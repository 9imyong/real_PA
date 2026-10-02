const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');

for (const rate of [16000, 44100, 48000]) {
  test(`${rate}Hz capture produces three complete 100ms PCM16 frames across render quanta`, () => {
    const frames = [];
    let Processor;
    const sandbox = {
      sampleRate: rate,
      AudioWorkletProcessor: class { constructor() { this.port = { postMessage: buffer => frames.push(buffer) }; } },
      registerProcessor: (_, value) => { Processor = value; },
    };
    vm.runInNewContext(readFileSync(join(__dirname, '../../src/real_pa/browser/capture.js'), 'utf8'), sandbox);
    const processor = new Processor();
    for (let offset = 0; offset < rate * .3; offset += 128) {
      const input = new Float32Array(Math.min(128, rate * .3 - offset)).fill(.5);
      assert.equal(processor.process([[input]]), true);
    }
    assert.equal(frames.length, 3);
    for (const frame of frames) {
      assert.equal(frame.byteLength, 3200);
      assert.ok(Array.from(new Int16Array(frame)).every(sample => Math.abs(sample - 16384) <= 1));
    }
    assert.equal(processor.index, 0);
  });
}
