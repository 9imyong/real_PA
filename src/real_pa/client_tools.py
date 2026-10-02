"""Client-routed tools: the client picks each turn's tools and executes them."""
import asyncio
import copy
import json
import re

from .contracts import Event

MAX_TOOLS = 16
MAX_TOOLS_JSON = 32768
MAX_RESULT_BYTES = 65536
TOOL_CHOICES = frozenset({'auto', 'required', 'none'})
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
                names, choice = await asyncio.wait_for(future, self.route_timeout)
            except TimeoutError:
                return [], 'none'
        finally:
            self._routes.pop(request_id, None)
        if not names or choice == 'none':
            return [], 'none'
        return [copy.deepcopy(self.tools[name]) for name in names], choice

    def resolve_route(self, command):
        future = self._routes.get(command.get('request_id'))
        if future is None or future.done():
            return  # Late or unknown routes belong to a superseded turn.
        names, choice = command.get('tools', []), command.get('tool_choice', 'auto')
        valid = (isinstance(names, list) and len(names) <= MAX_TOOLS
                 and all(isinstance(name, str) and name in self.tools for name in names)
                 and len(set(names)) == len(names) and choice in TOOL_CHOICES)
        future.set_result((names, choice) if valid else ([], 'none'))

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
