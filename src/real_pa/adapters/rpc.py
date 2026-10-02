"""Authenticated self-hosted RPC: receive continues while inference streams."""
from __future__ import annotations
import asyncio
import base64
import json
import os
import secrets
import time
from urllib.parse import urlsplit
from ..contracts import (Request, Context, Event, ProviderUnavailable,
                         ConfigurationError, InvalidOutput)


def encode(value):
    if isinstance(value, bytes):
        return {'$pcm16': base64.b64encode(value).decode('ascii')}
    if isinstance(value, dict):
        if '$pcm16' in value:
            raise ValueError('reserved wire key')
        return {k: encode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [encode(v) for v in value]
    return value


def decode(value):
    if isinstance(value, dict):
        if set(value) == {'$pcm16'}:
            return base64.b64decode(value['$pcm16'], validate=True)
        return {k: decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [decode(v) for v in value]
    return value


class RemoteProvider:
    def __init__(self, config):
        self.config = config
        self.capabilities = config.capabilities
        if config.options.keys() - {'url', 'token_env'}:
            raise ConfigurationError('unknown RPC option')
        self.url = config.options.get('url', '')
        parsed = urlsplit(self.url)
        if parsed.scheme not in {'ws', 'wss'} or not parsed.hostname or parsed.username or parsed.password:
            raise ConfigurationError('invalid inference RPC endpoint')
        if parsed.scheme == 'ws' and parsed.hostname not in {'127.0.0.1', 'localhost', '::1'}:
            raise ConfigurationError('company network RPC requires TLS')
        self.token = None
        self.sockets = set()

    async def load(self):
        name = self.config.options.get('token_env')
        self.token = os.environ.get(name) if name else None
        if not self.token:
            raise ConfigurationError('missing RPC credential')
        # Negotiate actual server capabilities; a local manifest cannot invent them.
        from websockets.asyncio.client import connect
        try:
            async with connect(self.url, proxy=None, open_timeout=self.config.timeout) as ws:
                await ws.send(json.dumps({'type': 'hello', 'token': self.token,
                                          'role': self.config.role}))
                raw = json.loads(await asyncio.wait_for(ws.recv(), self.config.timeout))
                if raw.get('type') != 'capabilities' or raw.get('role') != self.config.role:
                    raise InvalidOutput('invalid capability response')
                identity = raw.get('model_identity',{})
                for key in ['model_id','revision','runtime']:
                    expected = self.config.manifest.get(key)
                    if expected is not None and identity.get(key) != expected:
                        raise InvalidOutput('worker model identity mismatch')
                expected_hashes = self.config.manifest.get('artifact_fingerprints')
                if expected_hashes is not None and identity.get('artifact_fingerprints') != expected_hashes:
                    raise InvalidOutput('worker artifact identity mismatch')
                from ..contracts import Capabilities
                self.capabilities = Capabilities(raw['role'], frozenset(raw['features']),
                                                 frozenset(raw['languages']))
        except (OSError, TimeoutError) as exc:
            raise ProviderUnavailable('inference RPC unavailable') from exc

    async def stream(self, request, context):
        from websockets.asyncio.client import connect
        if self.token is None or request.role != self.config.role:
            raise ConfigurationError('RPC adapter not loaded or role mismatch')
        context.check()
        try:
            async with asyncio.timeout(max(0.001, context.deadline - time.monotonic())):
                async with connect(self.url, proxy=None, open_timeout=self.config.timeout,
                                   max_size=1024 * 1024) as ws:
                    self.sockets.add(ws)
                    try:
                        await ws.send(json.dumps({'type': 'infer', 'token': self.token,
                            'role': request.role, 'data': encode(request.data),
                            'session_id': context.session_id, 'turn_id': context.turn_id,
                            'generation_id': context.generation_id,
                            'timeout': min(context.timeout, self.config.timeout)}))
                        completed = False
                        async for message in ws:
                            context.check()
                            raw = json.loads(message)
                            if raw.get('generation_id') != context.generation_id:
                                raise InvalidOutput('RPC generation mismatch')
                            if raw.get('type') == 'error':
                                raise ProviderUnavailable('inference worker failed')
                            if raw.get('type') != 'event':
                                raise InvalidOutput('invalid RPC event')
                            event = Event(raw['kind'], decode(raw.get('data', {})))
                            yield event
                            if event.kind == 'completed':
                                completed = True
                                break
                        if not completed:
                            raise InvalidOutput('RPC ended without completion')
                    finally:
                        self.sockets.discard(ws)
                        # Disconnect is a cancellation signal to the worker.
        except (OSError, json.JSONDecodeError) as exc:
            raise ProviderUnavailable('inference RPC failed') from exc

    async def reset(self, session_id):
        # Role sessions need an explicit reset on the worker (implemented by the
        # server handler); closing sockets only cancels current requests.
        from websockets.asyncio.client import connect
        async with connect(self.url, proxy=None, open_timeout=self.config.timeout) as ws:
            await ws.send(json.dumps({'type':'reset','token':self.token,
                'role':self.config.role,'session_id':session_id}))
            reply = json.loads(await asyncio.wait_for(ws.recv(),self.config.timeout))
            if reply.get('type') != 'reset_done':
                raise InvalidOutput('worker reset failed')

    async def close(self):
        for ws in list(self.sockets):
            await ws.close()
        self.sockets.clear()
        self.token = None


class InferenceGateway:
    def __init__(self, providers, token, *, max_concurrent=4):
        if not token or len(token) < 16:
            raise ConfigurationError('worker token must contain at least 16 characters')
        self.providers = providers
        self.token = token
        self.slots = asyncio.Semaphore(max_concurrent)
        self.active = 0
        self.cancelled = 0

    async def handle(self, ws):
        work = disconnect = None
        context = None
        try:
            raw = json.loads(await asyncio.wait_for(ws.recv(),10))
            if not secrets.compare_digest(str(raw.get('token', '')), self.token):
                await ws.close(1008, 'authentication required')
                return
            provider = self.providers.get(raw.get('role'))
            if provider is None:
                await ws.close(1008, 'unsupported role')
                return
            if raw.get('type') == 'hello':
                c = provider.capabilities
                manifest = getattr(getattr(provider,'config',None),'manifest',{})
                identity = {k:manifest.get(k) for k in ['model_id','revision','runtime']}
                identity['artifact_fingerprints'] = sorted(
                    [{'name':a.get('name','artifact'),'sha256':a['sha256']}
                     for a in manifest.get('artifacts',[])],key=lambda item:item['name'])
                await ws.send(json.dumps({'type':'capabilities','role':c.role,
                    'features':sorted(c.features),'languages':sorted(c.languages),
                    'model_identity':identity}))
                return
            if raw.get('type') == 'reset':
                await provider.reset(raw['session_id'])
                await ws.send(json.dumps({'type':'reset_done'}))
                return
            if raw.get('type') != 'infer':
                await ws.close(1008,'invalid request')
                return
            timeout = raw.get('timeout',30)
            if not isinstance(timeout,(int,float)) or not 0 < timeout <= 120:
                await ws.close(1008,'invalid timeout')
                return
            context = Context(raw['session_id'],raw['turn_id'],raw['generation_id'],timeout)
            request = Request(raw['role'],decode(raw['data']))

            async def infer():
                async with self.slots:
                    self.active += 1
                    try:
                        async with asyncio.timeout(timeout):
                            async for event in provider.stream(request,context):
                                context.check()
                                await ws.send(json.dumps({'type':'event',
                                    'generation_id':context.generation_id,
                                    'kind':event.kind,'data':encode(event.data)}))
                    finally:
                        self.active -= 1

            work = asyncio.create_task(infer())
            # Reading concurrently is essential: wait_closed alone doesn't
            # process a cancellation message received before disconnect.
            disconnect = asyncio.create_task(ws.recv())
            done,_ = await asyncio.wait({work,disconnect},return_when=asyncio.FIRST_COMPLETED)
            if disconnect in done and not work.done():
                self.cancelled += 1
                context.cancelled.set()
                work.cancel()
            await work
        except asyncio.CancelledError:
            raise
        except Exception:
            if context is not None:
                try:
                    await ws.send(json.dumps({'type':'error','generation_id':context.generation_id,
                                               'code':'inference_failed'}))
                except Exception:
                    pass
        finally:
            for task in (work,disconnect):
                if task is not None:
                    task.cancel()
            for task in (work,disconnect):
                if task is not None:
                    try:
                        await task
                    except BaseException:
                        pass
