"""Synthetic TTS/STT character-error diagnostic; no physical speech certification."""
import argparse
import asyncio
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from real_pa.composition import registry
from real_pa.config import read_config
from real_pa.contracts import Context, Request

PHRASES = ['안녕하세요 오늘도 함께 이야기해요', '오늘 일정 알려 주세요',
           '내일 오후 세 시에 회의가 있어요', '방금 이야기한 내용을 기억해 주세요',
           '대답을 조금 짧게 해 주세요', '잠시 기다려 주세요', '다음 질문을 할게요',
           '한국어로 설명해 주세요', '아침에 산책하면 기분이 좋아요', '지금 몇 시인지 알려 주세요']


def distance(left, right):
    previous = list(range(len(right) + 1))
    for index, char in enumerate(left, 1):
        current = [index]
        for other, target in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[other] + 1,
                               previous[other - 1] + (char != target)))
        previous = current
    return previous[-1]


async def main(args):
    import numpy as np
    report = {'status': 'running', 'synthetic_audio_only': True,
              'physical_audio_verified': False, 'general_quality_certified': False, 'combinations': []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    for path in args.configs:
        configs = read_config(path)
        providers = await registry().build({role: configs[role] for role in ['tts', 'stt']})
        results = []
        try:
            for index, phrase in enumerate(PHRASES):
                session = f'synthetic-{index}'
                events = [event async for event in providers['tts'].stream(
                    Request('tts', {'text': phrase}), Context(session, 1, 1, 60))]
                chunks = [event for event in events if event.kind == 'audio_chunk']
                assert chunks and events[-1].kind == 'completed'
                rate = chunks[0].data['sample_rate']
                assert all(chunk.data['sample_rate'] == rate for chunk in chunks)
                samples = np.frombuffer(b''.join(chunk.data['pcm'] for chunk in chunks), dtype='<i2')
                pcm = np.interp(np.arange(int(len(samples) * 16000 / rate)),
                                np.arange(len(samples)) * 16000 / rate, samples).astype('<i2').tobytes()
                finals = [event async for event in providers['stt'].stream(
                    Request('stt', {'pcm': pcm, 'sample_rate': 16000, 'final': True}), Context(session, 1, 1, 60))
                    if event.kind == 'transcript_final']
                assert len(finals) == 1
                expected = re.sub(r'[\W_]', '', phrase)
                actual = re.sub(r'[\W_]', '', finals[0].data['text'])
                results.append({'phrase_index': index, 'reference_characters': len(expected),
                                'recognized_characters': len(actual), 'edit_distance': distance(expected, actual),
                                'exact_match': expected == actual, 'nonempty': bool(actual)})
                await providers['stt'].reset(session)
            errors = sum(item['edit_distance'] for item in results)
            total = sum(item['reference_characters'] for item in results)
            report['combinations'].append({'tts_adapter': configs['tts'].adapter,
                'stt_adapter': configs['stt'].adapter, 'phrases': results,
                'normalized_character_error_rate': round(errors / total, 4),
                'exact_matches': sum(item['exact_match'] for item in results)})
        finally:
            for provider in reversed(list(providers.values())):
                await provider.close()
    report['status'] = 'completed'
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--configs', nargs='+', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path('artifacts/korean-roundtrip-smoke.json'))
    args = parser.parse_args()
    try:
        asyncio.run(main(args))
    except BaseException:
        if args.output.exists():
            report = json.loads(args.output.read_text())
            report['status'] = 'failed'
            args.output.write_text(json.dumps(report, indent=2) + '\n')
        raise
