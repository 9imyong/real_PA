"""HTTP adapter cancellation at the final response cleanup boundary."""
import asyncio
from pathlib import Path
import unittest

import httpx
from real_pa.adapters.chat_http import ChatHttp
from real_pa.config import ProviderConfig
from real_pa.contracts import Context, Request, ConfigurationError, ContextCapacityExceeded, ProviderUnavailable


class ChatHttpConfigurationTests(unittest.TestCase):
    def config(self, **options):
        return ProviderConfig('llm', 'chat_http', {'model_id': 'fixture',
            'features': ['stream', 'cancel'], 'languages': ['ko']},
            {'base_url': 'http://localhost:1/v1', **options}, 1, Path('fixture'))

    def test_invalid_options_are_rejected_before_http_client_creation(self):
        for options in ({'max_tokens': True}, {'max_tokens': 0}, {'max_tokens': 1.5},
                        {'temperature': True}, {'temperature': float('nan')},
                        {'temperature': float('inf')}, {'temperature': -1},
                        {'enable_thinking': 'false'}, {'token_env': ''}, {'token_env': 3},
                        {'base_url': 3}, {'base_url': 'http://localhost:invalid/v1'},
                        {'base_url': 'http://[invalid/v1'}):
            with self.subTest(options=options):
                with self.assertRaises(ConfigurationError):
                    ChatHttp(self.config(**options))

    def test_invalid_system_prompt_is_rejected(self):
        for prompt in ('', '   ', 3, 'x' * 4001):
            with self.assertRaises(ConfigurationError):
                ChatHttp(self.config(system_prompt=prompt))

    def test_zero_temperature_and_boolean_thinking_are_supported(self):
        provider = ChatHttp(self.config(temperature=0, max_tokens=96,
                                       enable_thinking=False, token_env='REAL_PA_LLM_TOKEN'))
        self.assertIsNone(provider.client)


class ChatHttpCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_system_prompt_is_prepended_without_mutating_conversation(self):
        import json
        messages = [{'role': 'user', 'content': 'synthetic question'}]
        config = ProviderConfig('llm', 'chat_http', {'model_id': 'fixture',
            'features': ['stream', 'cancel'], 'languages': ['ko']},
            {'base_url': 'http://localhost:1/v1', 'system_prompt': 'trusted assistant instruction'}, 1, Path('fixture'))
        seen = []
        def handler(request):
            seen.append(json.loads(request.content)['messages'])
            return httpx.Response(200, text='data: [DONE]\n\n')
        provider = ChatHttp(config)
        provider.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            for turn in (1, 2):
                async for _ in provider.stream(Request('llm', {'messages': messages}), Context('s', turn, turn)):
                    pass
            self.assertEqual(messages, [{'role': 'user', 'content': 'synthetic question'}])
            self.assertTrue(all(request == [{'role': 'system', 'content': 'trusted assistant instruction'}, *messages] for request in seen))
        finally:
            await provider.close()

    async def test_context_error_is_distinct_from_other_bad_requests(self):
        for error_type, expected in [('exceed_context_size_error', ContextCapacityExceeded),
                                     ('invalid_request_error', ProviderUnavailable)]:
            config = ProviderConfig('llm', 'chat_http', {'model_id': 'fixture',
                'features': ['stream', 'cancel'], 'languages': ['ko']},
                {'base_url': 'http://localhost:1/v1'}, 1, Path('fixture'))
            provider = ChatHttp(config)
            provider.client = httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(400, json={'error': {'type': error_type}})))
            try:
                with self.assertRaises(expected):
                    async for _ in provider.stream(Request('llm', {'messages': []}), Context('s', 1, 1)):
                        self.fail('rejected input produced an event')
            finally:
                await provider.close()

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
