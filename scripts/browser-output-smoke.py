"""Isolate Chromium's output clock without models, sockets, or microphone."""
import argparse
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright


async def main(args):
    if (not 1 <= args.duration <= 3600 or args.rate not in (0, 44100, 48000)
            or not 20 <= args.chunk_ms <= 1000):
        raise ValueError('invalid duration or output sample rate')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {'status': 'running', 'actual_chromium': True, 'actual_models': False,
              'physical_playback_verified': False, 'microphone_used': False,
              'synthetic_output_device': args.fake_output}
    report.update(signal=args.signal, chunk_ms=args.chunk_ms)
    args.output.write_text(json.dumps(report, indent=2))
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(executable_path=args.chromium,
                headless=True, args=['--autoplay-policy=no-user-gesture-required'])
            try:
                page = await browser.new_page()
                result = await page.evaluate('''async ({duration, rate, fake, signal, chunkMs}) => {
                    const options = {latencyHint: 'interactive'};
                    if (rate) options.sampleRate = rate;
                    if (fake) options.sinkId = {type: 'none'};
                    const context = new AudioContext(options);
                    const started = performance.now();
                    const clock = context.createConstantSource();
                    clock.offset.value = 0;
                    clock.connect(context.destination);
                    let completed = 0, pending = null;
                    try {
                        await context.resume();
                        clock.start();
                        while (performance.now() - started < duration * 1000) {
                            const source = context.createBufferSource();
                            // Procedural signal; no recorded speech or personal data.
                            source.buffer = context.createBuffer(1,
                                Math.round(context.sampleRate * chunkMs / 1000), context.sampleRate);
                            if (signal === 'tone') {
                                const samples = source.buffer.getChannelData(0);
                                for (let i = 0; i < samples.length; i++)
                                    samples[i] = .005 * Math.sin(2 * Math.PI * 440 * i / context.sampleRate);
                            }
                            source.connect(context.destination);
                            pending = source;
                            const ended = await new Promise(resolve => {
                                const timer = setTimeout(() => resolve(false), 3000);
                                source.onended = () => { clearTimeout(timer); resolve(true); };
                                source.start(context.currentTime + .01);
                            });
                            if (!ended) return {status: 'failed', reason: 'output_timeout', completed,
                                audio_time: context.currentTime, audio_state: context.state,
                                wall_seconds: (performance.now() - started) / 1000,
                                sample_rate: context.sampleRate, sink: context.sinkId?.type || 'default'};
                            pending = null;
                            source.disconnect();
                            completed++;
                        }
                        return {status: 'passed', completed, audio_time: context.currentTime,
                            wall_seconds: (performance.now() - started) / 1000,
                            sample_rate: context.sampleRate, sink: context.sinkId?.type || 'default'};
                    } finally {
                        if (pending) { pending.onended = null; pending.stop(); pending.disconnect(); }
                        clock.stop(); clock.disconnect();
                        await context.close();
                    }
                }''', {'duration': args.duration, 'rate': args.rate, 'fake': args.fake_output,
                       'signal': args.signal, 'chunkMs': args.chunk_ms})
                report.update(result)
            finally:
                await browser.close()
    except BaseException as error:
        report.update(status='failed', error_type=type(error).__name__)
        raise
    finally:
        args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report))
    if report['status'] != 'passed':
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chromium', required=True)
    parser.add_argument('--duration', type=int, default=65)
    parser.add_argument('--rate', type=int, default=48000)
    parser.add_argument('--fake-output', action='store_true')
    parser.add_argument('--signal', choices=['silent', 'tone'], default='silent',
                        help='Procedural 440Hz signal at amplitude .005; no speech recording')
    parser.add_argument('--chunk-ms', type=int, default=1000,
                        help='Source length in milliseconds, 20 to 1000')
    parser.add_argument('--output', type=Path, default=Path('artifacts/browser-output-smoke.json'))
    asyncio.run(main(parser.parse_args()))
