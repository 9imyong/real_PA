"""Real-model client tool round trip: chat_http + DialogueSession, fixture TTS.

Measures routed tool calls against a live self-hosted LLM. Tool results are
synthetic; this checks calling/answering behaviour, not Lemmy tools or audio.
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tests'))

from real_pa.client_tools import ClientToolBridge  # noqa: E402
from real_pa.composition import registry  # noqa: E402
from real_pa.config import read_config  # noqa: E402
from real_pa.session import DialogueSession  # noqa: E402
from test_runtime import FixtureProvider  # noqa: E402

TOOLS = [
    {'type': 'function', 'function': {'name': 'get_weather', 'description': '현재 날씨와 예보를 조회합니다',
     'parameters': {'type': 'object', 'properties': {'location': {'type': 'string', 'description': '도시 이름, 말하지 않았으면 생략'}}}}},
    {'type': 'function', 'function': {'name': 'search_youtube', 'description': 'YouTube 영상을 검색합니다',
     'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}}, 'required': ['query']}}},
]
RESULTS = {'get_weather': {'location': '로봇 위치', 'sky': '맑음', 'temperature_c': 21},
           'search_youtube': {'videos': [{'title': '아이유 라이브 모음'}], 'shown_on_screen': True}}
# Router decisions a client would make; the model only fills arguments.
CASES = [('서울 날씨 어때?', ['get_weather'], 'auto'), ('밖에 나가도 될까?', ['get_weather'], 'required'),
         ('아이유 노래 영상 틀어줘', ['search_youtube'], 'required'), ('안녕, 반가워', [], 'none')]


async def turn(session, bridge, text, names, choice):
    start = time.monotonic()
    calls, answer, first_text = [], '', None
    await session.submit(text, metadata={'output_audio': False})
    while True:
        generation, event = await session.next_event()
        if event.kind == 'route_request':
            bridge.resolve_route({'request_id': event.data['request_id'], 'tools': names, 'tool_choice': choice})
        elif event.kind == 'tool_call':
            calls.append({'name': event.data['name'], 'arguments': event.data['arguments']})
            bridge.resolve_output({'call_id': event.data['call_id'], 'result': RESULTS[event.data['name']]})
        elif event.kind == 'text_delta':
            first_text = first_text or time.monotonic() - start
            answer += event.data['text']
        elif event.kind == 'turn_done':
            session.acknowledge_text(generation)
            break
        elif event.kind == 'error':
            raise RuntimeError(event.data)
    return {'text': text, 'route': names, 'tool_choice': choice, 'calls': calls, 'answer': answer.strip(),
            'first_text_s': round(first_text or 0, 3), 'total_s': round(time.monotonic() - start, 3)}


async def main(args):
    configs = read_config(args.config)
    providers = await registry().build({'llm': configs['llm']}, {'llm': {'stream', 'cancel', 'tools'}})
    bridge = ClientToolBridge(TOOLS)
    session = DialogueSession('client-tools-smoke', providers['llm'], FixtureProvider('tts'), timeout=60,
                              system_prompt='당신은 한국어 로봇 비서 레미입니다. 2문장 이내 해요체로 답하세요.',
                              client_tools=bridge)
    try:
        results = [await turn(session, bridge, *case) for case in CASES]
    finally:
        await session.close()
        await providers['llm'].close()
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    asyncio.run(main(parser.parse_args()))
