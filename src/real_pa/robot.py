"""Duplex robot orchestration. Transport authentication is owned by Lemmy."""
import asyncio
import contextlib
import io
import wave
from collections import deque
from .contracts import Context, Event, Request, ResourceExhausted
from .speech_controls import utterance_control


class RobotRuntime:
    def __init__(self, session, providers, *, input_capacity=12, max_utterance_seconds=20,
                 speech_pre_roll_frames=10):
        self.session = session
        self.providers = providers
        self.input = asyncio.Queue(maxsize=input_capacity)
        self.awake = False
        self.sequence = 0
        self.stt_sequence = 0
        self.speaking = False
        self.utterance_frames = 0
        self.max_frames = int(max_utterance_seconds * 10)
        if self.max_frames < 1:
            raise ValueError('utterance window must contain at least one frame')
        self.transcript_segments = []
        self.discarding_speech = False
        self.pre_roll = []
        if not 1 <= speech_pre_roll_frames <= 20:
            raise ValueError('speech pre-roll must contain 1 to 20 frames')
        self.speech_pre_roll_frames = speech_pre_roll_frames
        self.audio_window = deque(maxlen=self.max_frames + speech_pre_roll_frames)
        self.running = None
        self.closed = False
        self.input_epoch = 0
        self.input_id = 0

    async def reset_input(self, *, input_id=None):
        if self.closed:
            raise RuntimeError('audio session is closed')
        self.input_epoch += 1
        if input_id is not None:
            self.input_id = input_id
        done = asyncio.get_running_loop().create_future()
        try:
            self.input.put_nowait(('reset', self.input_epoch, done))
        except asyncio.QueueFull as exc:
            raise ResourceExhausted('capture queue overflow') from exc
        await asyncio.wait_for(done, 10)

    def accept_audio(self, pcm):
        # 100ms mono PCM16@16k input frames; bounded even while GPU is busy.
        if self.closed:
            return
        if not isinstance(pcm,bytes) or len(pcm) != 3200:
            raise ValueError('expected 100ms PCM16@16k frame')
        try:
            self.input.put_nowait(('audio', self.input_epoch, pcm))
        except asyncio.QueueFull as exc:
            raise ResourceExhausted('capture queue overflow; utterance must be retried') from exc

    async def start(self, *, ui_started=False):
        if self.running is not None:
            return
        self.awake = ui_started
        self.running = asyncio.create_task(self._process())

    async def _events(self, role, data):
        context = Context(self.session.session_id,self.session.turn,
                          self.session.generation,timeout=10)
        async for e in self.providers[role].stream(Request(role,data),context):
            yield e

    async def _process(self):
        while True:
            kind, epoch, item = await self.input.get()
            if kind == 'reset':
                await self.providers['stt'].reset(self.session.session_id)
                await self.providers['vad'].reset(self.session.session_id)
                self.audio_window.clear()
                self.pre_roll.clear()
                self.speaking = False
                self.utterance_frames = 0
                self.transcript_segments.clear()
                self.discarding_speech = False
                if not item.done():
                    item.set_result(None)
                continue
            if epoch != self.input_epoch:
                continue
            pcm = item
            self.sequence += 1
            data = {'pcm':pcm,'sample_rate':16000,'sequence':self.sequence,'final':False}
            self.audio_window.append(pcm)
            woke = False
            if not self.awake:
                self.pre_roll.append((self.sequence, pcm))
                self.pre_roll = self.pre_roll[-3:]
                async for event in self._events('kws',data):
                    if event.kind == 'wake_detected':
                        self.awake = True
                        woke = True
                if not self.awake:
                    continue
                # The current frame goes through VAD/STT below exactly once.
                # Replay only earlier capture frames with their original IDs.
                for sequence, frame in self.pre_roll[:-1]:
                    self.stt_sequence = sequence
                    async for _ in self._events('stt',dict(data,pcm=frame,sequence=sequence)):
                        pass
                self.pre_roll.clear()
            final = False
            started = False
            async for event in self._events('vad',data):
                if epoch != self.input_epoch:
                    continue
                if event.kind == 'speech_started':
                    started = True
                    self.speaking = True
                    self.audio_window = deque(list(self.audio_window)[-self.speech_pre_roll_frames:],
                                              maxlen=self.max_frames + self.speech_pre_roll_frames)
                    await self.session.interrupt()
                elif event.kind == 'speech_ended':
                    self.speaking = False
                    final = True
            if epoch != self.input_epoch:
                continue
            if self.discarding_speech:
                self.audio_window.clear()
                if final:
                    self.discarding_speech = False
                continue
            if started:
                # VAD may detect speech after its first samples. Replay bounded
                # pre-roll, excluding samples already sent during wake-up.
                frames = list(self.audio_window)
                first = self.sequence - len(frames) + 1
                for sequence, frame in enumerate(frames[:-1], start=first):
                    if epoch != self.input_epoch:
                        break
                    if sequence <= self.stt_sequence:
                        continue
                    self.stt_sequence = sequence
                    async for _ in self._events('stt', dict(data, pcm=frame, sequence=sequence)):
                        pass
            if epoch != self.input_epoch:
                continue
            if not self.speaking and not final and not woke:
                continue
            if self.speaking:
                self.utterance_frames += 1
            # Bound each recognizer stream without ending a long spoken turn.
            # VAD stays active; only its natural endpoint submits the request.
            segment_end = not final and self.utterance_frames >= self.max_frames
            self.stt_sequence = self.sequence
            async for event in self._events('stt',dict(data,final=final or segment_end)):
                if epoch != self.input_epoch:
                    continue
                if event.kind == 'transcript_partial':
                    event = Event(event.kind, dict(event.data, input_id=self.input_id))
                    current = Context(self.session.session_id,self.session.turn,self.session.generation,timeout=10)
                    if self.transcript_segments:
                        event = Event(event.kind, dict(event.data,
                            text=' '.join(self.transcript_segments + [event.data.get('text', '')]).strip()))
                    await self.session._emit(current,event)
                if event.kind == 'transcript_final':
                    self.utterance_frames = 0
                    text = event.data.get('text','').strip()
                    if text:
                        self.transcript_segments.append(text)
                    if sum(map(len, self.transcript_segments)) + max(0, len(self.transcript_segments) - 1) > 4000:
                        self.transcript_segments.clear()
                        self.audio_window.clear()
                        self.discarding_speech = not final
                        await self.providers['stt'].reset(self.session.session_id)
                        current = Context(self.session.session_id, self.session.turn,
                                          self.session.generation, timeout=10)
                        await self.session._emit(current, Event('input_rejected', {'code': 'transcript_too_long'}))
                        break
                    if segment_end:
                        await self.providers['stt'].reset(self.session.session_id)
                        current = Context(self.session.session_id, self.session.turn,
                                          self.session.generation, timeout=10)
                        await self.session._emit(current, Event('transcript_partial',
                            {'text': ' '.join(self.transcript_segments), 'input_id': self.input_id}))
                        continue
                    text = ' '.join(self.transcript_segments)
                    self.transcript_segments.clear()
                    # Control metadata belongs to this controller, not STT.
                    final_data = {key: value for key, value in event.data.items() if key != 'control'}
                    event = Event(event.kind, dict(final_data, text=text, input_id=self.input_id))
                    control = utterance_control(text)
                    if control == 'interrupt':
                        self.audio_window.clear()
                        await self.session.interrupt()
                        current = Context(self.session.session_id, self.session.turn,
                                          self.session.generation, timeout=10)
                        await self.session._emit(current, Event('transcript_final',
                            dict(event.data, control='interrupt')))
                        continue
                    if control == 'close':
                        await self.session.interrupt()
                        return
                    audio = io.BytesIO()
                    with wave.open(audio, 'wb') as wav:
                        wav.setnchannels(1)
                        wav.setsampwidth(2)
                        wav.setframerate(16000)
                        wav.writeframes(b''.join(self.audio_window))
                    self.audio_window.clear()
                    await self.session.submit(text, metadata={'audio_blob': audio.getvalue(), 'source': 'voice'})
                    # submit advances generation and flushes old output. Deliver
                    # the final transcript in the new generation so it survives.
                    current = Context(self.session.session_id, self.session.turn,
                                      self.session.generation, timeout=10)
                    await self.session._emit(current, event)

    async def close(self):
        if self.closed:
            return
        self.closed = True
        if self.running:
            self.running.cancel()
            # A failed input task has already been observed by the gateway.
            # Its exception must not prevent session/provider cleanup.
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self.running
        while not self.input.empty():
            self.input.get_nowait()
        self.audio_window.clear()
        self.transcript_segments.clear()
        await self.session.close()
        for role in ['stt','kws','vad']:
            await self.providers[role].reset(self.session.session_id)
