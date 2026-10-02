/* Transport and scheduling tests; browser/AEC/device measurements are separate. */
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');

function browser({ handshake = true, microphone = true } = {}) {
  const sockets = [];
  const tracks = [
    {
      stopped: false,
      stop() {
        this.stopped = true;
      },
      getSettings() {
        return { echoCancellation: true };
      },
    },
  ];
  const media = { getTracks: () => tracks, getAudioTracks: () => tracks };
  const node = () => ({
    disconnect() {},
    connect() {
      return this;
    },
  });
  class Context {
    constructor() {
      this.sampleRate = 16000;
      this.currentTime = 0;
      this.state = 'running';
      this.destination = {};
      this.audioWorklet = { addModule: async () => {} };
    }
    async resume() {}
    async close() {
      this.state = 'closed';
    }
    createMediaStreamSource() {
      return node();
    }
    createGain() {
      return { ...node(), gain: { value: 1 } };
    }
    createConstantSource() {
      return { ...node(), offset: { value: 1 }, start() {}, stop() { this.stopped = true; } };
    }
    createBuffer(channels, length, rate) {
      return { duration: length / rate, getChannelData: () => new Float32Array(length) };
    }
    createBufferSource() {
      return {
        ...node(),
        started: false,
        stopped: false,
        start() {
          this.started = true;
        },
        stop() {
          this.stopped = true;
        },
      };
    }
  }
  class Socket {
    static OPEN = 1;
    constructor() {
      this.readyState = 1;
      this.bufferedAmount = 0;
      this.sent = [];
      sockets.push(this);
      queueMicrotask(() => this.onopen?.());
    }
    send(raw) {
      this.sent.push(typeof raw === 'string' ? JSON.parse(raw) : raw);
      if (handshake && typeof raw === 'string' && JSON.parse(raw).type === 'start') {
        queueMicrotask(() => this.event({ type: 'session_started', session_id: 'server-session' }));
      }
    }
    event(data) {
      this.onmessage?.({ data: JSON.stringify(data) });
    }
    close() {
      this.readyState = 3;
      this.onclose?.();
    }
  }
  class Worklet {
    constructor() {
      Object.assign(this, node());
      this.port = {};
    }
  }
  const window = { addEventListener() {} };
  const navigator = { mediaDevices: { getUserMedia: async () => media } };
  const sandbox = {
    window,
    navigator,
    location: { host: 'robot.test', protocol: 'https:' },
    AudioContext: Context,
    AudioWorkletNode: Worklet,
    WebSocket: Socket,
    setTimeout,
    clearTimeout,
    Uint8Array,
    DataView,
    atob,
    console,
  };
  vm.runInNewContext(readFileSync(join(__dirname, '../../src/real_pa/browser/realtime-client.js'), 'utf8'), sandbox);
  const states = [],
    texts = [],
    errors = [];
  const listener = new window.RealPAClient({ token: 'unit-browser-credential', microphone, onState: (s) => states.push(s), onText: (t) => texts.push(t), onError: (e) => errors.push(e) });
  return { listener, sockets, tracks, navigator, states, texts, errors };
}
const audio = (generation) => ({
  type: 'audio_chunk',
  generation_id: generation,
  data: { pcm: { $pcm16: 'AAAAAA==' }, sample_rate: 16000, chunk_id: 1 },
});
const tick = () => new Promise((resolve) => setImmediate(resolve));

test('silent session clock is released on disconnect and recreated on reconnect', async () => {
  const { listener } = browser({ microphone: false });
  await listener.start();
  const clock = listener._clock;
  assert.equal(clock.offset.value, 0);
  await listener.stop();
  assert.equal(clock.stopped, true);
  assert.equal(listener._clock, null);
  await listener.start();
  assert.notEqual(listener._clock, clock);
  await listener.stop();
});

test('capture remains active during output and acknowledges completed playback', async () => {
  const { listener, sockets } = browser();
  await listener.start();
  const socket = sockets[0];
  assert.deepEqual(socket.sent[0], { type: 'start', token: 'unit-browser-credential', ui_started: true });
  socket.event({ type: 'interrupted', generation_id: 1 });
  socket.event(audio(1));
  const source = [...listener._sources][0];
  assert.equal(source.started, true);
  const frame = new ArrayBuffer(3200);
  listener._capture.port.onmessage({ data: frame });
  assert.equal(socket.sent.at(-1), frame);
  source.onended();
  assert.deepEqual(socket.sent.at(-1), { type: 'playback_ack', generation_id: 1, chunk_id: 1 });
  await listener.stop();
});

