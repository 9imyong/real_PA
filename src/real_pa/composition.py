"""Only location that knows built-in adapter implementations."""
from .registry import Registry
from .adapters.chat_http import ChatHttp
from .adapters.rpc import RemoteProvider
from .adapters.sherpa import SherpaProvider
from .adapters.sensevoice import SenseVoiceProvider


def registry():
    result = Registry()
    result.register('llm','chat_http',ChatHttp)
    result.register('stt','sensevoice_buffered',SenseVoiceProvider)
    for role in ['llm','stt','tts','kws','vad']:
        result.register(role,'company_rpc',RemoteProvider)
    for role in ['stt','tts','kws','vad']:
        result.register(role,'sherpa',SherpaProvider)
    return result
