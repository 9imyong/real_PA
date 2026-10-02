"""Bridge the existing Lemmy LlmPort to a self-hosted provider."""
import asyncio
import json
import uuid
from ..contracts import Context, Request, ConfigurationError


def json_schema(value):
    if isinstance(value,list):
        return [json_schema(x) for x in value]
    if not isinstance(value,dict):
        return value
    result = {k:json_schema(v) for k,v in value.items() if k != 'nullable'}
    if isinstance(result.get('type'),str):
        result['type'] = result['type'].lower()
    if value.get('nullable') and isinstance(result.get('type'),str):
        result['type'] = [result['type'],'null']
    return result


def chat_messages(messages, system_instruction=None):
    result = []
    pending = []
    if system_instruction:
        result.append({'role':'system','content':system_instruction})
    for mi,message in enumerate(messages):
        text = ''.join(p.text for p in message.parts if p.text is not None)
        calls = []
        for pi,part in enumerate(message.parts):
            if part.tool_call is not None:
                call = part.tool_call
                cid = f'call_{mi}_{pi}'
                pending.append((call.name,cid))
                calls.append({'id':cid,'type':'function','function':{
                    'name':call.name,'arguments':json.dumps(call.arguments,ensure_ascii=False)}})
        if text or calls:
            entry = {'role':message.role,'content':text or None}
            if calls:
                entry['tool_calls'] = calls
            result.append(entry)
        for part in message.parts:
            if part.tool_result is not None:
                tool = part.tool_result
                match = next(((i,cid) for i,(name,cid) in enumerate(pending) if name==tool.name),None)
                if match is None:
                    raise ConfigurationError('tool result has no preceding call')
                i,cid = match
                pending.pop(i)
                result.append({'role':'tool','tool_call_id':cid,
                               'content':json.dumps(tool.response,ensure_ascii=False)})
    return result


class LemmyLlmAdapter:
    def __init__(self, provider, *, schema_module=None):
        self.provider = provider
        self.schema_module = schema_module
        self.loaded = False
        self.lock = asyncio.Lock()

    async def _ready(self):
        if not self.loaded:
            async with self.lock:
                if not self.loaded:
                    await self.provider.load()
                    self.loaded = True
        if self.schema_module is None:
            # Import belongs to the integration adapter, never dialogue core.
            from app.modules.conversation import schemas
            self.schema_module = schemas

    async def stream(self, request):
        await self._ready()
        data = {'messages':chat_messages(request.messages,request.options.system_instruction)}
        tools = []
        for group in request.options.tools:
            for tool in group.get('function_declarations',[]):
                tools.append({'type':'function','function':json_schema(tool)})
        if tools:
            data['tools'] = tools
        context = Context(str(uuid.uuid4()),1,1,self.provider.config.timeout)
        async for event in self.provider.stream(Request('llm',data),context):
            if event.kind == 'text_delta':
                yield self.schema_module.LlmStreamEvent('text',text=event.data['text'])
            elif event.kind == 'tool_call':
                yield self.schema_module.LlmStreamEvent('tool_call',tool_call=
                    self.schema_module.ToolCall(event.data['name'],event.data['arguments']))

    async def generate_text(self, request):
        await self._ready()
        result = []
        context = Context(str(uuid.uuid4()),1,1,self.provider.config.timeout)
        async for event in self.provider.stream(Request('llm',{'messages':[
            {'role':'user','content':request.prompt}]}),context):
            if event.kind == 'text_delta':
                result.append(event.data['text'])
        return ''.join(result)

    async def get_cache_key(self, system_instruction):
        return None

    async def clear_cache(self):
        pass

    async def close(self):
        await self.provider.close()
        self.loaded = False


class LazyLemmyLlmAdapter:
    def __init__(self, config_path):
        self.config_path = config_path
        self.delegate = None

    def _get(self):
        if self.delegate is None:
            from ..config import read_config
            from ..composition import registry
            config = read_config(self.config_path).get('llm')
            if config is None:
                raise ConfigurationError('Lemmy requires an llm provider')
            factory = registry().factories.get(('llm',config.adapter))
            if factory is None:
                raise ConfigurationError('unknown Lemmy llm adapter')
            self.delegate = LemmyLlmAdapter(factory(config))
        return self.delegate

    def stream(self, request):
        return self._get().stream(request)

    async def generate_text(self, request):
        return await self._get().generate_text(request)

    async def get_cache_key(self, system_instruction):
        return None

    async def clear_cache(self):
        if self.delegate:
            await self.delegate.clear_cache()

    async def close(self):
        if self.delegate:
            await self.delegate.close()
