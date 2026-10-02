"""Robot-owned tool loop; inference never executes business actions."""
import asyncio
import copy
import json
import uuid

from .contracts import Event, Request, InvalidOutput, ResourceExhausted


class ToolLoop:
    def __init__(self, provider, tools, execute, *, system_prompt='',
                 write_tools=frozenset(), max_rounds=4, max_calls=8):
        provider.capabilities.require({'stream', 'cancel', 'tools'})
        self.provider = provider
        self.capabilities = provider.capabilities
        self.tools = copy.deepcopy(tools)
        self.allowed = {t['function']['name'] for t in tools}
        self.execute = execute
        self.system_prompt = system_prompt
        self.write_tools = frozenset(write_tools)
        self.max_rounds, self.max_calls = max_rounds, max_calls
        self.business_tasks = set()

    async def load(self):
        # Composition has already loaded and negotiated the underlying provider.
        return None

    async def _execute(self, call, context, local, operation_key):
        async def bounded():
            async with asyncio.timeout(30):
                return await self.execute(call, context, local, operation_key)
        if call['name'] not in self.write_tools:
            return await bounded()
        if len(self.business_tasks) >= self.max_calls:
            raise ResourceExhausted('too many active business operations')
        task = asyncio.create_task(bounded())
        self.business_tasks.add(task)
        def finished(done):
            self.business_tasks.discard(done)
            if not done.cancelled():
                done.exception()
        task.add_done_callback(finished)
        # Audio interruption cancels the waiter, not an already-started write.
        return await asyncio.shield(task)

    async def stream(self, request, context):
        messages = copy.deepcopy(request.data['messages'])
        if self.system_prompt:
            messages.insert(0, {'role': 'system', 'content': self.system_prompt})
        local = dict(request.local)
        local.setdefault('request_id', str(uuid.uuid4()))
        count = 0
        for _ in range(self.max_rounds):
            calls, text, completed = [], '', False
            # local (including biometric audio) NEVER crosses the LLM RPC boundary.
            upstream = Request('llm', {'messages': messages, 'tools': self.tools})
            async for event in self.provider.stream(upstream, context):
                context.check()
                if event.kind == 'tool_call':
                    raw = event.data
                    if (raw.get('name') not in self.allowed
                            or not isinstance(raw.get('arguments'), dict)):
                        raise InvalidOutput('unavailable tool call')
                    count += 1
                    if count > self.max_calls:
                        raise ResourceExhausted('tool call limit exceeded')
                    calls.append({'id': f'call_{context.turn_id}_{count}',
                                  'name': raw['name'], 'arguments': copy.deepcopy(raw['arguments'])})
                elif event.kind == 'completed':
                    completed = True
                elif event.kind == 'text_delta':
                    text += event.data['text']
                    yield event
            if not completed:
                raise InvalidOutput('tool round ended without completion')
            if not calls:
                yield Event('completed')
                return
            messages.append({'role': 'assistant', 'content': text or None, 'tool_calls': [
                {'id': c['id'], 'type': 'function', 'function': {
                    'name': c['name'], 'arguments': json.dumps(c['arguments'], ensure_ascii=False)}} for c in calls]})
            for call in calls:
                context.check()
                # One registration per user request; repeat calls replay its result.
                # Different arguments under this key conflict at the Lemmy store.
                key = f"{local['request_id']}:{call['name']}"
                yield Event('tool_started', {'name': call['name'], 'operation_key': key})
                result = await self._execute(call, context, local, key)
                context.check()
                encoded = json.dumps(result, ensure_ascii=False, allow_nan=False)
                if len(encoded.encode()) > 65536:
                    raise ResourceExhausted('tool result exceeded context limit')
                messages.append({'role': 'tool', 'tool_call_id': call['id'], 'content': encoded})
                yield Event('tool_result', {'call': call, 'result': result, 'operation_key': key})
        raise ResourceExhausted('tool round limit exceeded')

    async def reset(self, session_id):
        await self.provider.reset(session_id)

    async def close(self):
        # Bounded jobs finish before their provider/connection owner is released.
        if self.business_tasks:
            await asyncio.gather(*self.business_tasks, return_exceptions=True)
        await self.provider.close()
