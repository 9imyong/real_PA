"""Real models through native and self-hosted RPC adapters, with synthetic input.

This verifies two adapter paths per role, not two different model architectures.
No physical audio, recognition accuracy, or WAN throughput claim.
"""
import argparse
import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import secrets
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from real_pa.adapters.rpc import InferenceGateway, RemoteProvider
from real_pa.composition import registry
from real_pa.config import read_config
from real_pa.contracts import Context, Request


async def main(args):
    import numpy as np
    from websockets.asyncio.server import serve
    local = {}
    token_name = 'REAL_PA_ADAPTER_SMOKE_TOKEN'
    previous = os.environ.get(token_name)
    token = secrets.token_urlsafe(32)
    os.environ[token_name] = token
    remote = {}
    report = {'status': 'running', 'actual_models': True, 'synthetic_input_only': True,
              'different_model_architectures': False, 'roles': {}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2))
    try:
        configs = read_config(args.config)
        local = await registry().build(configs)
        chunks = [e async for e in local['tts'].stream(Request('tts', {'text': '안녕하세요. 오늘 일정 알려주세요.'}),
                  Context('adapter-source', 1, 1, 60)) if e.kind == 'audio_chunk']
        samples = np.frombuffer(b''.join(e.data['pcm'] for e in chunks), dtype='<i2')
        rate = chunks[0].data['sample_rate']
        pcm = np.interp(np.arange(int(len(samples) * 16000 / rate)),
                        np.arange(len(samples)) * 16000 / rate, samples).astype('<i2').tobytes()
        pcm += b'\0\0' * 16000
        gateway = InferenceGateway(local, token)
        async with serve(gateway.handle, '127.0.0.1', 0, max_size=1024 * 1024) as server:
            url = f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}'
            for role, config in configs.items():
                provider = RemoteProvider(replace(config, adapter='company_rpc',
                    options={'url': url, 'token_env': token_name}))
                remote[role] = provider
                await provider.load()
                assert provider.capabilities.features == local[role].capabilities.features
                observations = {}
                for name, candidate in [('native', local[role]), ('company_rpc', provider)]:
                    session_id = f'adapter-{role}-{name}'
                    data = ({'messages': [{'role': 'user', 'content': '한국어로 짧게 인사해 주세요.'}]} if role == 'llm'
                            else {'text': '안녕하세요.'} if role == 'tts'
                            else {'pcm': pcm, 'sample_rate': 16000, 'sequence': 1, 'final': True})
                    events = [e async for e in candidate.stream(Request(role, data), Context(session_id, 1, 1, 60))]
                    assert events and events[-1].kind == 'completed'
                    if role == 'llm':
                        assert any(e.kind == 'text_delta' and e.data['text'].strip() for e in events)
                    if role == 'stt':
                        assert any(e.kind == 'transcript_final' and e.data['text'].strip() for e in events)
                    if role == 'tts':
                        audio = [e for e in events if e.kind == 'audio_chunk']
                        assert audio and all(isinstance(e.data['pcm'], bytes) and len(e.data['pcm']) % 2 == 0
                                             and e.data['sample_rate'] > 0 for e in audio)
                    await candidate.reset(session_id)
                    if hasattr(local[role], 'sessions'):
                        assert session_id not in local[role].sessions
                    context = Context(session_id, 2, 2, 60)
                    context.cancelled.set()
                    cancelled = False
                    try:
                        async for _ in candidate.stream(Request(role, data), context):
                            raise AssertionError('cancelled request emitted output')
                    except asyncio.CancelledError:
                        cancelled = True
                    assert cancelled
                    observations[name] = {'event_kinds': sorted(set(e.kind for e in events)),
                                          'event_count': len(events), 'reset': True, 'pre_cancel': True}
                assert observations['native']['event_kinds'] == observations['company_rpc']['event_kinds']
                report['roles'][role] = observations
            assert gateway.active == 0
            report['status'] = 'passed'
    except BaseException as error:
        report.update(status='failed', error_type=type(error).__name__)
        raise
    finally:
        for provider in reversed(list(remote.values())): await provider.close()
        for provider in reversed(list(local.values())): await provider.close()
        if previous is None: os.environ.pop(token_name, None)
        else: os.environ[token_name] = previous
        args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config')
    parser.add_argument('--output', type=Path, default=Path('artifacts/model-adapter-smoke.json'))
    asyncio.run(main(parser.parse_args()))
