"""Actual model pipeline in a network-none container; synthetic audio and buffer ACK only."""
import argparse
import asyncio
import json
from pathlib import Path
import re
import socket
import sys

import httpx
import numpy as np
from real_pa.api import REQUIREMENTS
from real_pa.composition import registry
from real_pa.config import read_config
from real_pa.contracts import Context, Request
from real_pa.robot import RobotRuntime
from real_pa.session import DialogueSession


async def main(args):
    report = {'status': 'running', 'synthetic_audio_only': True,
              'buffer_ack_only': True, 'physical_audio_verified': False,
              'browser_used': False, 'external_network_blocked': False}
    args.output.write_text(json.dumps(report))
    providers, runtime, consumer, log_reader, process = {}, None, None, None, None
    browser_process = None
    try:
        if {name for _, name in socket.if_nameindex()} != {'lo'}:
            raise RuntimeError('requires a loopback-only network namespace')
        try:
            _, writer = await asyncio.wait_for(asyncio.open_connection('1.1.1.1', 443), 2)
        except OSError:
            report['external_network_blocked'] = True
        else:
            writer.close()
            await writer.wait_closed()
            raise RuntimeError('external route unexpectedly available')
        process = await asyncio.create_subprocess_exec('/opt/llama/llama-server',
            '--model', str(args.model), '--host', '127.0.0.1', '--port', '18181',
            '--ctx-size', '2048', '--n-gpu-layers', '99', '--threads', '4',
            '--no-webui', '--reasoning', 'off', '--cache-ram', '256',
            '--verbose', '--log-colors', 'off',
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)

        async def inspect_gpu_load():
            while line := await process.stdout.readline():
                report['server_log_lines_inspected'] = report.get('server_log_lines_inspected', 0) + 1
                match = re.search(rb'offloaded (\d+)/(\d+) layers to GPU', line)
                if match:
                    report['gpu_layers'] = {'offloaded': int(match[1]), 'total': int(match[2])}
                if re.search(rb'ggml_cuda_init: found [1-9][0-9]* CUDA devices', line):
                    report['cuda_device_detected'] = True
        log_reader = asyncio.create_task(inspect_gpu_load())
        async with httpx.AsyncClient(trust_env=False) as client:
            async with asyncio.timeout(60):
                while True:
                    if process.returncode is not None:
                        raise RuntimeError('local GPU server stopped')
                    try:
                        if (await client.get('http://127.0.0.1:18181/health')).status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    await asyncio.sleep(.1)
        if args.browser_script:
            report.update(browser_used=True, buffer_ack_only=False, synthetic_output_device=True)
            browser_output = args.output.with_name('offline-browser-result.json')
            browser_process = await asyncio.create_subprocess_exec(sys.executable, str(args.browser_script),
                '--config', str(args.config), '--chromium', args.chromium,
                '--turns', '10', '--voice-turns', '2', '--fake-output', '--output', str(browser_output))
            if await browser_process.wait() != 0:
                raise RuntimeError('offline browser scenario failed')
            browser_result = json.loads(browser_output.read_text())
            assert browser_result['status'] == 'passed'
            assert report.get('gpu_layers', {}).get('offloaded', 0) > 0
            report.update(status='passed', actual_local_models=True,
                          completed_text_turns=browser_result['completed_turns'],
                          completed_voice_turns=browser_result['completed_voice_turns'],
                          sessions_after_disconnect=browser_result['sessions_after_disconnect'])
            return
        providers = await registry().build(read_config(args.config), REQUIREMENTS)
        session = DialogueSession('offline-voice-smoke', providers['llm'], providers['tts'], timeout=60)
        runtime = RobotRuntime(session, providers)
        await runtime.start(ui_started=True)
        counts, completed = {}, asyncio.Queue()

        async def collect():
            while True:
                generation, event = await session.next_event()
                counts[event.kind] = counts.get(event.kind, 0) + 1
                if event.kind == 'transcript_final' and event.data.get('text', '').strip():
                    report['nonempty_voice_finals'] = report.get('nonempty_voice_finals', 0) + 1
                if event.kind == 'audio_chunk':
                    session.acknowledge(generation, event.data['chunk_id'])
                if event.kind == 'error':
                    await completed.put(False)
                if event.kind == 'turn_done':
                    await completed.put(True)
        consumer = asyncio.create_task(collect())
        chunks = [event async for event in providers['tts'].stream(
            Request('tts', {'text': '안녕하세요. 오늘 일정 알려주세요.'}),
            Context('offline-synthetic-source', 1, 1, 60)) if event.kind == 'audio_chunk']
        samples = np.frombuffer(b''.join(event.data['pcm'] for event in chunks), dtype='<i2')
        rate = chunks[0].data['sample_rate']
        pcm = np.interp(np.arange(int(len(samples) * 16000 / rate)),
                        np.arange(len(samples)) * 16000 / rate, samples).astype('<i2').tobytes()
        pcm = b'\0\0' * 16000 + pcm + b'\0\0' * 32000
        for offset in range(0, len(pcm), 3200):
            if runtime.running.done():
                await runtime.running
            runtime.accept_audio(pcm[offset:offset + 3200].ljust(3200, b'\0'))
            await asyncio.sleep(.1)
        assert await asyncio.wait_for(completed.get(), 60)
        assert report.get('nonempty_voice_finals', 0) >= 1 and counts.get('audio_chunk', 0) > 0
        await session.submit('한국어로 짧게 인사해 주세요.')
        assert await asyncio.wait_for(completed.get(), 60)
        assert any(message['role'] == 'assistant' for message in session.history)
        report.update(actual_local_models=True, roles_loaded=sorted(providers),
                      completed_turns=counts.get('turn_done', 0), event_counts=counts)
        gpu = report.get('gpu_layers', {})
        assert gpu.get('offloaded', 0) > 0
        report['status'] = 'passed'
    except BaseException as error:
        report.update(status='failed', error_type=type(error).__name__)
        raise
    finally:
        if browser_process and browser_process.returncode is None:
            browser_process.terminate()
            try:
                await asyncio.wait_for(browser_process.wait(), 5)
            except TimeoutError:
                browser_process.kill()
                await browser_process.wait()
        if consumer:
            consumer.cancel()
            await asyncio.gather(consumer, return_exceptions=True)
        if runtime:
            await runtime.close()
        for provider in reversed(list(providers.values())):
            await provider.close()
        if process and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 5)
            except TimeoutError:
                process.kill()
                await process.wait()
        if log_reader:
            await log_reader
        args.output.write_text(json.dumps(report, indent=2))
        print(json.dumps(report))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--browser-script', type=Path,
                        help='Optional actual browser scenario in the same network namespace')
    parser.add_argument('--chromium', help='Chromium executable for browser-script mode')
    args = parser.parse_args()
    if args.browser_script and not args.chromium:
        parser.error('--browser-script requires --chromium')
    asyncio.run(main(args))
