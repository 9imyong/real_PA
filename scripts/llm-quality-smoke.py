"""Sequential synthetic Korean dialogue; metrics omit conversation text.

This is a diagnostic, not an automatic factual-accuracy certification.
--review prints synthetic answers for manual review, never user dialogue.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import time

import httpx
from real_pa.config import read_config


QUESTIONS = (
    '안녕하세요.',
    '너의 이름은 뭐야?',
    '지금 어떤 모델을 사용해?',
    '모기가 많이 활동하는 계절과 이유를 알려줘.',
    '지금도 살아 있는 공룡이 있니?',
    '버블 정렬 원리를 설명하고 [5, 1, 3]을 오름차순으로 정렬해줘.',
    '방금 설명한 정렬 알고리즘 이름은 뭐였지?',
    '내 이름은 하늘이고 좋아하는 음료는 보리차야. 기억해줘.',
    '파이썬 문자열을 만드는 방법을 짧게 알려줘.',
    '내 이름과 좋아하는 음료가 뭐였지?',
)


async def main(args):
    config = read_config(args.config)['llm']
    options = config.options
    messages = []
    if options.get('system_prompt'):
        messages.append({'role': 'system', 'content': options['system_prompt']})
    report = {'status': 'running', 'actual_model': True, 'synthetic_dialogue_only': True,
              'model_id': config.manifest['model_id'], 'results': [],
              'factual_accuracy_requires_manual_review': True}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        headers = {}
        if options.get('token_env'):
            headers['Authorization'] = 'Bearer ' + os.environ[options['token_env']]
        async with httpx.AsyncClient(timeout=config.timeout, trust_env=False, headers=headers) as client:
            for index, question in enumerate(QUESTIONS):
                messages.append({'role': 'user', 'content': question})
                started = time.monotonic()
                response = await client.post(options['base_url'].rstrip('/') + '/chat/completions',
                    json={'model': config.manifest['model_id'], 'messages': messages,
                          'max_tokens': options.get('max_tokens', 128),
                          'temperature': options.get('temperature', 0.3),
                          'chat_template_kwargs': {'enable_thinking': options.get('enable_thinking', False)}})
                response.raise_for_status()
                choice = response.json()['choices'][0]
                answer = choice['message']['content']
                messages.append({'role': 'assistant', 'content': answer})
                result = {'case_index': index, 'finish_reason': choice['finish_reason'],
                          'characters': len(answer), 'elapsed_seconds': round(time.monotonic() - started, 3)}
                if index == 1:
                    result['assistant_name_present'] = 'real-PA' in answer
                if index == 2:
                    result['model_name_present'] = 'Qwen3' in answer
                if index == 6:
                    result['previous_algorithm_present'] = '버블' in answer or 'Bubble' in answer
                if index == 9:
                    result['both_synthetic_facts_present'] = '하늘' in answer and '보리차' in answer
                report['results'].append(result)
                if args.review:
                    print(f'Case {index}: {answer}', flush=True)
                args.output.write_text(json.dumps(report, indent=2))
        report['status'] = 'measured'
    except BaseException as error:
        report.update(status='failed', error_type=type(error).__name__)
        raise
    finally:
        args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path('artifacts/llm-quality-smoke.json'))
    parser.add_argument('--review', action='store_true')
    asyncio.run(main(parser.parse_args()))