test('interruption immediately blocks late audio and stale acknowledgements', async () => {
  const { listener, sockets } = browser();
  await listener.start();
  const socket = sockets[0];
  socket.event(audio(1));
  const source = [...listener._sources][0];
  const lateEnd = source.onended;
  listener.interrupt();
  assert.equal(source.stopped, true);
  socket.event(audio(1));
  lateEnd();
  assert.equal(listener._sources.size, 0);
  assert.equal(socket.sent.filter((m) => m.type === 'playback_ack').length, 0);
  socket.event({ type: 'interrupted', generation_id: 2 });
  socket.event(audio(1));
  assert.equal(listener._sources.size, 0);
  socket.event(audio(2));
  assert.equal(listener._sources.size, 1);
  await listener.stop();
});

test('manual stop settles pending handshake and frees the microphone', async () => {
  const { listener, sockets, tracks } = browser({ handshake: false });
  const starting = listener.start();
  await tick();
  assert.equal(sockets.length, 1);
  await listener.stop();
  await starting;
  assert.equal(tracks[0].stopped, true);
  assert.equal(listener.isActive, false);
});

test('late microphone permission result is cleaned up after stop', async () => {
  const { listener, navigator, tracks, sockets } = browser();
  let grant;
  navigator.mediaDevices.getUserMedia = () =>
    new Promise((resolve) => {
      grant = resolve;
    });
  const starting = listener.start();
  await tick();
  await listener.stop();
  grant({ getTracks: () => tracks, getAudioTracks: () => tracks });
  await starting;
  assert.equal(tracks[0].stopped, true);
  assert.equal(sockets.length, 0);
});

test('input backpressure closes capture instead of silently losing a turn', async () => {
  const { listener, sockets, tracks, errors } = browser();
  await listener.start();
  sockets[0].bufferedAmount = 33000;
  listener._capture.port.onmessage({ data: new ArrayBuffer(3200) });
  await tick();
  assert.equal(tracks[0].stopped, true);
  assert.equal(listener.isActive, false);
  assert.equal(errors.length, 1);
});

test('tool results update UI only for the current generation', async () => {
  const { listener, sockets } = browser();
  const results = [];
  listener.onResult = (result) => results.push(result);
  await listener.start();
  sockets[0].event({ type: 'interrupted', generation_id: 2 });
  const result = (generation) => ({
    type: 'tool_result',
    generation_id: generation,
    data: { result: { ui: { intent: 'reminder', data: { id: 1 } } } },
  });
  sockets[0].event(result(1));
  sockets[0].event(result(undefined));
  assert.equal(results.length, 0);
  sockets[0].event(result(2));
  assert.equal(results.length, 1);
  assert.equal(results[0].intent, 'reminder');
  await listener.stop();
});

test('completed playback reveals the panel without stopping continuous capture', async () => {
  const { listener, sockets, states } = browser();
  await listener.start();
  const socket = sockets[0];
  socket.event({ type: 'interrupted', generation_id: 1 });
  socket.event(audio(1));
  socket.event({ type: 'turn_done', generation_id: 1 });
  assert.equal(states.at(-1), 'speaking');
  [...listener._sources][0].onended();
  assert.equal(states.at(-1), 'idle');
  socket.event({ type: 'transcript_partial', generation_id: 1, data: { text: '' } });
  assert.equal(states.at(-1), 'idle');
  const frame = new ArrayBuffer(3200);
  listener._capture.port.onmessage({ data: frame });
  assert.equal(socket.sent.at(-1), frame);
  await listener.stop();
});

test('text conversation connects without microphone permission', async () => {
  const { listener, navigator, sockets } = browser({ microphone: false });
  navigator.mediaDevices.getUserMedia = () => { assert.fail('text mode must not request a microphone'); };
  await listener.start();
  assert.equal(listener.isActive, true);
  assert.equal(listener._media, null);
  assert.equal(listener.sendText('안녕하세요'), true);
  assert.equal(sockets[0].sent.at(-1).type, 'text');
  await listener.stop();
});

test('microphone can be toggled without disconnecting text or playback', async () => {
  const { listener, sockets, tracks } = browser({ microphone: false });
  await listener.start();
  await listener.setMicrophone(true);
  assert.ok(listener._capture);
  await listener.setMicrophone(false);
  assert.equal(tracks[0].stopped, true);
  assert.equal(listener._capture, null);
  assert.equal(sockets[0].readyState, 1);
  assert.equal(listener.sendText('계속 대화'), true);
  await listener.stop();
});

