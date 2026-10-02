"""Local real-model voice concurrency diagnostic; synthetic PCM, paced buffer ACK.

Shares the configured LLM endpoint. No physical browser/AEC/WAN certification.
RAM measures this benchmark API and load driver together, excluding live API.
"""
import argparse
import asyncio
import base64
import contextlib
import json
import math
import os
from pathlib import Path
import secrets
import subprocess
import time

import numpy as np
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from real_pa.api import DuplexAPI, REQUIREMENTS
from real_pa.composition import registry
from real_pa.config import read_config
from real_pa.contracts import Context, Request, ResourceExhausted
from real_pa.robot import RobotRuntime


def memory():
    fields = {k: v.strip() for k, v in (line.split(':', 1) for line in
        Path('/proc/self/status').read_text().splitlines() if ':' in line)}
    cpu = Path('/proc/self/stat').read_text().rsplit(')', 1)[1].split()
    return {'rss_kib': int(fields['VmRSS'].split()[0]),
            'lifetime_peak_rss_kib': int(fields['VmHWM'].split()[0]),
            'cpu_ticks': int(cpu[11]) + int(cpu[12])}


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)] if values else None


async def user(url, token, frames, voice_end_index, rounds, gate):
    records = []
    async with connect(url, max_size=65536, proxy=None) as ws:
        await ws.send(json.dumps({'type': 'start', 'token': token, 'ui_started': True}))
        assert json.loads(await ws.recv())['type'] == 'session_started'
        capture = asyncio.Queue()
        playback = asyncio.Queue(maxsize=128)
        current = {}
        finished = asyncio.Event()

        async def feed():
            due = time.monotonic()
            while True:
                item = capture.get_nowait() if not capture.empty() else (b'\0' * 3200, False)
                await ws.send(item[0])
                if item[1]: current['input_end'] = time.monotonic()
                due += .1
                await asyncio.sleep(max(0, due - time.monotonic()))

        async def play():
            while True:
                event = await playback.get()
                data = event['data']
                pcm = base64.b64decode(data['pcm']['$pcm16'], validate=True)
                await asyncio.sleep(len(pcm) / 2 / data['sample_rate'])
                await ws.send(json.dumps({'type': 'playback_ack', 'generation_id': event['generation_id'],
                                          'chunk_id': data['chunk_id']}))
                playback.task_done()

        async def receive():
            async for raw in ws:
                event = json.loads(raw)
                if event['type'] in {'error', 'input_rejected'}:
                    raise RuntimeError(event['type'])
                if event['type'] == 'transcript_final' and event['data'].get('text', '').strip():
                    current['final_at'] = time.monotonic()
                if event['type'] == 'audio_chunk':
                    current.setdefault('audio_at', time.monotonic())
                    await playback.put(event)
                if event['type'] == 'turn_done': finished.set()

        tasks = [asyncio.create_task(feed()), asyncio.create_task(play()), asyncio.create_task(receive())]
        try:
            await gate.wait()
            for _ in range(rounds):
                current.clear(); finished.clear(); started = time.monotonic()
                for index, frame in enumerate(frames):
                    capture.put_nowait((frame, index == voice_end_index))
                waiter = asyncio.create_task(finished.wait())
                try:
                    async with asyncio.timeout(90):
                        done, _ = await asyncio.wait([waiter, *tasks], return_when=asyncio.FIRST_COMPLETED)
                        for task in tasks:
                            if task in done:
                                await task
                                raise RuntimeError('client background task ended')
                        await playback.join()
                    assert {'input_end', 'audio_at', 'final_at'} <= current.keys()
                    records.append({'first_audio_seconds': round(current['audio_at'] - current['input_end'], 3),
                                    'final_transcript_seconds': round(current['final_at'] - current['input_end'], 3),
                                    'completed_seconds': round(time.monotonic() - started, 3)})
                finally:
                    waiter.cancel(); await asyncio.gather(waiter, return_exceptions=True)
                await asyncio.sleep(.3)
            await ws.send(json.dumps({'type': 'close'}))
            return {'status': 'passed', 'turns': records}
        except Exception as error:
            return {'status': 'failed', 'error_type': type(error).__name__, 'turns': records}
        finally:
            for task in tasks: task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


