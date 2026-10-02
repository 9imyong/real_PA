"""Client-routed tools: the client picks each turn's tools and executes them."""
import asyncio
import copy
import json
import re
from dataclasses import dataclass, field

from .contracts import Event, Request

MAX_TOOLS = 16
MAX_TOOLS_JSON = 32768
MAX_RESULT_BYTES = 65536
TOOL_CHOICES = frozenset({'auto', 'required', 'none'})
MAX_PREFETCHED = 4
MAX_REPLY = 500
_NAME = re.compile(r'[A-Za-z0-9_-]{1,64}')
_ID = re.compile(r'[A-Za-z0-9_:.-]{1,128}')


def validate_tools(tools):
    """Return {name: definition} for OpenAI-style function definitions."""
    if not isinstance(tools, list) or not 1 <= len(tools) <= MAX_TOOLS:
        raise ValueError('tools must be a nonempty list')
    if len(json.dumps(tools, ensure_ascii=False)) > MAX_TOOLS_JSON:
        raise ValueError('tool definitions too large')
    registered = {}
    for tool in tools:
        function = tool.get('function') if isinstance(tool, dict) else None
        if (tool.get('type') != 'function' or not isinstance(function, dict)
                or not isinstance(function.get('name'), str) or not _NAME.fullmatch(function['name'])
                or not isinstance(function.get('description', ''), str)
                or not isinstance(function.get('parameters', {}), dict)
                or function['name'] in registered):
            raise ValueError('invalid tool definition')
        registered[function['name']] = copy.deepcopy(tool)
    return registered


def _json_size(value):
    return len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode())


@dataclass
class Route:
    """One turn's routing decision from the client.

    ``prefetched``: lookups the client already executed (deterministic arguments);
    the model only answers from them and gets no tools. ``reply``: fixed text spoken
    instead of generating, e.g. a fail-closed notice when a required lookup failed.
    """
    tools: list = field(default_factory=list)
    choice: str = 'none'
    prefetched: list = field(default_factory=list)
    reply: str | None = None


class PrefetchedAnswer:
    """LLM wrapper that replays client-executed lookups as this turn's tool messages."""

    def __init__(self, llm, calls, reply, tools=()):
        self.llm, self.calls, self.reply, self.tools = llm, calls, reply, list(tools)
        self.capabilities = llm.capabilities

    def _results(self):
        return [Event('tool_result', {'call': {k: c[k] for k in ('id', 'name', 'arguments')}, 'result': c['result']})
                for c in self.calls]

    async def stream(self, request, context):
        if self.reply is not None:
            for event in self._results():
                yield event
            yield Event('text_delta', {'text': self.reply})
            yield Event('completed')
            return
        messages = list(request.data['messages'])
        messages.append({'role': 'assistant', 'content': None, 'tool_calls': [
            {'id': c['id'], 'type': 'function', 'function': {
                'name': c['name'], 'arguments': json.dumps(c['arguments'], ensure_ascii=False)}} for c in self.calls]})
        messages += [{'role': 'tool', 'tool_call_id': c['id'], 'content': json.dumps(c['result'], ensure_ascii=False)}
                     for c in self.calls]
        pending = self._results()
        # Results join the history only once the model accepted the request, so a
        # capacity retry with trimmed history never records them twice.
        data = {'messages': messages}
        if self.tools:
            # Same schemas as other turns (cache prefix), but the answer may not call them.
            data.update(tools=self.tools, tool_choice='none')
        async for event in self.llm.stream(Request('llm', data, request.local), context):
            while pending:
                yield pending.pop(0)
            yield event

    async def reset(self, session_id):
        await self.llm.reset(session_id)


class ClientToolBridge:
    """Per-connection broker; real-PA holds definitions but never tool code."""

    def __init__(self, tools, *, route_timeout=1.5, tool_timeout=15.0):
        self.tools = validate_tools(tools)
        self.route_timeout = route_timeout
        self.tool_timeout = tool_timeout
        self._routes = {}
        self._outputs = {}

    async def route(self, request_id, text, emit):
        """Ask the client for this turn's tools; any failure means no tools."""
        future = asyncio.get_running_loop().create_future()
        self._routes[request_id] = future
        try:
            await emit(Event('route_request', {'request_id': request_id, 'text': text}))
            try:
                route = await asyncio.wait_for(future, self.route_timeout)
            except TimeoutError:
                return Route()
        finally:
            self._routes.pop(request_id, None)
        # Keep the client's tool list even with tool_choice "none": chat templates put
        # tool schemas at the start of the prompt, so dropping or changing them per
        # turn invalidates the inference server's prefix cache (measured ~0.7-1.5s).
        route.tools = [copy.deepcopy(self.tools[name]) for name in route.tools]
        return route

    def resolve_route(self, command):
        future = self._routes.get(command.get('request_id'))
        if future is None or future.done():
            return  # Late or unknown routes belong to a superseded turn.
        names, choice = command.get('tools', []), command.get('tool_choice', 'auto')
        prefetched, reply = command.get('prefetched', []), command.get('reply')
        try:
            valid = (isinstance(names, list) and len(names) <= MAX_TOOLS
                     and all(isinstance(name, str) and name in self.tools for name in names)
                     and len(set(names)) == len(names) and choice in TOOL_CHOICES
                     and isinstance(prefetched, list) and len(prefetched) <= MAX_PREFETCHED
                     and all(isinstance(item, dict) and item.get('name') in self.tools
                             and isinstance(item.get('arguments'), dict) and isinstance(item.get('result'), dict)
                             and _json_size(item['result']) <= MAX_RESULT_BYTES for item in prefetched)
                     and (reply is None or (isinstance(reply, str) and reply.strip() and len(reply) <= MAX_REPLY)))
        except ValueError:
            valid = False
        future.set_result(Route(names, choice, copy.deepcopy(prefetched), reply) if valid else Route())

    async def execute(self, call, operation_key, emit):
        """Delegate one model call; timeouts and bad output are failure results."""
        call_id = call['id']
        future = asyncio.get_running_loop().create_future()
        self._outputs[call_id] = future
        try:
            await emit(Event('tool_call', {'call_id': call_id, 'name': call['name'],
                                           'arguments': call['arguments'], 'operation_key': operation_key}))
            try:
                return await asyncio.wait_for(future, self.tool_timeout)
            except TimeoutError:
                return {'error': 'tool_timeout'}
        finally:
            self._outputs.pop(call_id, None)

    def resolve_output(self, command):
        call_id = command.get('call_id')
        future = self._outputs.get(call_id) if isinstance(call_id, str) and _ID.fullmatch(call_id) else None
        if future is None or future.done():
            return
        result = command.get('result')
        try:
            valid = isinstance(result, dict) and len(
                json.dumps(result, ensure_ascii=False, allow_nan=False).encode()) <= MAX_RESULT_BYTES
        except ValueError:
            valid = False
        future.set_result(result if valid else {'error': 'invalid_tool_output'})
