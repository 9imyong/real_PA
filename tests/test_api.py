"""Real HTTP/WebSocket boundaries, with fixture inference only."""
import json
import asyncio
import unittest
from contextlib import asynccontextmanager

import httpx
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed, InvalidStatus

from real_pa.api import DuplexAPI
from test_robot import AudioFixture
from test_runtime import FixtureProvider

TOKEN = 'unit-api-credential-not-production'


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_turn_can_be_followed_by_text_and_audio_on_the_same_connection(self):
        class FailOnce(FixtureProvider):
            calls = 0
            async def stream(self, request, context):
                self.calls += 1
                if self.calls == 1:
                    raise TimeoutError('fixture inference failure')
                async for event in super().stream(request, context):
                    yield event
        async with self.server() as (api, _, url):
            api.providers['llm'] = FailOnce()
            async with connect(url) as ws:
                await ws.send(json.dumps({'type': 'start', 'token': TOKEN, 'ui_started': True}))
                await ws.recv()
                await ws.send(json.dumps({'type': 'text', 'text': '첫 요청'}))
                async with asyncio.timeout(10):
                    while True:
                        event = json.loads(await ws.recv())
                        if event['type'] == 'error':
                            self.assertEqual(event['data']['code'], 'turn_failed')
                            break
                await ws.send(b'\0\0' * 1600)
                await ws.send(json.dumps({'type': 'text', 'text': '후속 요청'}))
                types = []
                async with asyncio.timeout(10):
                    while True:
                        event = json.loads(await ws.recv())
                        types.append(event['type'])
                        if event['type'] == 'audio_chunk':
                            await ws.send(json.dumps({'type': 'playback_ack', 'generation_id': event['generation_id'],
                                                     'chunk_id': event['data']['chunk_id']}))
                        if event['type'] == 'turn_done': break
                self.assertIn('text_delta', types)
                self.assertIn('audio_chunk', types)
                self.assertNotIn('error', types)
                self.assertEqual(api.active, 1)

    @asynccontextmanager
    async def server(self, *, max_sessions=4):
        providers = dict(llm=FixtureProvider(), tts=FixtureProvider('tts'),
                         **{r: AudioFixture(r) for r in ['stt', 'vad', 'kws']})
        api = DuplexAPI(providers, TOKEN, max_sessions=max_sessions)
        async with serve(api.handle, '127.0.0.1', 0, process_request=api.process_request,
                         origins=[None, 'http://allowed.test'], compression=None, max_size=65536) as server:
            port = server.sockets[0].getsockname()[1]
            yield api, f'http://127.0.0.1:{port}', f'ws://127.0.0.1:{port}/v1/realtime'

    async def test_browser_and_health_are_served_on_the_api_origin(self):
        async with self.server() as (_, http, _):
            async with httpx.AsyncClient(trust_env=False) as client:
                for path in ['/', '/client.js', '/realtime-client.js', '/capture.js', '/style.css']:
                    result = await client.get(http + path)
                    self.assertEqual(result.status_code, 200)
                    self.assertTrue(result.content)
                result = await client.get(http + '/healthz')
                self.assertEqual(result.json()['protocol_version'], 1)
                self.assertEqual((await client.get(http + '/pyproject.toml')).status_code, 404)

    async def test_authenticated_text_stream_and_playback_ack(self):
        async with self.server() as (_, _, url):
            async with connect(url) as ws:
                await ws.send(json.dumps({'type': 'start', 'token': TOKEN, 'ui_started': True}))
                self.assertEqual(json.loads(await ws.recv())['type'], 'session_started')
                await ws.send(json.dumps({'type': 'text', 'text': '시험 대화'}))
                types = []
                while True:
                    event = json.loads(await ws.recv())
                    types.append(event['type'])
                    if event['type'] == 'audio_chunk':
                        await ws.send(json.dumps({'type': 'playback_ack', 'generation_id': event['generation_id'],
                                                 'chunk_id': event['data']['chunk_id']}))
                    if event['type'] == 'turn_done': break
                self.assertIn('text_delta', types)
                self.assertIn('audio_chunk', types)
                await ws.send(json.dumps({'type': 'close'}))

    async def test_invalid_credential_and_wrong_origin_are_rejected(self):
        async with self.server() as (_, _, url):
            async with connect(url) as ws:
                await ws.send(json.dumps({'type': 'start', 'token': 'wrong'}))
                with self.assertRaises(ConnectionClosed): await ws.recv()
                self.assertEqual(ws.close_code, 1008)
            with self.assertRaises(InvalidStatus) as error:
                async with connect(url, origin='http://foreign.test'):
                    self.fail('wrong origin admitted')
            self.assertEqual(error.exception.response.status_code, 403)

    async def test_session_capacity_rejects_without_blocking_an_active_session(self):
        async with self.server(max_sessions=1) as (api, _, url):
            async with connect(url) as first:
                await first.send(json.dumps({'type': 'start', 'token': TOKEN}))
                await first.recv()
                async with connect(url) as second:
                    with self.assertRaises(ConnectionClosed): await second.recv()
                    self.assertEqual(second.close_code, 1013)
                self.assertEqual(api.active, 1)
                await first.send(json.dumps({'type': 'text', 'text': '계속 대화'}))
                while json.loads(await first.recv())['type'] != 'turn_done': pass
