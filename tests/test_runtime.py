import asyncio
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from real_pa.config import read_config, ProviderConfig
from real_pa.contracts import (Capabilities, Context, Event, Request,
                               ConfigurationError, UnsupportedCapability)
from real_pa.registry import Registry
from real_pa.session import DialogueSession


class FixtureProvider:
    """Control-contract fixture, never a model quality substitute."""
    def __init__(self, role='llm', gate=None, fail_load=False):
        self.capabilities = Capabilities(role,frozenset({'stream','cancel'}),frozenset({'ko'}))
        self.gate = gate
        self.closed = False
        self.was_cancelled = False
        self.fail_load = fail_load

    async def load(self):
        if self.fail_load:
            raise RuntimeError('load failed')

    async def stream(self, request, context):
        try:
            if self.gate is not None:
                await self.gate.wait()
            context.check()
            if request.role == 'llm':
                yield Event('text_delta',{'text':'안녕하세요.'})
            else:
                yield Event('audio_chunk',{'pcm':b'\0\0'*10,'sample_rate':16000})
            yield Event('completed')
        except asyncio.CancelledError:
            self.was_cancelled = True
            raise

    async def reset(self, session_id):
        pass

    async def close(self):
        self.closed = True


def config(role='llm'):
    return ProviderConfig(role,'fixture',{'model_id':'fixture','role':role,
        'features':['stream','cancel'],'languages':['ko']},{},1,Path('fixture'))


class ConfigTests(unittest.TestCase):
    def test_hash_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'model').write_bytes(b'actual')
            manifest = {'role':'llm','model_id':'fixture','revision':'1','runtime':'fixture',
                        'license':'test-only','features':['stream'],'languages':['ko'],
                        'artifacts':[{'path':'model','sha256':'0'*64}]}
            (root/'model.json').write_text(json.dumps(manifest))
            (root/'config.toml').write_text('[providers.llm]\nadapter="fixture"\nmanifest="model.json"\n')
            with self.assertRaises(ConfigurationError):
                read_config(root/'config.toml')
            manifest['artifacts'][0]['sha256'] = hashlib.sha256(b'actual').hexdigest()
            (root/'model.json').write_text(json.dumps(manifest))
            self.assertEqual(read_config(root/'config.toml')['llm'].adapter,'fixture')

    def test_missing_required_capability(self):
        with self.assertRaises(UnsupportedCapability):
            config().capabilities.require({'tools'})


class RegistryTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_later_adapter_is_rejected_before_any_model_load(self):
        loads = []
        class Model(FixtureProvider):
            async def load(self): loads.append('loaded')
        registry = Registry()
        registry.register('llm', 'fixture', lambda c: Model())
        with self.assertRaises(ConfigurationError):
            await registry.build({'llm': config(), 'tts': config('tts')})
        self.assertEqual(loads, [])

    async def test_missing_declared_feature_is_rejected_before_any_model_load(self):
        loads = []
        class Model(FixtureProvider):
            async def load(self): loads.append('loaded')
        registry = Registry()
        registry.register('llm', 'fixture', lambda c: Model())
        registry.register('tts', 'fixture', lambda c: Model('tts'))
        with self.assertRaises(UnsupportedCapability):
            await registry.build({'llm': config(), 'tts': config('tts')}, {'tts': {'chunks'}})
        self.assertEqual(loads, [])

    async def test_partial_load_cleanup(self):
        registry = Registry()
        first, second = FixtureProvider(), FixtureProvider('tts',fail_load=True)
        registry.register('llm','fixture',lambda c:first)
        registry.register('tts','fixture',lambda c:second)
        with self.assertRaises(RuntimeError):
            await registry.build({'llm':config(),'tts':config('tts')})
        self.assertTrue(first.closed and second.closed)

    async def test_unknown_registry_id_does_not_import(self):
        with self.assertRaises(ConfigurationError):
            await Registry().build({'llm':config()})

    async def test_loaded_capability_not_just_manifest(self):
        registry = Registry()
        provider = FixtureProvider()
        provider.capabilities = Capabilities('llm',frozenset(),frozenset({'ko'}))
        registry.register('llm','fixture',lambda c:provider)
        with self.assertRaises(UnsupportedCapability):
            await registry.build({'llm':config()},{'llm':{'stream'}})
        self.assertTrue(provider.closed)


class SessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_separate_newline_tokens_do_not_fail_speech_turn(self):
        class TextProvider(FixtureProvider):
            async def stream(self, request, context):
                for text in ('안녕하세요.', '\n', '  \n', '반갑습니다!', '\n'):
                    yield Event('text_delta', {'text': text})
                yield Event('completed')
        phrases = []
        class SpeechProvider(FixtureProvider):
            async def stream(self, request, context):
                from real_pa.contracts import InvalidOutput
                text = request.data['text']
                if not text.strip():
                    raise InvalidOutput('empty speech text')
                phrases.append(text)
                async for event in super().stream(request, context):
                    yield event
        session = DialogueSession('s', TextProvider(), SpeechProvider('tts'))
        try:
            await session.submit('인사해 줘')
            await asyncio.wait_for(session.task, 2)
            events = []
            while not session.output.empty():
                _, event = await session.next_event()
                events.append(event)
            self.assertEqual(phrases, ['안녕하세요.', '반갑습니다!'])
            self.assertEqual(''.join(e.data['text'] for e in events if e.kind == 'text_delta'),
                             '안녕하세요.\n  \n반갑습니다!\n')
            self.assertEqual(sum(e.kind == 'audio_chunk' for e in events), 2)
            self.assertEqual(events[-1].kind, 'turn_done')
            self.assertFalse(any(e.kind == 'error' for e in events))
        finally:
            await session.close()

    async def test_interrupt_cancels_worker_and_drops_old_events(self):
        gate = asyncio.Event()
        llm = FixtureProvider(gate=gate)
        s = DialogueSession('s',llm,FixtureProvider('tts'))
        await s.submit('처음 질문')
        await asyncio.sleep(0)
        old = s.generation
        await s.interrupt()
        self.assertTrue(llm.was_cancelled)
        self.assertFalse(s.acknowledge(old,1))
        generation,event = await s.next_event()
        self.assertEqual(generation,s.generation)
        self.assertEqual(event.kind,'interrupted')
        await s.close()

    async def test_only_acknowledged_audio_enters_history(self):
        s = DialogueSession('s',FixtureProvider(),FixtureProvider('tts'))
        await s.submit('안녕')
        await s.task
        chunks = []
        while not s.output.empty():
            g,e = await s.next_event()
            if e.kind == 'audio_chunk':
                chunks.append((g,e.data['chunk_id']))
        self.assertEqual(len(chunks),1)
        self.assertTrue(s.acknowledge(*chunks[0]))
        self.assertFalse(s.acknowledge(*chunks[0]))
        await s.interrupt()
        self.assertEqual(s.history[-1],{'role':'assistant','content':'안녕하세요.'})
        await s.close()

    async def test_unplayed_audio_not_in_history(self):
        s = DialogueSession('s',FixtureProvider(),FixtureProvider('tts'))
        await s.submit('안녕')
        await s.task
        await s.interrupt()
        self.assertFalse(any(x['role']=='assistant' for x in s.history))
        await s.close()

    async def test_output_overflow_fails_turn_without_hanging(self):
        s = DialogueSession('s',FixtureProvider(),FixtureProvider('tts'),max_output=1)
        await s.submit('안녕')
        await asyncio.wait_for(s.task,2)
        _,e = await s.next_event()
        self.assertEqual(e.kind,'error')
        await s.close()

    async def test_closed_session_and_idempotent_close(self):
        s = DialogueSession('s',FixtureProvider(),FixtureProvider('tts'))
        await s.close()
        await s.close()
        with self.assertRaises(RuntimeError):
            await s.submit('닫힌 세션')


if __name__ == '__main__':
    unittest.main()


class NativeCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_interrupt_returns_before_slow_native_cleanup(self):
        cleanup_started, release = asyncio.Event(), asyncio.Event()
        class SlowTts(FixtureProvider):
            async def stream(self, request, context):
                yield Event('audio_chunk', {'pcm': b'\0\0' * 320, 'sample_rate': 16000})
                yield Event('audio_chunk', {'pcm': b'\0\0' * 320, 'sample_rate': 16000})
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cleanup_started.set()
                    await release.wait()
                    raise
        session = DialogueSession('s', FixtureProvider(), SlowTts('tts'))
        try:
            await session.submit('시험')
            while True:
                _, event = await session.next_event()
                if event.kind == 'audio_chunk': break
            await asyncio.wait_for(session.interrupt(), .1)
            await asyncio.wait_for(cleanup_started.wait(), .1)
            self.assertTrue(session.retired_tasks)
            _, event = await session.next_event()
            self.assertEqual(event.kind, 'interrupted')
        finally:
            release.set()
            await session.close()
        self.assertFalse(session.retired_tasks)
