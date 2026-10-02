"""Explicit buffered partial recognition with an offline SenseVoice model."""
import asyncio
import math
from .sherpa import native_call
from ..contracts import Capabilities, ConfigurationError, Event, InvalidOutput, ModelLoadError


class SenseVoiceProvider:
    def __init__(self, config):
        self.config = config
        if config.role != 'stt' or 'buffered_partial' not in config.capabilities.features:
            raise ConfigurationError('SenseVoice requires an explicit buffered_partial STT profile')
        if config.options.keys() - {'num_threads', 'partial_seconds', 'max_seconds'}:
            raise ConfigurationError('unknown SenseVoice option')
        threads = config.options.get('num_threads', 2)
        if type(threads) is not int or not 1 <= threads <= 32:
            raise ConfigurationError('SenseVoice num_threads must be between 1 and 32')
        self.interval = config.options.get('partial_seconds', 1.0)
        self.maximum = config.options.get('max_seconds', 22.0)
        for value in (self.interval, self.maximum):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ConfigurationError('invalid SenseVoice buffer interval')
        if not .2 <= self.interval <= 3 or not self.interval <= self.maximum <= 30:
            raise ConfigurationError('invalid SenseVoice buffer limits')
        declared = config.capabilities
        self.capabilities = Capabilities('stt', declared.features &
            {'stream', 'partial', 'final', 'cancel', 'buffered_partial'}, declared.languages,
            declared.sample_rates & {16000})
        self.files = {a['name']: str((config.manifest_path.parent / a['path']).resolve())
                      for a in config.manifest['artifacts']}
        if not {'model', 'tokens'} <= self.files.keys():
            raise ConfigurationError('SenseVoice model and tokens are required')
        self.engine = None
        self.sessions = {}
        self.lock = asyncio.Lock()

    async def load(self):
        try:
            await native_call(self._load)
        except Exception as error:
            raise ModelLoadError('SenseVoice failed to load') from error

    def _load(self):
        import sherpa_onnx
        self.engine = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=self.files['model'], tokens=self.files['tokens'], language='ko', use_itn=True,
            num_threads=self.config.options.get('num_threads', 2), provider='cpu')

    def _process(self, request, context):
        context.check()
        import numpy as np
        pcm = request.data.get('pcm', b'')
        if not isinstance(pcm, bytes) or len(pcm) % 2 or request.data.get('sample_rate', 16000) != 16000:
            raise InvalidOutput('expected mono PCM16 at 16kHz')
        final = bool(request.data.get('final'))
        state = self.sessions.get(context.session_id, [bytearray(), 0])
        if len(state[0]) + len(pcm) > int(self.maximum * 32000):
            raise InvalidOutput('SenseVoice buffer limit exceeded')
        state[0].extend(pcm)
        self.sessions[context.session_id] = state
        if not final and len(state[0]) - state[1] < self.interval * 32000:
            return []
        context.check()
        text = ''
        if state[0]:
            stream = self.engine.create_stream()
            samples = np.frombuffer(state[0], dtype='<i2').astype(np.float32) / 32768
            stream.accept_waveform(16000, samples)
            self.engine.decode_stream(stream)
            context.check()
            text = stream.result.text
        state[1] = len(state[0])
        if final:
            self.sessions.pop(context.session_id, None)
        return [Event('transcript_final' if final else 'transcript_partial', {'text': text})]

    async def stream(self, request, context):
        if self.engine is None or request.role != 'stt':
            raise ConfigurationError('SenseVoice is not ready or role mismatch')
        context.check()
        async with self.lock:
            events = await native_call(self._process, request, context)
        for event in events:
            context.check()
            yield event
        context.check()
        yield Event('completed')

    async def reset(self, session_id):
        async with self.lock:
            self.sessions.pop(session_id, None)

    async def close(self):
        async with self.lock:
            self.sessions.clear()
            self.engine = None
