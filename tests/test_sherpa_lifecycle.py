import importlib.util
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from real_pa.adapters.sherpa import SherpaProvider
from real_pa.contracts import Context, Request


class CompletionCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_native_result_cannot_emit_completion_after_cancel(self):
        provider = object.__new__(SherpaProvider)
        provider.config = SimpleNamespace(role='vad')
        provider.engine = object()
        provider.lock = asyncio.Lock()
        context = Context('cancelled-vad', 1, 1)
        async def finished_native(*args):
            context.cancelled.set()
            return []
        with patch('real_pa.adapters.sherpa.native_call', side_effect=finished_native):
            with self.assertRaises(asyncio.CancelledError):
                async for _ in provider.stream(Request('vad', {}), context):
                    self.fail('cancelled inference emitted completion')


@unittest.skipUnless(importlib.util.find_spec('sherpa_onnx'), 'audio extra required')
class StreamLifecycleTests(unittest.TestCase):
    def test_stream_created_once_per_utterance_and_recreated_after_final(self):
        class Stream:
            def accept_waveform(self, rate, samples): pass
            def input_finished(self): pass
        class Engine:
            creations = 0
            def create_stream(self):
                self.creations += 1
                return Stream()
            def is_ready(self, stream): return False
            def get_result(self, stream): return ''
        provider = object.__new__(SherpaProvider)
        provider.config = SimpleNamespace(role='stt')
        provider.engine = Engine()
        provider.sessions = {}
        context = Context('fixture-session', 1, 1)
        for final in (False, False, True):
            provider._process(Request('stt', {'pcm': b'\0\0' * 1600, 'final': final}), context)
        self.assertEqual(provider.engine.creations, 1)
        self.assertNotIn('fixture-session', provider.sessions)
        provider._process(Request('stt', {'pcm': b'\0\0' * 1600}), context)
        self.assertEqual(provider.engine.creations, 2)
