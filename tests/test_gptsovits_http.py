import asyncio
import json
from pathlib import Path
import unittest

import httpx
from real_pa.adapters.gptsovits_http import GptSovitsHttp
from real_pa.config import ProviderConfig
from real_pa.contracts import Context, Request, ConfigurationError, InvalidOutput, ProviderUnavailable


def config(**options):
    return ProviderConfig('tts', 'gptsovits_http', {'model_id': 'fixture',
        'features': ['phrase', 'chunks', 'cancel'], 'languages': ['ko'], 'sample_rates': [32000]},
        {'url': 'http://localhost:9880/tts', 'sample_rate': 32000,
         'ref_audio_path': '/operator/synthetic.wav', **options}, 1, Path('fixture'))


class TtsHttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_split_samples_and_partial_last_frame_are_preserved(self):
        pcm = b'\x01\x00' * 3001
        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield pcm[:1]
                yield pcm[1:2577]
                yield pcm[2577:]
        def handler(request):
            body = json.loads(request.content)
            self.assertEqual(body['media_type'], 'raw')
            self.assertTrue(body['streaming_mode'])
            self.assertEqual(body['text_lang'], 'ko')
            return httpx.Response(200, headers={'content-type': 'audio/raw'}, stream=Stream())
        provider = GptSovitsHttp(config())
        provider.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            events = [event async for event in provider.stream(Request('tts', {'text': '시험'}), Context('s', 1, 1))]
            self.assertEqual(events[-1].kind, 'completed')
            self.assertEqual(b''.join(event.data['pcm'] for event in events[:-1]), pcm)
            self.assertEqual([event.data['sequence'] for event in events[:-1]], [0, 1, 2])
            self.assertTrue(all(len(event.data['pcm']) <= 2560 for event in events[:-1]))
        finally:
            await provider.close()

    async def test_invalid_audio_and_http_errors_do_not_complete(self):
        for status, content_type, pcm, expected in [
                (200, 'audio/wav', b'RIFF', InvalidOutput),
                (200, 'audio/raw', b'', InvalidOutput),
                (200, 'audio/raw', b'\x00', InvalidOutput),
                (503, 'application/json', b'private details', ProviderUnavailable)]:
            with self.subTest(status=status, content_type=content_type, size=len(pcm)):
                provider = GptSovitsHttp(config())
                provider.client = httpx.AsyncClient(transport=httpx.MockTransport(
                    lambda request: httpx.Response(status, headers={'content-type': content_type}, content=pcm)))
                try:
                    with self.assertRaises(expected):
                        async for event in provider.stream(Request('tts', {'text': '시험'}), Context('s', 1, 1)):
                            self.assertNotEqual(event.kind, 'completed')
                finally:
                    await provider.close()

    async def test_cancelled_response_cleanup_cannot_emit_completed(self):
        context = Context('s', 1, 1)
        closed = []
        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'\x00\x00'
            async def aclose(self):
                closed.append(True)
                context.cancelled.set()
        provider = GptSovitsHttp(config())
        provider.client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, headers={'content-type': 'audio/raw'}, stream=Stream())))
        try:
            with self.assertRaises(asyncio.CancelledError):
                async for event in provider.stream(Request('tts', {'text': '시험'}), context):
                    self.assertNotEqual(event.kind, 'completed')
            self.assertTrue(closed)
        finally:
            await provider.close()

    async def test_pending_read_deadline_and_task_cancellation_close_response(self):
        for cancel_task in (False, True):
            with self.subTest(cancel_task=cancel_task):
                started = asyncio.Event()
                closed = asyncio.Event()
                class Stream(httpx.AsyncByteStream):
                    async def __aiter__(self):
                        started.set()
                        await asyncio.Event().wait()
                        yield b''
                    async def aclose(self):
                        closed.set()
                provider = GptSovitsHttp(config())
                provider.client = httpx.AsyncClient(transport=httpx.MockTransport(
                    lambda request: httpx.Response(200, headers={'content-type': 'audio/raw'}, stream=Stream())))
                async def consume():
                    async for _ in provider.stream(Request('tts', {'text': '시험'}), Context('s', 1, 1, timeout=0.05)):
                        self.fail('pending request emitted output')
                task = asyncio.create_task(consume())
                try:
                    await started.wait()
                    if cancel_task:
                        task.cancel()
                    with self.assertRaises(asyncio.CancelledError if cancel_task else TimeoutError):
                        await task
                    self.assertTrue(closed.is_set())
                finally:
                    await provider.close()

    async def test_context_signal_cancels_a_stalled_read_before_deadline(self):
        started = asyncio.Event()
        closed = asyncio.Event()
        context = Context('s', 1, 1, timeout=30)
        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                started.set()
                await asyncio.Event().wait()
                yield b''
            async def aclose(self):
                closed.set()
        provider = GptSovitsHttp(config())
        provider.client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, headers={'content-type': 'audio/raw'}, stream=Stream())))
        async def consume():
            async for _ in provider.stream(Request('tts', {'text': '시험'}), context):
                self.fail('cancelled read emitted output')
        task = asyncio.create_task(consume())
        try:
            await asyncio.wait_for(started.wait(), 1)
            context.cancelled.set()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, 0.5)
            self.assertTrue(closed.is_set())
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await provider.close()

    async def test_chunk_ready_together_with_cancellation_is_discarded(self):
        context = Context('s', 1, 1)
        async def chunks():
            context.cancelled.set()
            yield b'\x00\x00'
        with self.assertRaises(asyncio.CancelledError):
            await GptSovitsHttp._read_next(chunks().__aiter__(), context)

    async def test_context_cancel_while_waiting_for_response_headers(self):
        context = Context('s', 1, 1)
        started = asyncio.Event()
        stopped = asyncio.Event()
        async def handler(request):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
        provider = GptSovitsHttp(config())
        provider.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        async def consume():
            async for _ in provider.stream(Request('tts', {'text': '시험'}), context):
                self.fail('cancelled header request emitted output')
        task = asyncio.create_task(consume())
        try:
            await asyncio.wait_for(started.wait(), 1)
            context.cancelled.set()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, .5)
            self.assertTrue(stopped.is_set())
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await provider.close()

    async def test_response_arriving_with_cancel_is_closed_without_delivery(self):
        context = Context('s', 1, 1)
        closed = asyncio.Event()
        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'\x00\x00'
            async def aclose(self):
                closed.set()
        async def handler(request):
            context.cancelled.set()
            return httpx.Response(200, headers={'content-type': 'audio/raw'}, stream=Stream())
        provider = GptSovitsHttp(config())
        provider.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            with self.assertRaises(asyncio.CancelledError):
                async for _ in provider.stream(Request('tts', {'text': '시험'}), context):
                    self.fail('cancelled response emitted output')
            self.assertTrue(closed.is_set())
        finally:
            await provider.close()

    def test_bad_configuration_rejected(self):
        for options in ({'url': 'http://user:secret@localhost/tts'}, {'url': 3},
                        {'sample_rate': True}, {'sample_rate': 44100},
                        {'ref_audio_path': 'https://example.com/voice.wav'},
                        {'prompt_lang': 'en'}, {'token_env': ''}, {'unknown': True}):
            with self.subTest(options=options):
                with self.assertRaises(ConfigurationError):
                    GptSovitsHttp(config(**options))

    def test_manifest_sample_rate_must_match_configured_raw_audio(self):
        for rates in ([], [24000]):
            candidate = config()
            candidate.manifest['sample_rates'] = rates
            with self.subTest(rates=rates):
                with self.assertRaises(ConfigurationError):
                    GptSovitsHttp(candidate)
