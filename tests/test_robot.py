import asyncio
import unittest
import io
import wave
from real_pa.contracts import Context,Event,Request
from real_pa.robot import RobotRuntime
from real_pa.session import DialogueSession
from test_runtime import FixtureProvider


class AudioFixture(FixtureProvider):
    def __init__(self,role):
        super().__init__(role)
        self.frames=0
    async def stream(self,request,context):
        self.frames+=1
        if request.role=='stt':
            yield Event('transcript_partial',{'text':''})
        yield Event('completed')


class RobotTests(unittest.IsolatedAsyncioTestCase):
    async def test_punctuated_spoken_close_ends_input_without_a_reply(self):
        class Vad(AudioFixture):
            async def stream(self, request, context):
                self.frames += 1
                yield Event('speech_started' if self.frames == 1 else 'speech_ended')
        class Stt(AudioFixture):
            async def stream(self, request, context):
                if request.data['final']:
                    yield Event('transcript_final', {'text': '대화 끝.'})
        session = DialogueSession('s', FixtureProvider(), FixtureProvider('tts'))
        runtime = RobotRuntime(session, {'stt': Stt('stt'), 'vad': Vad('vad'), 'kws': AudioFixture('kws')})
        await runtime.start(ui_started=True)
        try:
            for _ in range(2): runtime.accept_audio(b'\1\0' * 1600)
            await asyncio.wait_for(runtime.running, 2)
            self.assertEqual(session.turn, 0)
            self.assertEqual(session.history, [])
        finally:
            await runtime.close()

    async def test_spoken_stop_emits_final_and_keeps_input_for_the_next_turn(self):
        class Vad(AudioFixture):
            async def stream(self, request, context):
                self.frames += 1
                yield Event('speech_started' if self.frames % 2 else 'speech_ended')
        class Stt(AudioFixture):
            async def stream(self, request, context):
                if request.data['final']:
                    yield Event('transcript_final', {'text': '그만.' if request.data['sequence'] == 2 else '다음 질문'})
        session = DialogueSession('s', FixtureProvider(), FixtureProvider('tts'))
        runtime = RobotRuntime(session, {'stt': Stt('stt'), 'vad': Vad('vad'), 'kws': AudioFixture('kws')})
        await runtime.start(ui_started=True)
        try:
            for _ in range(2): runtime.accept_audio(b'\1\0' * 1600)
            async with asyncio.timeout(2):
                while True:
                    generation, event = await session.next_event()
                    if event.kind == 'transcript_final': break
            self.assertEqual(generation, session.generation)
            self.assertEqual(event.data, {'text': '그만.', 'control': 'interrupt', 'input_id': 0})
            self.assertEqual(session.turn, 0)
            self.assertFalse(runtime.running.done())
            self.assertEqual(len(runtime.audio_window), 0)
            await runtime.reset_input(input_id=77)
            for _ in range(2): runtime.accept_audio(b'\1\0' * 1600)
            async with asyncio.timeout(2):
                while True:
                    _, event = await session.next_event()
                    if event.kind == 'transcript_final': break
            self.assertEqual(event.data['input_id'], 77)
            self.assertEqual(session.history[0]['content'], '다음 질문')
        finally:
            await runtime.close()

    async def test_oversized_transcript_recovers_after_silence_without_disconnect(self):
        class Vad(AudioFixture):
            async def stream(self, request, context):
                self.frames += 1
                if self.frames in (1, 5): yield Event('speech_started')
                if self.frames in (4, 6): yield Event('speech_ended')
        class Stt(AudioFixture):
            async def stream(self, request, context):
                if request.data['final']:
                    yield Event('transcript_final', {'text': '가' * 4001 if request.data['sequence'] == 2 else '다시 질문'})
        session = DialogueSession('s', FixtureProvider(), FixtureProvider('tts'))
        vad = Vad('vad')
        runtime = RobotRuntime(session, {'stt': Stt('stt'), 'vad': vad, 'kws': AudioFixture('kws')},
                               max_utterance_seconds=.2)
        await runtime.start(ui_started=True)
        try:
            for _ in range(4): runtime.accept_audio(b'\1\0' * 1600)
            async with asyncio.timeout(2):
                while vad.frames < 4: await asyncio.sleep(.001)
            events = []
            while not session.output.empty(): events.append((await session.next_event())[1])
            self.assertEqual([e.data['code'] for e in events if e.kind == 'input_rejected'], ['transcript_too_long'])
            self.assertEqual(session.turn, 0)
            self.assertFalse(runtime.discarding_speech)
            self.assertFalse(runtime.running.done())
            for _ in range(2): runtime.accept_audio(b'\1\0' * 1600)
            async with asyncio.timeout(2):
                while session.turn < 1: await asyncio.sleep(.001)
            self.assertEqual(session.history[0]['content'], '다시 질문')
        finally:
            await runtime.close()

    async def test_long_speech_segments_stt_but_submits_only_at_vad_endpoint(self):
        class Vad(AudioFixture):
            async def stream(self, request, context):
                self.frames += 1
                if self.frames == 1: yield Event('speech_started')
                if self.frames == 6: yield Event('speech_ended')
        class Stt(AudioFixture):
            def __init__(self):
                super().__init__('stt')
                self.final_sequences = []
            async def stream(self, request, context):
                if request.data['final']:
                    self.final_sequences.append(request.data['sequence'])
                    yield Event('transcript_final', {'text': ['첫째', '둘째', '셋째'][len(self.final_sequences)-1]})
        session = DialogueSession('s', FixtureProvider(), FixtureProvider('tts'))
        stt, vad = Stt(), Vad('vad')
        runtime = RobotRuntime(session, {'stt': stt, 'vad': vad, 'kws': AudioFixture('kws')},
                               max_utterance_seconds=.2)
        await runtime.start(ui_started=True)
        try:
            for _ in range(5): runtime.accept_audio(b'\1\0' * 1600)
            async with asyncio.timeout(2):
                while vad.frames < 5: await asyncio.sleep(.001)
            self.assertEqual(session.turn, 0)
            self.assertFalse(runtime.running.done())
            self.assertEqual(stt.final_sequences, [2, 4])
            runtime.accept_audio(b'\0\0' * 1600)
            async with asyncio.timeout(2):
                while session.turn < 1: await asyncio.sleep(.001)
            self.assertEqual(stt.final_sequences, [2, 4, 6])
            self.assertEqual(session.history[0]['content'], '첫째 둘째 셋째')
            self.assertEqual(runtime.transcript_segments, [])
            self.assertLessEqual(len(runtime.audio_window), runtime.max_frames + runtime.speech_pre_roll_frames)
        finally:
            await runtime.close()

    async def test_vad_gates_silence_and_preserves_speech_pre_roll_and_endpoint(self):
        class Vad(AudioFixture):
            async def stream(self, request, context):
                self.frames += 1
                if self.frames == 5: yield Event('speech_started')
                if self.frames == 6: yield Event('speech_ended')
        class Stt(AudioFixture):
            received = None
            async def stream(self, request, context):
                if self.received is None: self.received = []
                self.received.append((request.data['sequence'], request.data['final'], request.data['pcm']))
                yield Event('completed')
        session = DialogueSession('s', FixtureProvider(), FixtureProvider('tts'))
        stt, vad = Stt('stt'), Vad('vad')
        runtime = RobotRuntime(session, {'stt': stt, 'vad': vad, 'kws': AudioFixture('kws')})
        await runtime.start(ui_started=True)
        try:
            frames = [bytes([value, 0]) * 1600 for value in range(1, 8)]
            for frame in frames: runtime.accept_audio(frame)
            for _ in range(100):
                if vad.frames == 7: break
                await asyncio.sleep(.001)
            self.assertEqual(stt.received, [(i, i == 6, frames[i - 1]) for i in range(1, 7)])
        finally:
            await runtime.close()

    async def test_final_transcript_has_bounded_robot_local_wav(self):
        class Vad(AudioFixture):
            async def stream(self, request, context):
                self.frames += 1
                yield Event('speech_started' if self.frames == 1 else 'speech_ended')
        class Stt(AudioFixture):
            async def stream(self, request, context):
                if request.data['final']:
                    yield Event('transcript_final', {'text': '시험', 'control': 'interrupt'})
        class Model(FixtureProvider):
            async def stream(self, request, context):
                self.request = request
                yield Event('completed')
        model = Model()
        session = DialogueSession('s', model, FixtureProvider('tts'))
        runtime = RobotRuntime(session, {'stt': Stt('stt'), 'vad': Vad('vad'), 'kws': AudioFixture('kws')})
        await runtime.start(ui_started=True)
        try:
            frame = b'\1\0' * 1600
            runtime.accept_audio(frame)
            runtime.accept_audio(frame)
            for _ in range(100):
                if hasattr(model, 'request'): break
                await asyncio.sleep(.001)
            self.assertNotIn('audio_blob', model.request.data)
            with wave.open(io.BytesIO(model.request.local['audio_blob'])) as wav:
                self.assertEqual((wav.getframerate(), wav.getnchannels(), wav.getsampwidth()), (16000, 1, 2))
                self.assertEqual(wav.readframes(wav.getnframes()), frame * 2)
            self.assertEqual(model.request.local['source'], 'voice')
            output = []
            while not session.output.empty():
                output.append(session.output.get_nowait())
            finals = [(generation, event.data['text']) for generation, event in output
                      if event.kind == 'transcript_final']
            self.assertEqual(finals, [(session.generation, '시험')])
            self.assertTrue(all('control' not in event.data for _, event in output
                                if event.kind == 'transcript_final'))
        finally:
            await runtime.close()
    async def test_wake_replays_each_capture_frame_once_in_order(self):
        class WakeFixture(AudioFixture):
            async def stream(self, request, context):
                self.frames += 1
                if self.frames == 3:
                    yield Event('wake_detected')

        class RecordingStt(AudioFixture):
            def __init__(self):
                super().__init__('stt')
                self.received = []

            async def stream(self, request, context):
                self.received.append((request.data['sequence'], request.data['pcm']))
                yield Event('completed')

        session = DialogueSession('s', FixtureProvider(), FixtureProvider('tts'))
        stt = RecordingStt()
        runtime = RobotRuntime(session, {'stt': stt, 'kws': WakeFixture('kws'),
                                        'vad': AudioFixture('vad')})
        frames = [bytes([value, 0]) * 1600 for value in (1, 2, 3)]
        await runtime.start()
        try:
            for frame in frames:
                runtime.accept_audio(frame)
            for _ in range(100):
                if len(stt.received) >= 3:
                    break
                await asyncio.sleep(.001)
            self.assertEqual(stt.received, list(enumerate(frames, start=1)))
        finally:
            await runtime.close()

    async def test_capture_processed_during_blocked_generation(self):
        llm=FixtureProvider(gate=asyncio.Event())
        session=DialogueSession('s',llm,FixtureProvider('tts'))
        providers={role:AudioFixture(role) for role in ['stt','kws','vad']}
        runtime=RobotRuntime(session,providers)
        await runtime.start(ui_started=True)
        await session.submit('응답 생성 중')
        for _ in range(8):runtime.accept_audio(b'\0\0'*1600)
        for _ in range(100):
            if providers['vad'].frames==8:break
            await asyncio.sleep(.001)
        self.assertEqual(providers['vad'].frames,8)
        self.assertEqual(providers['stt'].frames,0)
        self.assertFalse(session.task.done())
        await runtime.close()
        self.assertTrue(llm.was_cancelled)

    async def test_invalid_frames_rejected_and_close_idempotent(self):
        session=DialogueSession('s',FixtureProvider(),FixtureProvider('tts'))
        runtime=RobotRuntime(session,{r:AudioFixture(r) for r in ['stt','kws','vad']})
        with self.assertRaises(ValueError):runtime.accept_audio(b'\0')
        await runtime.close()
        await runtime.close()

    async def test_failed_capture_task_does_not_skip_session_cleanup(self):
        class FailingVad(AudioFixture):
            async def stream(self, request, context):
                raise TimeoutError('fixture deadline')
                yield
        session = DialogueSession('s', FixtureProvider(), FixtureProvider('tts'))
        runtime = RobotRuntime(session, {'vad': FailingVad('vad'), 'stt': AudioFixture('stt'),
                                         'kws': AudioFixture('kws')})
        await runtime.start(ui_started=True)
        runtime.accept_audio(b'\0\0' * 1600)
        with self.assertRaises(TimeoutError):
            await runtime.running
        await runtime.close()
        self.assertTrue(session.closed)

    async def test_silence_does_not_exhaust_utterance_limit(self):
        session=DialogueSession('s',FixtureProvider(),FixtureProvider('tts'))
        runtime=RobotRuntime(session,{r:AudioFixture(r) for r in ['stt','kws','vad']},max_utterance_seconds=.1)
        await runtime.start(ui_started=True)
        runtime.accept_audio(b'\0\0'*1600)
        await asyncio.sleep(.01)
        self.assertFalse(runtime.running.done())
        await runtime.close()