async def main(args):
    if not 1 <= args.rounds <= 100 or any(n < 1 or n > 64 for n in args.concurrency):
        raise ValueError('bounded rounds/concurrency required')
    report = {'status': 'running', 'synthetic_audio_only': True, 'physical_audio_verified': False,
              'llm_endpoint_shared_with_live_service': True,
              'ram_scope': 'benchmark API plus driver; live API/LLM/browser excluded',
              'latency_reference': 'last injected TTS frame with AC RMS >= .001; first received audio, not physical playback',
              'gpu_scope': 'whole GPU including live service; sampled once per second',
              'ack_mode': 'paced to PCM duration; no physical playback', 'stages': []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    configs = read_config(args.config)
    report['models'] = {role: {'adapter': config.adapter,
                       'model_id': config.manifest['model_id'], 'revision': config.manifest['revision']}
                       for role, config in configs.items()}
    args.output.write_text(json.dumps(report, indent=2))
    providers = await registry().build(configs, REQUIREMENTS)
    original_accept = RobotRuntime.accept_audio
    capture_overflows = 0
    def measured_accept(runtime, pcm):
        nonlocal capture_overflows
        try:
            return original_accept(runtime, pcm)
        except ResourceExhausted:
            capture_overflows += 1
            raise
    RobotRuntime.accept_audio = measured_accept
    token = secrets.token_urlsafe(32)
    api = DuplexAPI(providers, max_sessions=max(args.concurrency))
    try:
        events = [e async for e in providers['tts'].stream(
            Request('tts', {'text': args.phrase}), Context('load-source', 1, 1, 60))]
        chunks = [e for e in events if e.kind == 'audio_chunk']
        rate = chunks[0].data['sample_rate']
        report['input_sample_rate'] = 16000
        report['output_sample_rate'] = rate
        samples = np.frombuffer(b''.join(e.data['pcm'] for e in chunks), dtype='<i2')
        resampled = np.interp(np.arange(int(len(samples) * 16000 / rate)),
                              np.arange(len(samples)) * 16000 / rate, samples).astype('<i2')
        pcm = b'\0' * 9600 + resampled.tobytes() + b'\0' * 32000
        pcm += b'\0' * ((-len(pcm)) % 3200)
        frames = [pcm[i:i + 3200] for i in range(0, len(pcm), 3200)]
        energetic = []
        for index, frame in enumerate(frames):
            block = np.frombuffer(frame, dtype='<i2').astype(np.float32) / 32768
            if np.sqrt(np.mean((block - block.mean()) ** 2)) >= .001:
                energetic.append(index)
        if not energetic: raise RuntimeError('synthetic speech has no usable signal')
        voice_end_index = energetic[-1]
        async with serve(api.handle, '127.0.0.1', 0, process_request=api.process_request,
                         max_size=65536, max_queue=8, compression=None) as server:
            url = f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1/realtime'
            for count in args.concurrency:
                overflow_baseline = capture_overflows
                baseline = memory(); readings = []; gpu_readings = []; sampling = True
                def gpu_memory():
                    try:
                        return int(subprocess.check_output(['nvidia-smi', '--query-gpu=memory.used',
                            '--format=csv,noheader,nounits'], text=True, timeout=3).splitlines()[0])
                    except (OSError, ValueError, subprocess.SubprocessError): return None
                async def sample():
                    next_gpu = 0
                    while sampling:
                        readings.append(memory())
                        if time.monotonic() >= next_gpu:
                            value = await asyncio.to_thread(gpu_memory)
                            if value is not None: gpu_readings.append(value)
                            next_gpu = time.monotonic() + 1
                        await asyncio.sleep(.1)
                sampler = asyncio.create_task(sample())
                gate = asyncio.Event()
                tasks = [asyncio.create_task(user(url, token, frames, voice_end_index, args.rounds, gate))
                         for _ in range(count)]
                await asyncio.sleep(.5); started = time.monotonic(); gate.set()
                results = await asyncio.gather(*tasks, return_exceptions=True)
                elapsed = time.monotonic() - started
                sampling = False; await sampler
                await asyncio.sleep(.5)
                normalized = [r if isinstance(r, dict) else
                              {'status': 'failed', 'error_type': type(r).__name__, 'turns': []} for r in results]
                turns = [t for r in normalized for t in r['turns']]
                latest = memory()
                stage = {'concurrent_users': count, 'requested_turns': count * args.rounds,
                         'completed_turns': len(turns), 'failed_users': sum(r['status'] != 'passed' for r in normalized),
                         'capture_queue_overflows': capture_overflows - overflow_baseline,
                         'elapsed_seconds': round(elapsed, 3), 'rss_baseline_kib': baseline['rss_kib'],
                         'sampled_peak_rss_kib': max(r['rss_kib'] for r in readings),
                         'lifetime_peak_rss_kib': latest['lifetime_peak_rss_kib'],
                         'sampled_gpu_peak_mib': max(gpu_readings) if gpu_readings else None,
                         'average_process_cpu_percent': round(100 * (latest['cpu_ticks'] - baseline['cpu_ticks']) /
                             os.sysconf('SC_CLK_TCK') / elapsed, 1),
                         'first_audio_p50_seconds': percentile([t['first_audio_seconds'] for t in turns], .5),
                         'first_audio_p95_seconds': percentile([t['first_audio_seconds'] for t in turns], .95),
                         'final_transcript_p95_seconds': percentile([t['final_transcript_seconds'] for t in turns], .95),
                         'sessions_after_disconnect': api.active, 'clients': normalized}
                report['stages'].append(stage); args.output.write_text(json.dumps(report, indent=2))
                print(json.dumps({k: v for k, v in stage.items() if k != 'clients'}), flush=True)
                if stage['failed_users'] or api.active:
                    report['status'] = 'capacity_failure_observed'; break
            else: report['status'] = 'measured'
    finally:
        RobotRuntime.accept_audio = original_accept
        for provider in reversed(list(providers.values())):
            with contextlib.suppress(Exception): await provider.close()
        args.output.write_text(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--concurrency', nargs='+', type=int, default=[1, 2, 4])
    parser.add_argument('--rounds', type=int, default=5)
    parser.add_argument('--phrase', default='아침 산책의 장점을 두 문장으로 설명해 주세요.')
    parser.add_argument('--output', type=Path, default=Path('artifacts/voice-load-smoke.json'))
    asyncio.run(main(parser.parse_args()))
