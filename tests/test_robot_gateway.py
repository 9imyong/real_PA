"""Duplex transport checks without opening network sockets."""
import asyncio
import json
import unittest

from real_pa.robot_gateway import RobotGateway, run_connection
from test_robot import AudioFixture
from test_runtime import FixtureProvider


class Socket:
    def __init__(self):
        self.input = asyncio.Queue()
        self.output = asyncio.Queue()
        self.closed = None

    async def recv(self):
        return await self.input.get()

    async def send(self, message):
        await self.output.put(json.loads(message))

    async def close(self, code=1000, reason=''):
        self.closed = code

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self.recv()

    async def wait_type(self, kind):
        async with asyncio.timeout(2):
            while True:
                event = await self.output.get()
                if event['type'] == kind:
                    return event


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    def providers(self):
        return dict(llm=FixtureProvider(gate=asyncio.Event()), tts=FixtureProvider('tts'),
                    **{r: AudioFixture(r) for r in ['stt', 'kws', 'vad']})

    async def test_authenticated_transport_consumes_audio_and_interrupts_generation(self):
        socket, providers = Socket(), self.providers()
        task = asyncio.create_task(run_connection(socket, providers, 'server-session', ui_started=True))
        try:
            started = await socket.wait_type('session_started')
            self.assertEqual(started['session_id'], 'server-session')
            socket.input.put_nowait(json.dumps({'type': 'text', 'text': '테스트'}))
            await socket.wait_type('interrupted')
            for _ in range(8):
                socket.input.put_nowait(b'\0\0' * 1600)
            async with asyncio.timeout(2):
                while providers['vad'].frames != 8:
                    await asyncio.sleep(.001)
            self.assertEqual(providers['stt'].frames, 0)
            socket.input.put_nowait(json.dumps({'type': 'text', 'text': '그만.'}))
            await socket.wait_type('interrupted')
            socket.input.put_nowait(json.dumps({'type': 'close'}))
            await asyncio.wait_for(task, 2)
            self.assertTrue(providers['llm'].was_cancelled)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_identity_revoked_before_input_does_not_start_generation(self):
        socket, providers = Socket(), self.providers()
        calls = 0

        async def authorize():
            nonlocal calls
            calls += 1
            return calls == 1

        socket.input.put_nowait(json.dumps({'type': 'text', 'text': '거절'}))
        await asyncio.wait_for(run_connection(socket, providers, 's', authorize=authorize), 2)
        self.assertEqual(socket.closed, 4401)
        self.assertFalse(providers['llm'].was_cancelled)

    async def test_idle_identity_revocation_cancels_inflight_generation(self):
        socket, providers = Socket(), self.providers()
        allowed = True

        async def authorize():
            return allowed

        task = asyncio.create_task(run_connection(socket, providers, 's', authorize=authorize))
        try:
            await socket.wait_type('session_started')
            socket.input.put_nowait(json.dumps({'type': 'text', 'text': '테스트'}))
            await socket.wait_type('interrupted')
            # Let the provider enter its blocked generator before revoking.
            await asyncio.sleep(.01)
            allowed = False
            await asyncio.wait_for(task, 2)
            self.assertEqual(socket.closed, 4401)
            self.assertTrue(providers['llm'].was_cancelled)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_development_start_rejects_non_object_and_invalid_mode(self):
        for hello in [[], {'type': 'start', 'token': 'a' * 16, 'ui_started': 'false'}]:
            with self.subTest(hello=hello):
                socket = Socket()
                socket.input.put_nowait(json.dumps(hello))
                await RobotGateway(self.providers(), 'a' * 16).handle(socket)
                self.assertEqual(socket.closed, 1008)
