import asyncio
import os
import unittest
from pathlib import Path

from real_pa.adapters.rpc import InferenceGateway, RemoteProvider, encode, decode
from real_pa.config import ProviderConfig
from real_pa.contracts import Context, Request, Event, ContextCapacityExceeded
from test_runtime import FixtureProvider

try:
    from websockets.asyncio.server import serve
    from websockets.asyncio.client import connect
except ImportError:
    serve = None


@unittest.skipIf(serve is None,'websockets dependency unavailable')
class RpcTests(unittest.IsolatedAsyncioTestCase):
    async def test_context_capacity_error_survives_rpc(self):
        async def rejected(request, context):
            raise ContextCapacityExceeded()
            yield Event('completed')
        self.fixture.stream = rejected
        remote = RemoteProvider(self.config)
        await remote.load()
        try:
            with self.assertRaises(ContextCapacityExceeded):
                async for _ in remote.stream(Request('llm', {'messages': []}), Context('s', 1, 1)):
                    self.fail('rejected request produced output')
        finally:
            await remote.close()

    async def asyncSetUp(self):
        self.token = 'test-token-long-enough'
        os.environ['REAL_PA_TEST_TOKEN'] = self.token
        self.fixture = FixtureProvider()
        self.gateway = InferenceGateway({'llm':self.fixture},self.token)
        self.server = await serve(self.gateway.handle,'127.0.0.1',0,max_size=1024*1024)
        self.url = 'ws://127.0.0.1:'+str(self.server.sockets[0].getsockname()[1])
        self.config = ProviderConfig('llm','remote',{'features':['stream','cancel'],'languages':['ko']},
            {'url':self.url,'token_env':'REAL_PA_TEST_TOKEN'},2,Path('fixture'))

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()
        os.environ.pop('REAL_PA_TEST_TOKEN',None)

    async def test_real_network_stream_and_negotiation(self):
        remote = RemoteProvider(self.config)
        await remote.load()
        events = [e async for e in remote.stream(Request('llm',{'messages':[]}),Context('s',1,1))]
        self.assertEqual([e.kind for e in events],['text_delta','completed'])
        self.assertEqual(events[0].data['text'],'안녕하세요.')
        await remote.close()

    async def test_disconnect_cancels_active_gpu_request(self):
        self.fixture.gate = asyncio.Event()
        remote = RemoteProvider(self.config)
        await remote.load()
        async def consume():
            return [e async for e in remote.stream(Request('llm',{'messages':[]}),Context('s',1,3))]
        task = asyncio.create_task(consume())
        for _ in range(100):
            if self.gateway.active:
                break
            await asyncio.sleep(.005)
        self.assertEqual(self.gateway.active,1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        for _ in range(100):
            if self.fixture.was_cancelled:
                break
            await asyncio.sleep(.005)
        self.assertTrue(self.fixture.was_cancelled)
        self.assertEqual(self.gateway.active,0)
        await remote.close()

    async def test_invalid_token_cannot_infer(self):
        async with connect(self.url,proxy=None) as ws:
            await ws.send('{"type":"hello","token":"bad","role":"llm"}')
            with self.assertRaises(Exception):
                await ws.recv()
            self.assertEqual(ws.close_code,1008)

    def test_pcm_wire_round_trip(self):
        data = {'pcm':b'\x00\x01\xff\x00','sample_rate':16000}
        self.assertEqual(decode(encode(data)),data)
