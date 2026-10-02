"""Buffered STT contract fixtures; no actual model or accuracy claims."""
import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

from real_pa.adapters.sensevoice import SenseVoiceProvider
from real_pa.config import ProviderConfig
from real_pa.contracts import ConfigurationError, Context, InvalidOutput, Request


def provider(features=None):
    manifest = {'features': features if features is not None else
                ['stream', 'partial', 'final', 'cancel', 'buffered_partial'],
                'languages': ['ko'], 'sample_rates': [16000],
                'artifacts': [{'name': 'model', 'path': 'model.onnx'}, {'name': 'tokens', 'path': 'tokens.txt'}]}
    result = SenseVoiceProvider(ProviderConfig('stt', 'sensevoice_buffered', manifest,
        {'partial_seconds': .2, 'max_seconds': .3}, 10, Path('fixture.json')))
    class Engine:
        decodes = 0
        def create_stream(self):
            return SimpleNamespace(accept_waveform=lambda rate, samples: None,
                                   result=SimpleNamespace(text='인식 결과'))
        def decode_stream(self, stream): self.decodes += 1
    result.engine = Engine()
    return result


@unittest.skipUnless(importlib.util.find_spec('numpy'), 'audio extra required')
class SenseVoiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_while_waiting_for_model_lock_does_not_buffer_audio(self):
        model = provider()
        context = Context('s', 1, 1)
        await model.lock.acquire()
        async def consume():
            return [e async for e in model.stream(Request('stt', {'pcm': b'\1\0' * 1600}), context)]
        task = asyncio.create_task(consume())
        await asyncio.sleep(0)
        context.cancelled.set()
        model.lock.release()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(model.sessions, {})
        self.assertEqual(model.engine.decodes, 0)
    async def test_explicit_buffered_profile_required(self):
        with self.assertRaises(ConfigurationError):
            provider(['stream', 'partial', 'final', 'cancel'])

    async def test_partial_interval_and_final_are_distinct_and_reset_drops_audio(self):
        model = provider()
        context = Context('s', 1, 1)
        frame = b'\1\0' * 1600
        async def events(final=False):
            return [e async for e in model.stream(Request('stt', {'pcm': frame, 'final': final}), context)]
        self.assertEqual([e.kind for e in await events()], ['completed'])
        self.assertEqual([e.kind for e in await events()], ['transcript_partial', 'completed'])
        self.assertEqual([e.kind for e in await events(True)], ['transcript_final', 'completed'])
        self.assertEqual(model.engine.decodes, 2)
        self.assertNotIn('s', model.sessions)
        await events()
        await model.reset('s')
        self.assertNotIn('s', model.sessions)
        await model.close()
        self.assertIsNone(model.engine)

    async def test_limits_and_cancellation_do_not_emit_transcripts(self):
        model = provider()
        context = Context('s', 1, 1)
        with self.assertRaises(InvalidOutput):
            async for _ in model.stream(Request('stt', {'pcm': b'\0\0' * 6400}), context): pass
        self.assertEqual(model.sessions, {})
        context.cancelled.set()
        with self.assertRaises(asyncio.CancelledError):
            async for _ in model.stream(Request('stt', {'pcm': b'\0\0' * 1600}), context): pass
        self.assertEqual(model.engine.decodes, 0)
