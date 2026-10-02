"""Actual audio models through production VAD/STT orchestration.

Synthetic speech only; fixture LLM suppresses responses to isolate recognition.
No microphone, speaker, browser AEC, or assistant quality claim.
"""
import argparse
import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from real_pa.composition import registry
from real_pa.config import read_config
from real_pa.contracts import Context, Event, InvalidOutput, Request
from real_pa.robot import RobotRuntime
from real_pa.session import DialogueSession


class SilentLlm:
    async def stream(self, request, context):
        yield Event('completed')
    async def reset(self, session_id): pass


async def main(args):
    import numpy as np
    configs = read_config(args.config)
    providers = await registry().build({role: configs[role] for role in ('stt', 'vad', 'tts', 'kws')})
    session = DialogueSession('gated-audio-diagnostic', SilentLlm(), providers['tts'])
    runtime = RobotRuntime(session, providers, max_utterance_seconds=args.window)
    captured = []
    original_stt = providers['stt'].stream
    async def observe(request, context):
        captured.append(request.data['pcm'])
        report['recognizer_final_requests'] += bool(request.data.get('final'))
        if request.data.get('final') and runtime.speaking:
            report['segment_boundaries'] += 1
        async for event in original_stt(request, context):
            if event.kind == 'transcript_partial':
                report['partial_events'] += 1
                report['nonempty_partials'] += bool(event.data.get('text', '').strip())
            yield event
    providers['stt'].stream = observe
    report = {'actual_audio_models': True, 'fixture_llm': True, 'synthetic_input_only': True,
              'finals': 0, 'nonempty_finals': 0, 'transcript_characters': 0,
              'recognizer_window_seconds': args.window, 'recognizer_final_requests': 0}
    report['segment_boundaries'] = 0
    report['partial_events'] = report['nonempty_partials'] = 0
    async def collect():
        while True:
            _, event = await session.next_event()
            if event.kind == 'transcript_final':
                text = event.data['text'].strip()
                report['finals'] += 1
                report['nonempty_finals'] += bool(text)
                report['transcript_characters'] = max(report['transcript_characters'], len(text))
    consumer = asyncio.create_task(collect())
    try:
        chunks = [event async for event in providers['tts'].stream(
            Request('tts', {'text': '안녕하세요. 오늘 일정 알려주세요.'}),
            Context('gated-synthetic-source', 1, 1, 60)) if event.kind == 'audio_chunk']
        samples = np.frombuffer(b''.join(event.data['pcm'] for event in chunks), dtype='<i2')
        rate = chunks[0].data['sample_rate']
        resampled = np.interp(np.arange(int(len(samples) * 16000 / rate)),
                              np.arange(len(samples)) * 16000 / rate, samples).astype('<i2').tobytes()
        if args.trim_loop_silence:
            # Synthetic source only: remove the loop's leading/trailing silence
            # so repetition can exercise a single sustained VAD turn.
            values = np.frombuffer(resampled, dtype='<i2').astype('int32')
            voiced = np.flatnonzero(np.abs(values) > 128)
            if not len(voiced):
                raise ValueError('synthetic source contains no speech signal')
            first = max(0, int(voiced[0]) - 640)
            last = min(len(values), int(voiced[-1]) + 641)
            resampled = values[first:last].astype('<i2').tobytes()
        pcm = b'\0\0' * 16000 + resampled * args.repeats + b'\0\0' * 16000
        report['synthetic_audio_seconds'] = len(pcm) / 32000
        await runtime.start(ui_started=True)
        for offset in range(0, len(pcm), 3200):
            if runtime.running.done(): await runtime.running
            runtime.accept_audio(pcm[offset:offset + 3200].ljust(3200, b'\0'))
            await asyncio.sleep(.1)
        await asyncio.sleep(.3)
        if runtime.running.done(): await runtime.running
        cropped = b''.join(captured)
        report['gated_audio_seconds'] = len(cropped) / 32000
        for name, waveform in [('full', pcm), ('cropped', cropped)]:
            text = ''
            try:
                async for event in original_stt(Request('stt', {'pcm': waveform + b'\0\0' * 16000,
                                                              'sample_rate': 16000, 'final': True}),
                                                 Context('gated-compare-' + name, 1, 1, 60)):
                    if event.kind == 'transcript_final': text = event.data['text']
            except InvalidOutput:
                report[name + '_wave_status'] = 'input_rejected'
                if not args.allow_comparison_rejection:
                    raise
                continue
            report[name + '_wave_status'] = 'completed'
            report[name + '_wave_characters'] = len(text.strip())
        report['status'] = 'passed' if (report['nonempty_finals']
            and report['segment_boundaries'] >= args.require_segments
            and report['nonempty_partials'] >= args.require_partials) else 'failed'
        output = args.output
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps(report, indent=2))
        print(json.dumps(report))
        assert report['status'] == 'passed'
    finally:
        consumer.cancel()
        await asyncio.gather(consumer, return_exceptions=True)
        await runtime.close()
        for provider in providers.values(): await provider.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config')
    parser.add_argument('--window', type=float, default=20)
    parser.add_argument('--repeats', type=int, choices=range(1, 21), default=1)
    parser.add_argument('--require-segments', type=int, default=0)
    parser.add_argument('--require-partials', type=int, default=0)
    parser.add_argument('--allow-comparison-rejection', action='store_true',
                        help='Record rejected one-batch reference input separately; gated pipeline requirements still apply')
    parser.add_argument('--trim-loop-silence', action='store_true')
    parser.add_argument('--output', type=Path, default=Path('artifacts/gated-audio-smoke.json'))
    asyncio.run(main(parser.parse_args()))
