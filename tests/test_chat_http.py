"""HTTP adapter cancellation at the final response cleanup boundary."""
import asyncio
from pathlib import Path
import unittest

import httpx
from real_pa.adapters.chat_http import ChatHttp
from real_pa.config import ProviderConfig
from real_pa.contracts import Context, Request


class ChatHttpCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_response_cleanup_cancellation_does_not_emit_completion(self):
        context = Context('s', 1, 1)
        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'data: [DONE]\n\n'
            async def aclose(self):
                context.cancelled.set()
        config = ProviderConfig('llm', 'chat_http', {'model_id': 'fixture',
            'features': ['stream', 'cancel'], 'languages': ['ko']},
            {'base_url': 'http://localhost:1/v1'}, 1, Path('fixture'))
        provider = ChatHttp(config)
        provider.client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, stream=Stream())))
        try:
            with self.assertRaises(asyncio.CancelledError):
                async for _ in provider.stream(Request('llm', {'messages': []}), context):
                    self.fail('cancelled inference emitted completion')
        finally:
            await provider.close()
