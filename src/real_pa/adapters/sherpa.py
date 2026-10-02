"""Local audio inference; native work is isolated from the asyncio loop."""
from __future__ import annotations
import asyncio
from pathlib import Path
from ..contracts import Event, Capabilities, ConfigurationError, InvalidOutput, Request, ModelLoadError


async def native_call(function, *args):
    # Native kernels cannot always be preempted. Keep resources alive until
    # they finish, while the robot has already stopped output for this generation.
    task = asyncio.create_task(asyncio.to_thread(function,*args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await task
        except Exception:
            pass
        raise


class SherpaProvider:
    def __init__(self, config):
        self.config = config
        supported = {
            'stt':{'stream','partial','final','cancel'},
            'tts':{'phrase','chunks','cancel'},
            'kws':{'stream','cancel'},
            'vad':{'stream','cancel'},
        }
        declared = config.capabilities
        self.capabilities = Capabilities(config.role,
            declared.features & supported.get(config.role,set()),
            declared.languages, declared.sample_rates)
        self.engine = None
        self.sessions = {}
        self.lock = asyncio.Lock()
        self.files = {}
        for artifact in config.manifest['artifacts']:
            self.files[artifact['name']] = str((config.manifest_path.parent/artifact['path']).resolve())

    async def load(self):
        try:
            await native_call(self._load)
        except ConfigurationError:
            raise
        except Exception as exc:
            raise ModelLoadError('native audio model failed to load') from exc

    def _load(self):
        import sherpa_onnx as s
        o = self.config.options
        role = self.config.role
        if set(o) - {'num_threads','sample_rate','threshold','min_silence','speaker_id','speed','num_steps'}:
            raise ConfigurationError('unknown sherpa option')
        threads = o.get('num_threads',2)
        if role == 'stt':
            self.engine = s.OnlineRecognizer.from_transducer(
                **{k:self.files[k] for k in ['tokens','encoder','decoder','joiner']},
                num_threads=threads, sample_rate=16000, provider='cpu')
        elif role == 'kws':
            self.engine = s.KeywordSpotter(
                **{k:self.files[k] for k in ['tokens','encoder','decoder','joiner']},
                keywords_file=self.files['keywords'], num_threads=threads,provider='cpu')
        elif role == 'vad':
            c = s.VadModelConfig()
            c.silero_vad.model = self.files['model']
            c.silero_vad.threshold = o.get('threshold',.5)
            c.silero_vad.min_silence_duration = o.get('min_silence',.5)
            c.sample_rate = 16000
            c.num_threads = threads
            self.engine = c
        elif role == 'tts':
            model = s.OfflineTtsModelConfig(
                supertonic=s.OfflineTtsSupertonicModelConfig(
                    **{k:self.files[k] for k in ['duration_predictor','text_encoder',
                          'vector_estimator','vocoder','tts_json','unicode_indexer','voice_style']}),
                num_threads=threads,provider='cpu',debug=False)
            self.engine = s.OfflineTts(s.OfflineTtsConfig(model=model))
        else:
            raise ConfigurationError('unsupported sherpa role')

    def _process(self, request, context):
        context.check()
        import numpy as np
        import sherpa_onnx as s
        role = self.config.role
        if role == 'tts':
            text = request.data.get('text','').strip()
            if not text:
                raise InvalidOutput('TTS text must not be empty')
            g = s.GenerationConfig()
            g.sid = self.config.options.get('speaker_id',0)
            g.speed = self.config.options.get('speed',1.0)
            g.num_steps = self.config.options.get('num_steps',4)
            g.extra['lang'] = 'ko'
            audio = self.engine.generate(text,g)
            pcm = (np.clip(np.asarray(audio.samples),-1,1)*32767).astype('<i2').tobytes()
            # Bounded frames, not a whole utterance wire payload.
            size = max(2,int(audio.sample_rate*.04)*2)
            return [Event('audio_chunk',{'pcm':pcm[i:i+size],'sample_rate':audio.sample_rate,
                     'sequence':i//size}) for i in range(0,len(pcm),size)]
        pcm = request.data.get('pcm',b'')
        if not isinstance(pcm,bytes) or len(pcm)%2 or request.data.get('sample_rate',16000)!=16000:
            raise InvalidOutput('expected mono PCM16 at 16kHz')
        samples = np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768
        key = context.session_id
        events = []
        if role in {'stt','kws'}:
            stream = self.sessions.get(key)
            if stream is None:
                stream = self.engine.create_stream()
                self.sessions[key] = stream
            stream.accept_waveform(16000,samples)
            if role == 'stt' and request.data.get('final'):
                stream.input_finished()
            while self.engine.is_ready(stream):
                self.engine.decode_stream(stream)
            text = self.engine.get_result(stream)
            if role == 'stt':
                final = bool(request.data.get('final'))
                events.append(Event('transcript_final' if final else 'transcript_partial',{'text':text}))
                if final:
                    self.sessions.pop(key,None)
            elif text:
                events.append(Event('wake_detected',{'keyword':text}))
                self.engine.reset_stream(stream)
        elif role == 'vad':
            state = self.sessions.get(key)
            if state is None:
                state = [s.VoiceActivityDetector(self.engine,buffer_size_in_seconds=30),
                         np.empty(0,dtype=np.float32),False]
                self.sessions[key] = state
            detector,pending,active = state
            pending = np.concatenate((pending,samples))
            while len(pending) >= 512:
                detector.accept_waveform(pending[:512])
                pending = pending[512:]
                detected = detector.is_speech_detected()
                if detected != active:
                    events.append(Event('speech_started' if detected else 'speech_ended'))
                    active = detected
                while not detector.empty():
                    detector.pop()
            state[1],state[2] = pending,active
        return events

    async def stream(self, request, context):
        if self.engine is None or request.role != self.config.role:
            raise ConfigurationError('sherpa provider not loaded or role mismatch')
        context.check()
        async with self.lock:
            result = await native_call(self._process,request,context)
        for event in result:
            context.check()
            yield event
        context.check()
        yield Event('completed')

    async def reset(self, session_id):
        async with self.lock:
            self.sessions.pop(session_id,None)

    async def close(self):
        async with self.lock:
            self.sessions.clear()
            self.engine = None
