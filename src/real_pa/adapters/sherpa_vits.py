"""Korean Mimic3 VITS TTS using the shared native lifecycle, no core changes."""
import math
from pathlib import Path

from .sherpa import SherpaProvider
from ..contracts import Capabilities, ConfigurationError, Event, InvalidOutput


class SherpaVits(SherpaProvider):
    def __init__(self, config):
        if config.role != 'tts' or config.options.keys() - {'num_threads', 'speed'}:
            raise ConfigurationError('invalid Korean VITS configuration')
        threads = config.options.get('num_threads', 2)
        speed = config.options.get('speed', 1.0)
        if type(threads) is not int or threads < 1 or type(speed) not in (int, float) or not math.isfinite(speed) or speed <= 0:
            raise ConfigurationError('invalid VITS threads or speed')
        super().__init__(config)
        declared = self.capabilities
        self.capabilities = Capabilities('tts', declared.features,
                                        declared.languages & {'ko'}, declared.sample_rates & {22050})
        if 22050 not in self.capabilities.sample_rates:
            raise ConfigurationError('Korean Mimic3 requires 22050 Hz manifest')
        if {'model', 'tokens', 'phondata'} - self.files.keys():
            raise ConfigurationError('VITS model, tokens and phondata required')

    def _load(self):
        import sherpa_onnx as s
        model = s.OfflineTtsModelConfig(
            vits=s.OfflineTtsVitsModelConfig(model=self.files['model'], tokens=self.files['tokens'],
                                           data_dir=str(Path(self.files['phondata']).parent)),
            num_threads=self.config.options.get('num_threads', 2), provider='cpu')
        self.engine = s.OfflineTts(s.OfflineTtsConfig(model=model))
        if self.engine.sample_rate != 22050:
            self.engine = None
            raise ConfigurationError('VITS model output rate mismatch')

    def _process(self, request, context):
        import numpy as np
        context.check()
        text = request.data.get('text')
        if not isinstance(text, str) or not text.strip():
            raise InvalidOutput('nonempty VITS synthesis text required')
        audio = self.engine.generate(text, sid=0, speed=self.config.options.get('speed', 1.0))
        context.check()
        samples = np.asarray(audio.samples)
        if not len(samples) or not np.isfinite(samples).all() or audio.sample_rate != 22050:
            raise InvalidOutput('invalid VITS output')
        pcm = (np.clip(samples, -1, 1) * 32767).astype('<i2').tobytes()
        size = 22050 * 40 // 1000 * 2
        return [Event('audio_chunk', {'pcm': pcm[index:index + size],
                                     'sample_rate': 22050, 'sequence': index // size})
                for index in range(0, len(pcm), size)]
