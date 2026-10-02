"""Standalone browser + duplex API, usable by future Lemmy clients."""
import asyncio
import contextlib
from http import HTTPStatus
from importlib.resources import files
import json
import os
from urllib.parse import urlsplit

from websockets.http11 import Response
from websockets.datastructures import Headers

from .composition import registry
from .config import read_config
from .contracts import ConfigurationError
from .robot_gateway import RobotGateway

REQUIREMENTS = {'llm': {'stream', 'cancel'}, 'stt': {'partial', 'final'},
                'tts': {'chunks', 'cancel'}, 'vad': {'stream'}, 'kws': {'stream'}}
ASSETS = {'/': ('index.html', 'text/html; charset=utf-8'),
          '/index.html': ('index.html', 'text/html; charset=utf-8'),
          '/client.js': ('client.js', 'text/javascript; charset=utf-8'),
          '/realtime-client.js': ('realtime-client.js', 'text/javascript; charset=utf-8'),
          '/capture.js': ('capture.js', 'text/javascript; charset=utf-8'),
          '/style.css': ('style.css', 'text/css; charset=utf-8')}


def response(status, body, content_type='application/json; charset=utf-8'):
    return Response(status.value, status.phrase,
                    Headers({'Content-Type': content_type, 'Content-Length': str(len(body)),
                             'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}), body)


class DuplexAPI:
    def __init__(self, providers, token, *, max_sessions=4, idle_timeout=300):
        self.providers = providers
        self.gateway = RobotGateway(providers, token, idle_timeout=idle_timeout)
        self.max_sessions = max_sessions
        self.active = 0

    def process_request(self, connection, request):
        path = urlsplit(request.path).path
        if path == '/v1/realtime':
            return None
        if path == '/healthz':
            return response(HTTPStatus.OK, json.dumps({'status': 'ready', 'protocol_version': 1,
                                                       'roles': sorted(self.providers)}).encode())
        asset = ASSETS.get(path)
        if asset is not None:
            name, content_type = asset
            body = files('real_pa').joinpath('browser', name).read_bytes()
            return response(HTTPStatus.OK, body, content_type)
        return response(HTTPStatus.NOT_FOUND, b'{"error":"not_found"}')

    async def handle(self, ws):
        if self.active >= self.max_sessions:
            await ws.close(1013, 'session capacity reached')
            return
        self.active += 1
        try:
            await self.gateway.handle(ws)
        finally:
            self.active -= 1


async def serve_api(config_path, host='127.0.0.1', port=18484,
                    token_env='REAL_PA_API_TOKEN', origins=()):
    from websockets.asyncio.server import serve
    if host not in {'127.0.0.1', 'localhost', '::1'} and not origins:
        raise ConfigurationError('remote API requires explicit browser origins and a TLS proxy')
    token = os.environ.get(token_env)
    if not token or len(token) < 16:
        raise ConfigurationError('API client credential must have at least 16 characters')
    providers = await registry().build(read_config(config_path), REQUIREMENTS)
    try:
        api = DuplexAPI(providers, token)
        allowed = list(origins) if origins else [f'http://localhost:{port}', f'http://127.0.0.1:{port}']
        # Non-browser clients (e.g. future Lemmy service) still authenticate via start.
        async with serve(api.handle, host, port, origins=[None, *allowed],
                         process_request=api.process_request, max_size=65536,
                         max_queue=8, compression=None, server_header=None):
            await asyncio.Event().wait()
    finally:
        for provider in reversed(list(providers.values())):
            with contextlib.suppress(Exception):
                await provider.close()
