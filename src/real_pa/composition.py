"""Only location that knows built-in adapter implementations."""
from .registry import Registry
from .adapters.chat_http import ChatHttp
from .adapters.rpc import RemoteProvider
from .adapters.sherpa import SherpaProvider
from .adapters.sensevoice import SenseVoiceProvider
from .adapters.gptsovits_http import GptSovitsHttp
from .adapters.sherpa_vits import SherpaVits


def registry():
    result = Registry()
    result.register('llm','chat_http',ChatHttp)
    result.register('stt','sensevoice_buffered',SenseVoiceProvider)
    result.register('tts','gptsovits_http',GptSovitsHttp)
    result.register('tts','sherpa_vits_korean',SherpaVits)
    for role in ['llm','stt','tts','kws','vad']:
        result.register(role,'company_rpc',RemoteProvider)
    for role in ['stt','tts','kws','vad']:
        result.register(role,'sherpa',SherpaProvider)
    return result
