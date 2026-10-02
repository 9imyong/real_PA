"""Self-hosted llama.cpp/vLLM chat SSE adapter; not an external AI service."""
from __future__ import annotations
import asyncio
import json
import os
from urllib.parse import urlsplit
from ..contracts import Event, InvalidOutput, ProviderUnavailable, ConfigurationError

class ChatHttp:
    def __init__(self, config):
        self.config = config
        self.capabilities = config.capabilities
        self.client = None
        allowed = {'base_url','token_env','max_tokens','temperature','enable_thinking'}
        if config.options.keys() - allowed:
            raise ConfigurationError('unknown chat HTTP option')
        url = config.options.get('base_url', '')
        parsed = urlsplit(url)
        if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ConfigurationError('invalid inference endpoint')
        # Network location is explicitly operator-configured, never model-controlled.
        self.url = url.rstrip('/') + '/chat/completions'

    async def load(self):
        import httpx
        headers = {}
        name = self.config.options.get('token_env')
        if name:
            token = os.environ.get(name)
            if not token:
                raise ConfigurationError('missing server credential')
            headers['Authorization'] = 'Bearer ' + token
        self.client = httpx.AsyncClient(timeout=self.config.timeout,
                                        headers=headers, trust_env=False,
                                        follow_redirects=False)

    async def stream(self, request, context):
        if self.client is None or request.role != 'llm':
            raise ConfigurationError('chat adapter is not ready')
        context.check()
        body = {'model':self.config.manifest['model_id'],
                'messages':request.data['messages'], 'stream':True,
                'max_tokens':self.config.options.get('max_tokens',128),
                'temperature':self.config.options.get('temperature',0.3)}
        if 'enable_thinking' in self.config.options:
            body['chat_template_kwargs'] = {'enable_thinking':self.config.options['enable_thinking']}
        if request.data.get('tools'):
            self.capabilities.require({'tools'})
            body['tools'] = request.data['tools']
        calls = {}
        complete = False
        try:
            import httpx
            async with asyncio.timeout(max(0.001,context.deadline - __import__('time').monotonic())):
                async with self.client.stream('POST',self.url,json=body) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        context.check()
                        if not line.startswith('data:'):
                            continue
                        raw = line[5:].strip()
                        if raw == '[DONE]':
                            complete = True
                            break
                        try:
                            event = json.loads(raw)
                            choices = event.get('choices', [])
                            if not choices:
                                continue
                            delta = choices[0].get('delta',{})
                            text = delta.get('content')
                            if text:
                                yield Event('text_delta',{'text':text})
                            for fragment in delta.get('tool_calls',[]):
                                index = fragment['index']
                                call = calls.setdefault(index,{'id':'','name':'','arguments':''})
                                if fragment.get('id'):
                                    call['id'] = fragment['id']
                                function = fragment.get('function',{})
                                call['name'] += function.get('name','')
                                call['arguments'] += function.get('arguments','')
                        except (ValueError, KeyError, TypeError, IndexError) as exc:
                            raise InvalidOutput('invalid chat stream') from exc
                    if not complete:
                        raise InvalidOutput('chat stream ended without completion')
            for call in calls.values():
                context.check()
                try:
                    args = json.loads(call['arguments'])
                    if not isinstance(args,dict) or not call['id'] or not call['name']:
                        raise ValueError
                except ValueError as exc:
                    raise InvalidOutput('invalid tool call') from exc
                yield Event('tool_call',{'id':call['id'],'name':call['name'],'arguments':args})
            context.check()
            yield Event('completed')
        except httpx.HTTPError as exc:
            raise ProviderUnavailable('self-hosted inference request failed') from exc

    async def reset(self, session_id):
        # Chat messages belong to the dialogue controller, not this adapter.
        return None

    async def close(self):
        if self.client is not None:
            await self.client.aclose()
            self.client = None
