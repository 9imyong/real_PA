"""Actual Chromium and local models; synthetic text, no physical audio claims.

Run with a Python environment containing real-pa[audio] and playwright.
Uses the installed package, so wheel assets are tested as well.
"""
import argparse
import asyncio
from contextlib import asynccontextmanager
import json
import math
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import wave
from time import monotonic

from playwright.async_api import async_playwright
from websockets.asyncio.server import serve
from real_pa.api import DuplexAPI, REQUIREMENTS
from real_pa.composition import registry
from real_pa.config import read_config
from real_pa.contracts import Context, Request
from real_pa.session import DialogueSession


@asynccontextmanager
async def tls_proxy(binary, upstream):
    """Exercise the deployment template on loopback with a temporary test cert."""
    if not binary:
        yield upstream
        return
    with tempfile.TemporaryDirectory(prefix='real-pa-tls-') as directory:
        root = Path(directory)
        certificate, key = root / 'cert.pem', root / 'key.pem'
        await asyncio.to_thread(subprocess.run, ['openssl', 'req', '-x509', '-newkey', 'rsa:2048',
            '-nodes', '-days', '1', '-subj', '/CN=localhost',
            '-addext', 'subjectAltName=DNS:localhost,IP:127.0.0.1',
            '-keyout', str(key), '-out', str(certificate)], check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        key.chmod(0o600)
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        template = (Path(__file__).resolve().parents[1] / 'deploy/nginx.conf').read_text()
        template = template.replace('listen 443 ssl;', f'listen 127.0.0.1:{port} ssl;')
        template = template.replace('assistant.example.com', 'localhost')
        template = template.replace('/etc/real-pa/tls/fullchain.pem', str(certificate))
        template = template.replace('/etc/real-pa/tls/privkey.pem', str(key))
        template = template.replace('http://127.0.0.1:18484', upstream)
        config = root / 'nginx.conf'
        config.write_text(f'worker_processes 1;\npid {root}/nginx.pid;\n'
                          f'error_log {root}/error.log warn;\nevents {{}}\nhttp {{\n'
                          f'client_body_temp_path {root}/body;\nproxy_temp_path {root}/proxy;\n'
                          f'fastcgi_temp_path {root}/fastcgi;\nuwsgi_temp_path {root}/uwsgi;\n'
                          f'scgi_temp_path {root}/scgi;\n{template}\n}}\n')
        process = await asyncio.create_subprocess_exec(binary, '-p', str(root), '-c', str(config),
            '-g', 'daemon off;', stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        url = f'https://127.0.0.1:{port}'
        try:
            import httpx
            async with httpx.AsyncClient(verify=False, trust_env=False) as client:
                async with asyncio.timeout(10):
                    while True:
                        if process.returncode is not None:
                            raise RuntimeError('test TLS proxy failed to start')
                        try:
                            response = await client.get(url + '/healthz')
                            if response.status_code == 200:
                                break
                        except httpx.TransportError:
                            pass
                        await asyncio.sleep(.05)
            yield url
        finally:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 5)
                except TimeoutError:
                    process.kill()
                    await process.wait()


async def main(args):
    if not math.isfinite(args.duration) or not 0 <= args.duration <= 3600:
        raise ValueError('duration must be between zero and 3600 seconds')
    if not math.isfinite(args.voice_duration) or not 0 <= args.voice_duration <= 3600:
        raise ValueError('voice duration must be between zero and 3600 seconds')
    if args.turns < 2:
        raise ValueError('at least two context-check turns are required')
    if not 1 <= args.voice_turns <= 1000:
        raise ValueError('voice turns must be between one and 1000')
    providers = await registry().build(read_config(args.config), REQUIREMENTS)
    token = secrets.token_urlsafe(32)
    api = DuplexAPI(providers, token)
    origins = [None]
    timings = []
    observed = {}
    failures = []
    context_metrics = []
    started_at = monotonic()
    # Record bounded failure metadata, never exception messages or model output.
    for role in ('llm', 'tts'):
        original = providers[role].stream
        async def diagnosed(request, context, original=original, role=role):
            if role == 'llm':
                messages = request.data.get('messages', [])
                context_metrics.append({'message_count': len(messages),
                    'synthetic_name_anchor_present': any(
                        message.get('role') == 'user' and message.get('content') ==
                        '내 이름은 테스트야. 기억하고 짧게 인사해 줘.' for message in messages),
                    'synthetic_name_question': bool(messages and messages[-1].get('content') ==
                        '내 이름이 뭐였지? 이름만 답해 줘.')})
                del context_metrics[:-5]
            try:
                async for event in original(request, context):
                    yield event
            except Exception as error:
                if len(failures) < 16:
                    failures.append({'stage': role, 'type': type(error).__name__,
                                     'elapsed': round(monotonic() - started_at, 3)})
                raise
        providers[role].stream = diagnosed
    original_emit = DialogueSession._emit
    async def emit(session, context, event):
        try:
            return await original_emit(session, context, event)
        except Exception as error:
            if len(failures) < 16:
                failures.append({'stage': 'output_queue', 'type': type(error).__name__,
                                 'elapsed': round(monotonic() - started_at, 3)})
            raise
    DialogueSession._emit = emit
    input_metrics = {'vad_frames': 0, 'stt_frames': 0, 'speech_started': 0,
                     'speech_ended': 0, 'transcript_final': 0, 'nonempty_final': 0, 'peak_pcm': 0}
    for role in ('vad', 'stt'):
        original = providers[role].stream
        async def measured(request, context, original=original, role=role):
            input_metrics[role + '_frames'] += 1
            if role == 'vad':
                import numpy as np
                samples = np.frombuffer(request.data['pcm'], dtype='<i2').astype('int32')
                input_metrics['peak_pcm'] = max(input_metrics['peak_pcm'], int(np.abs(samples).max(initial=0)))
            async for event in original(request, context):
                if event.kind in ('speech_started', 'speech_ended', 'transcript_final'):
                    input_metrics[event.kind] += 1
                if event.kind == 'transcript_final' and event.data.get('text', '').strip():
                    input_metrics['nonempty_final'] += 1
                yield event
        providers[role].stream = measured
    args.output.write_text(json.dumps({'status': 'running', 'pid': os.getpid(), 'completed_text_turns': 0}))
    acknowledgements = {'accepted': 0, 'rejected': 0}
    original_ack = DialogueSession.acknowledge
    def acknowledge(session, generation, chunk):
        accepted = original_ack(session, generation, chunk)
        acknowledgements['accepted' if accepted else 'rejected'] += 1
        return accepted
    DialogueSession.acknowledge = acknowledge
    audio_file = tempfile.NamedTemporaryFile(suffix='.wav')
    try:
        import numpy as np
        chunks = [event async for event in providers['tts'].stream(
            Request('tts', {'text': '안녕하세요. 오늘 일정 알려주세요.'}),
            Context('browser-synthetic-audio', 1, 1, 60)) if event.kind == 'audio_chunk']
        samples = np.frombuffer(b''.join(event.data['pcm'] for event in chunks), dtype='<i2')
        rate = chunks[0].data['sample_rate']
        resampled = np.interp(np.arange(int(len(samples) * 16000 / rate)),
                              np.arange(len(samples)) * 16000 / rate, samples).astype('<i2')
        with wave.open(audio_file.name, 'wb') as wav:
            wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            wav.writeframes(b'\0\0' * 32000 + resampled.tobytes() + b'\0\0' * 160000)
        async with serve(api.handle, '127.0.0.1', 0, origins=origins,
                         process_request=api.process_request, max_size=65536,
                         compression=None) as server:
            url = f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}'
            origins.append(url)
            async with tls_proxy(args.nginx, url) as url, async_playwright() as playwright:
                origins.append(url)
                browser = await playwright.chromium.launch(
                    executable_path=args.chromium, headless=True,
                    args=['--autoplay-policy=no-user-gesture-required', '--use-fake-ui-for-media-stream',
                          '--use-fake-device-for-media-stream', f'--use-file-for-fake-audio-capture={audio_file.name}',
                          ])
                page = None
                try:
                    page = await browser.new_page(viewport={'width': 1100, 'height': 800},
                                                  ignore_https_errors=bool(args.nginx))
                    await page.goto(url)
                    if args.fake_output:
                        await page.evaluate('''() => {
                            const Context = window.AudioContext;
                            window.AudioContext = class extends Context {
                                constructor(options) { super({...options, sinkId: {type: 'none'}}); }
                            };
                        }''')
                    # Credentials remain in memory; screenshots mask the field.
                    await page.evaluate('(token) => document.getElementById("token").value = token', token)
                    if args.output_rate:
                        await page.evaluate('(rate) => client.outputSampleRate = rate', args.output_rate)
                    await page.click('#start')
                    await page.wait_for_function('!document.getElementById("send").disabled')
                    if args.fake_output:
                        assert await page.evaluate('client._context.sinkId?.type === "none"')
                    await page.evaluate('''() => {
                        window.events = {};
                        const checkClock = client._checkPlaybackClock.bind(client);
                        client._checkPlaybackClock = () => {
                            window.lastClockCheck = {
                                audioState: client._context?.state,
                                audioTime: client._context?.currentTime,
                                queuedSources: client._sources.size,
                                stalledMs: client._playbackWatch
                                    ? performance.now() - client._playbackWatch.progressAt : 0,
                            };
                            return checkClock();
                        };
                        const onError = client.onError;
                        client.onError = text => {
                            window.browserError = {
                                category: text.includes('오디오 재생이 멈췄') ? 'output_clock_stalled' : 'other_client_error',
                                clock: window.lastClockCheck,
                            };
                            return onError(text);
                        };
                        window.firstAudioReceivedMs = [];
                        let pendingTextAt = null;
                        const submit = client.sendText.bind(client);
                        client.sendText = text => {
                            pendingTextAt = performance.now();
                            const accepted = submit(text);
                            if (!accepted) pendingTextAt = null;
                            return accepted;
                        };
                        const receive = client._receive.bind(client);
                        client._receive = message => {
                            events[message.type] = (events[message.type] || 0) + 1;
                            if (message.type === 'error') window.failure = {
                                code: message.data.code, sources: client._sources.size,
                                audioState: client._context?.state, audioTime: client._context?.currentTime,
                                audioSampleRate: client._context?.sampleRate,
                                nextStart: client._nextStart, queue: client._playbackQueue.map(item => ({chunk: item.chunk, done: item.done}))
                            };
                            const result = receive(message);
                            if (message.type === 'audio_chunk' && pendingTextAt !== null &&
                                !client._awaitingInterrupt && message.generation_id === client._generation &&
                                client._sources.size > 0) {
                                firstAudioReceivedMs.push(performance.now() - pendingTextAt);
                                pendingTextAt = null;
                            }
                            return result;
                        };
                    }''')
                    conversation_started = monotonic()
                    index = 0
                    memory = False
                    while index < args.turns or monotonic() - conversation_started < args.duration:
                        prompt = ('내 이름은 테스트야. 기억하고 짧게 인사해 줘.' if index == 0
                                  else '내 이름이 뭐였지? 이름만 답해 줘.' if index == args.turns - 1
                                  else '한국어로 한 단어만 인사해 줘.')
                        started = monotonic()
                        await page.fill('#text', prompt)
                        await page.click('#send')
                        await page.wait_for_function(
                            '(count) => document.querySelectorAll(".message.assistant").length >= count', arg=index + 1,
                            timeout=60000)
                        try:
                            await page.wait_for_function('client._turnDone && client._sources.size === 0', timeout=60000)
                        except Exception:
                            observed['text_playback'] = await page.evaluate('''() => ({events, failure: window.failure,
                                active: client.isActive, sources: client._sources.size,
                                done: client._turnDone, audioState: client._context?.state,
                                audioTime: client._context?.currentTime,
                                nextStart: client._nextStart,
                                sink: client._context?.sinkId?.type || 'default',
                                notice: document.getElementById('notice').textContent})''')
                            raise
                        timings.append(round(monotonic() - started, 3))
                        if index == args.turns - 1:
                            memory = '테스트' in await page.locator('.message.assistant').last.inner_text()
                            observed['context_recall'] = memory
                            observed['context_metrics_at_recall'] = list(context_metrics)
                            assert memory
                        index += 1
                        args.output.write_text(json.dumps({'status': 'running', 'pid': os.getpid(),
                                                          'completed_text_turns': len(timings),
                                                          'text_phase_seconds': round(monotonic() - conversation_started, 3),
                                                          'minimum_duration_seconds': args.duration}))
                        print(json.dumps({'completed_turn': index}), flush=True)
                    text_phase_seconds = monotonic() - conversation_started
                    first_audio_received_ms = await page.evaluate('firstAudioReceivedMs')
                    assert len(first_audio_received_ms) == len(timings)
                    ordered = sorted(first_audio_received_ms)
                    first_audio_stats = {
                        'samples': len(ordered),
                        'p50_ms': round(ordered[math.ceil(len(ordered) * .5) - 1], 3),
                        'p95_ms': round(ordered[math.ceil(len(ordered) * .95) - 1], 3),
                        'measurement': 'browser sendText to first accepted audio_chunk receipt; excludes physical playback and speech endpoint',
                        'raw_ms': [round(value, 3) for value in first_audio_received_ms],
                    }
                    observed['context_recall'] = memory
                    await page.evaluate('''() => {
                        window.smoke = {interruptsDuringAudio: 0, finals: 0};
                        const receive = client._receive.bind(client);
                        client._receive = message => {
                            if (message.type === 'interrupted' && client._sources.size) smoke.interruptsDuringAudio++;
                            if (message.type === 'transcript_final' && message.data.text.trim()) smoke.finals++;
                            return receive(message);
                        };
                    }''')
                    await page.check('#microphone')
                    await page.wait_for_function('client._media !== null', timeout=10000)
                    await page.fill('#text', '한국어로 긴 인사말을 다섯 문장 작성해 줘.')
                    await page.click('#send')
                    await page.wait_for_function('smoke.finals >= 1', timeout=30000)
                    voice_started = monotonic()
                    completed_voice_turns = 0
                    next_final = 1
                    # Keep the same capture track alive across repeated synthetic
                    # utterances, including every generated/playback response.
                    while (completed_voice_turns < args.voice_turns or
                           monotonic() - voice_started < args.voice_duration):
                        await page.wait_for_function('(target) => smoke.finals >= target',
                                                     arg=next_final, timeout=60000)
                        await page.wait_for_function(
                            'client.isActive && client._turnDone && client._sources.size === 0',
                            timeout=60000)
                        assert await page.evaluate('''() => client.microphone &&
                            client._media.getAudioTracks().every(track => track.readyState === 'live')''')
                        completed_voice_turns += 1
                        next_final = await page.evaluate('smoke.finals + 1')
                        args.output.write_text(json.dumps({'status': 'running', 'pid': os.getpid(),
                            'completed_text_turns': len(timings),
                            'completed_voice_turns': completed_voice_turns,
                            'continuous_microphone': True,
                            'minimum_voice_duration_seconds': args.voice_duration,
                            'voice_phase_seconds': round(monotonic() - voice_started, 3)}))
                        print(json.dumps({'completed_voice_turn': completed_voice_turns}), flush=True)
                    voice_phase_seconds = monotonic() - voice_started
                    await page.uncheck('#microphone')
                    try:
                        await page.wait_for_function('client._turnDone && client._sources.size === 0', timeout=60000)
                    except Exception:
                        observed['voice_playback'] = await page.evaluate('''() => ({events,
                            active: client.isActive, done: client._turnDone,
                            sources: client._sources.size, generation: client._generation,
                            audioTime: client._context?.currentTime, audioState: client._context?.state,
                            sink: client._context?.sinkId?.type || 'default',
                            notice: document.getElementById('notice').textContent})''')
                        raise
                    voice = await page.evaluate('smoke')
                    output_rate = await page.evaluate('client._context.sampleRate')
                    await page.screenshot(path=str(args.output.with_suffix('.png')))
                    await page.click('#stop')
                    await page.wait_for_function('!client.isActive')
                    async with asyncio.timeout(5):
                        while api.active:
                            await asyncio.sleep(.01)
                    result = {'status': 'passed', 'actual_chromium': True, 'actual_local_models': True,
                              'installed_package_assets': True, 'completed_turns': len(timings),
                              'text_phase_seconds': round(text_phase_seconds, 3),
                              'minimum_duration_seconds': args.duration,
                              'context_checked_at_turn': args.turns,
                              'context_metrics_at_recall': observed.get('context_metrics_at_recall', []),
                              'continuous_microphone_during_text_phase': False,
                              'continuous_microphone_during_voice_phase': True,
                              'completed_voice_turns': completed_voice_turns,
                              'voice_phase_seconds': round(voice_phase_seconds, 3),
                              'minimum_voice_duration_seconds': args.voice_duration,
                              'actual_nginx_tls_proxy': bool(args.nginx),
                              'test_certificate_only': bool(args.nginx),
                              'context_recall': memory, 'turn_seconds': timings,
                              'first_audio_received': first_audio_stats,
                              'sessions_after_disconnect': api.active,
                              'synthetic_inputs_only': True, 'voice': voice,
                              'synthetic_output_device': args.fake_output,
                              'output_sample_rate': output_rate,
                              'input_metrics': input_metrics,
                              'physical_audio_verified': False}
                    observed = {'context_recall': memory, 'sessions_after_disconnect': api.active, 'voice': voice}
                    assert memory and api.active == 0
                    assert text_phase_seconds >= args.duration
                    assert voice_phase_seconds >= args.voice_duration
                    assert voice['finals'] >= 1 and voice['interruptsDuringAudio'] >= 1
                    args.output.write_text(json.dumps(result, indent=2))
                    print(json.dumps(result))
                finally:
                    if page is not None:
                        try:
                            observed['browser_terminal'] = await page.evaluate('''() => ({
                                events: window.events, error: window.browserError,
                                active: client.isActive, pendingSources: client._sources.size,
                                audioState: client._context?.state, audioTime: client._context?.currentTime,
                                firstAudioReceivedMs: window.firstAudioReceivedMs,
                            })''')
                        except Exception:
                            observed['browser_terminal'] = {'inspection_unavailable': True}
                    await browser.close()
    except BaseException as error:
        args.output.write_text(json.dumps({'status': 'failed', 'error_type': type(error).__name__,
                                          'completed_text_turns': len(timings),
                                          'acknowledgements': acknowledgements,
                                          'synthetic_output_device': args.fake_output,
                                          'input_metrics': input_metrics,
                                          'stage_failures': failures, **observed}, indent=2))
        raise
    finally:
        DialogueSession.acknowledge = original_ack
        DialogueSession._emit = original_emit
        for provider in reversed(list(providers.values())):
            await provider.close()
        audio_file.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--chromium', required=True)
    parser.add_argument('--nginx', help='Optional nginx executable for local HTTPS/WSS deployment-template test')
    parser.add_argument('--turns', type=int, default=10)
    parser.add_argument('--voice-turns', type=int, default=1,
                        help='Repeated synthetic voice/response cycles with microphone continuously enabled')
    parser.add_argument('--duration', type=float, default=0,
                        help='Minimum seconds of text/playback on one connection; microphone tested afterward')
    parser.add_argument('--voice-duration', type=float, default=0,
                        help='Minimum seconds of continuous microphone voice/response cycles; synthetic input')
    parser.add_argument('--output-rate', type=int, default=0,
                        help='Optional device clock rate for hardware comparison; capture wire format stays 16kHz')
    parser.add_argument('--fake-output', action='store_true',
                        help='Use Web Audio silent sink; not a physical playback test')
    parser.add_argument('--output', type=Path, default=Path('artifacts/browser-smoke.json'))
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(main(args))
