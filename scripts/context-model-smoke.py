"""Measure synthetic name recall with fixed history; never print model text."""
import argparse
import asyncio
from dataclasses import replace
import json
from pathlib import Path

from real_pa.composition import registry
from real_pa.config import read_config
from real_pa.contracts import Context, Request


async def main(args):
    if not 1 <= args.trials <= 100:
        raise ValueError('trials must be between one and 100')
    config = read_config(args.config)['llm']
    # This is a fixed synthetic context, not captured browser/user history.
    messages = [{'role': 'user', 'content': '내 이름은 테스트야. 기억하고 짧게 인사해 줘.'},
                {'role': 'assistant', 'content': '안녕하세요, 테스트님.'}]
    for _ in range(8):
        messages.extend([{'role': 'user', 'content': '한국어로 한 단어만 인사해 줘.'},
                         {'role': 'assistant', 'content': '안녕하세요.'}])
    messages.append({'role': 'user', 'content': '내 이름이 뭐였지? 이름만 답해 줘.'})
    report = {'status': 'running', 'synthetic_context_only': True, 'actual_model': True,
              'message_count': len(messages), 'results': []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2))
    try:
        for temperature in (0.0, 0.3):
            options = dict(config.options, temperature=temperature)
            providers = await registry().build({'llm': replace(config, options=options)},
                                               {'llm': {'stream', 'cancel'}})
            provider = providers['llm']
            result = {'temperature': temperature, 'trials': args.trials,
                      'expected_name_present': 0, 'completed': 0}
            try:
                for index in range(args.trials):
                    parts = []
                    async for event in provider.stream(Request('llm', {'messages': messages}),
                                                       Context('synthetic-context', index + 1, index + 1, 60)):
                        if event.kind == 'text_delta':
                            parts.append(event.data['text'])
                        if event.kind == 'completed':
                            result['completed'] += 1
                    result['expected_name_present'] += int('테스트' in ''.join(parts))
            finally:
                await provider.close()
            report['results'].append(result)
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
    parser.add_argument('--trials', type=int, default=10)
    parser.add_argument('--output', type=Path, default=Path('artifacts/context-model-smoke.json'))
    asyncio.run(main(parser.parse_args()))
