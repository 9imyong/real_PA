"""Self-hosted llama.cpp/vLLM chat SSE adapter; not an external AI service."""
from __future__ import annotations
import asyncio
import json
import math
import os
import re
from urllib.parse import urlsplit
from ..contracts import Event, InvalidOutput, ProviderUnavailable, ConfigurationError, ContextCapacityExceeded

class ChatHttp:
    def __init__(self, config):
        self.config = config
        self.capabilities = config.capabilities
        self.client = None
        allowed = {'base_url','token_env','max_tokens','temperature','enable_thinking','system_prompt'}
        if config.options.keys() - allowed:
            raise ConfigurationError('unknown chat HTTP option')
        max_tokens = config.options.get('max_tokens', 128)
        if type(max_tokens) is not int or max_tokens < 1:
            raise ConfigurationError('max_tokens must be a positive integer')
        temperature = config.options.get('temperature', 0.3)
        if type(temperature) not in (int, float) or not math.isfinite(temperature) or temperature < 0:
            raise ConfigurationError('temperature must be finite and nonnegative')
        if 'enable_thinking' in config.options and type(config.options['enable_thinking']) is not bool:
            raise ConfigurationError('enable_thinking must be boolean')
        if 'system_prompt' in config.options and (not isinstance(config.options['system_prompt'], str) or
                not config.options['system_prompt'].strip() or len(config.options['system_prompt']) > 4000):
            raise ConfigurationError('system_prompt must be nonempty text of at most 4000 characters')
        if 'token_env' in config.options and (not isinstance(config.options['token_env'], str) or
                not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', config.options['token_env'])):
            raise ConfigurationError('token_env must name an environment variable')
        url = config.options.get('base_url', '')
        try:
            if not isinstance(url, str):
                raise ValueError
            parsed = urlsplit(url)
            parsed.port
        except ValueError as exc:
            raise ConfigurationError('invalid inference endpoint') from exc
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
        messages = list(request.data['messages'])
        prompt = self.config.options.get('system_prompt')
        if prompt:
            messages.insert(0, {'role':'system', 'content':prompt})
        body = {'model':self.config.manifest['model_id'],
                'messages':messages, 'stream':True,
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
                    if response.status_code == 400:
                        raw_error = bytearray()
                        async for chunk in response.aiter_bytes():
                            context.check()
                            raw_error.extend(chunk)
                            if len(raw_error) > 16384:
                                break
                        if len(raw_error) <= 16384:
                            try:
                                error = json.loads(raw_error).get('error', {})
                                if isinstance(error, dict) and (error.get('type') == 'exceed_context_size_error' or
                                        error.get('code') == 'context_length_exceeded'):
                                    raise ContextCapacityExceeded('inference context capacity exceeded')
                            except (ValueError, AttributeError):
                                pass
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