test('turning microphone off discards late permission and queued capture', async () => {
  const { listener, navigator, tracks, sockets } = browser({ microphone: false });
  await listener.start();
  let grant;
  navigator.mediaDevices.getUserMedia = () => new Promise(resolve => { grant = resolve; });
  const enabling = listener.setMicrophone(true);
  await tick();
  await listener.setMicrophone(false);
  grant({ getTracks: () => tracks, getAudioTracks: () => tracks });
  await enabling;
  assert.equal(tracks[0].stopped, true);
  assert.equal(listener._media, null);
  assert.equal(listener._capture, null);
  assert.equal(listener.isActive, true);
  await listener.stop();
});

test('disabled capture cannot send a queued frame after microphone off', async () => {
  const { listener, sockets } = browser();
  await listener.start();
  const queued = listener._capture.port.onmessage;
  await listener.setMicrophone(false);
  const count = sockets[0].sent.length;
  queued({ data: new ArrayBuffer(3200) });
  assert.equal(sockets[0].sent.length, count);
  await listener.stop();
});

test('out-of-order playback callbacks acknowledge chunks in transport order', async () => {
  const { listener, sockets } = browser({ microphone: false });
  await listener.start();
  const first = audio(1), second = audio(1);
  second.data.chunk_id = 2;
  sockets[0].event(first);
  sockets[0].event(second);
  const sources = [...listener._sources];
  sources[1].onended();
  assert.equal(sockets[0].sent.filter(message => message.type === 'playback_ack').length, 0);
  sources[0].onended();
  assert.deepEqual(sockets[0].sent.filter(message => message.type === 'playback_ack').map(message => message.chunk_id), [1, 2]);
  await listener.stop();
});

test('a failed answer keeps capture and the connection available for the next request', async () => {
  const { listener, sockets, tracks, errors } = browser();
  const notices = [];
  listener.onNotice = notice => notices.push(notice);
  await listener.start();
  sockets[0].event(audio(1));
  const source = [...listener._sources][0];
  sockets[0].event({ type: 'error', generation_id: 1, data: { code: 'turn_failed' } });
  assert.equal(source.stopped, true);
  assert.equal(listener.isActive, true);
  assert.equal(tracks[0].stopped, false);
  assert.equal(errors.length, 0);
  assert.equal(notices.length, 1);
  assert.equal(listener.sendText('다시 인사해 줘'), true);
  sockets[0].event({ type: 'interrupted', generation_id: 2 });
  sockets[0].event(audio(2));
  assert.equal(listener._sources.size, 1);
  const current = [...listener._sources][0];
  sockets[0].event({ type: 'error', generation_id: 1, data: { code: 'turn_failed' } });
  assert.equal(current.stopped, false);
  assert.equal(notices.length, 1);
  await listener.stop();
});

test('an oversized spoken input keeps capture and accepts the next request', async () => {
  const { listener, sockets, tracks, errors } = browser();
  const notices = [];
  listener.onNotice = notice => notices.push(notice);
  await listener.start();
  sockets[0].event({ type: 'interrupted', generation_id: 1 });
  sockets[0].event({ type: 'input_rejected', generation_id: 1, data: { code: 'transcript_too_long' } });
  assert.equal(listener.isActive, true);
  assert.equal(tracks[0].stopped, false);
  assert.equal(errors.length, 0);
  assert.equal(notices.length, 1);
  sockets[0].event({ type: 'input_rejected', generation_id: 0, data: { code: 'transcript_too_long' } });
  assert.equal(notices.length, 1);
  assert.equal(listener.sendText('다시 질문'), true);
  await listener.stop();
});

test('spoken interruption finalizes its caption and stays listening', async () => {
  const { listener, sockets, tracks, states } = browser();
  const transcripts = [];
  listener.onTranscript = (text, final) => transcripts.push({ text, final });
  await listener.start();
  sockets[0].event(audio(1));
  const source = [...listener._sources][0];
  sockets[0].event({ type: 'interrupted', generation_id: 2 });
  sockets[0].event({ type: 'transcript_final', generation_id: 2, data: { text: '그만', control: 'interrupt' } });
  assert.equal(source.stopped, true);
  assert.deepEqual(transcripts, [{ text: '그만', final: true }]);
  assert.equal(states.at(-1), 'listening');
  assert.equal(listener.isActive, true);
  assert.equal(tracks[0].stopped, false);
  sockets[0].event({ type: 'transcript_final', generation_id: 1, data: { text: '이전 발화' } });
  assert.equal(transcripts.length, 1);
  assert.equal(listener.sendText('다음 질문'), true);
  await listener.stop();
});
