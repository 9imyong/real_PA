/* Transport and scheduling tests; browser/AEC/device measurements are separate. */
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');

function browser({ handshake = true, microphone = true } = {}) {
  let time = 0;
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
    disconnect() { this.disconnected = true; },
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
    performance: { now: () => time },
    Uint8Array,
    DataView,
    atob,
    console,
  };
  vm.runInNewContext(readFileSync(join(__dirname, '../../src/real_pa/browser/realtime-client.js'), 'utf8'), sandbox);
  const states = [],
    texts = [],
    errors = [];
  const listener = new window.RealPAClient({ microphone, onState: (s) => states.push(s), onText: (t) => texts.push(t), onError: (e) => errors.push(e) });
  return { listener, sockets, tracks, navigator, states, texts, errors,
    advanceTime: milliseconds => { time += milliseconds; } };
}
const audio = (generation) => ({
  type: 'audio_chunk',
  generation_id: generation,
  data: { pcm: { $pcm16: 'AAAAAA==' }, sample_rate: 16000, chunk_id: 1 },
});
const tick = () => new Promise((resolve) => setImmediate(resolve));

test('completed and interrupted playback nodes are disconnected from the output graph', async () => {
  const { listener, sockets } = browser({ microphone: false });
  await listener.start();
  sockets[0].event(audio(1));
  const completed = [...listener._sources][0];
  completed.onended();
  assert.equal(completed.disconnected, true);
  sockets[0].event(audio(2));
  const interrupted = [...listener._sources][0];
  listener.interrupt();
  assert.equal(interrupted.stopped, true);
  assert.equal(interrupted.disconnected, true);
  assert.equal(listener._sources.size, 0);
  await listener.stop();
});

test('rapid microphone off/on rejects old input captions in the same generation', async () => {
  const { listener, sockets } = browser();
  const captions = [];
  listener.onTranscript = (text, final) => captions.push({ text, final });
  await listener.start();
  await listener.setMicrophone(false);
  await listener.setMicrophone(true);
  assert.equal(sockets[0].sent.at(-1).input_id, 2);
  for (const type of ['transcript_partial', 'transcript_final']) {
    sockets[0].event({ type, generation_id: 0, data: { text: 'old', input_id: 0 } });
  }
  assert.equal(captions.some(item => item.text === 'old'), false);
  sockets[0].event({ type: 'transcript_partial', generation_id: 0, data: { text: 'new', input_id: 2 } });
  assert.equal(captions.at(-1).text, 'new');
  await listener.stop();
});

test('injected capture device replaces native acquisition and closes its resources', async () => {
  const { listener, tracks, navigator, sockets } = browser();
  navigator.mediaDevices.getUserMedia = async () => { throw new Error('native path must not run'); };
  const media = { getTracks: () => tracks, getAudioTracks: () => tracks };
  let opened = 0, closed = 0;
  listener.captureDevice = {
    async open({ context }) { assert.equal(context.state, 'running'); opened++; return { stream: media, echoCancellation: true }; },
    close(stream) { assert.equal(stream, media); closed++; },
  };
  await listener.start();
  assert.equal(listener.isActive, true);
  assert.equal(opened, 1);
  sockets[0].event(audio(1));
  await listener.setMicrophone(false);
  assert.equal(closed, 1);
  assert.equal(tracks[0].stopped, true);
  assert.equal(listener.isActive, true);
  await listener.stop();
  assert.equal(closed, 1);
});

test('capture adapter cannot silently omit AEC and cleanup failure still stops tracks', async () => {
  const { listener, tracks } = browser({ microphone: false });
  await listener.start();
  listener.captureDevice = {
    async open() { return { stream: { getTracks: () => tracks, getAudioTracks: () => tracks } }; },
    close() { throw new Error('adapter cleanup failed'); },
  };
  await assert.rejects(listener.setMicrophone(true));
  assert.equal(tracks[0].stopped, true);
  assert.equal(listener.microphone, false);
  assert.equal(listener.isActive, true);
  await listener.stop();
});

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
  assert.deepEqual(socket.sent[0], { type: 'start', ui_started: true });
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

test('stalled output releases capture and preserves text without acknowledging unheard chunks', async () => {
  const { listener, sockets, tracks, errors, advanceTime } = browser();
  await listener.start();
  sockets[0].event(audio(1));
  const source = [...listener._sources][0];
  advanceTime(2999);
  listener._checkPlaybackClock();
  assert.equal(listener.isActive, true);
  advanceTime(1);
  listener._checkPlaybackClock();
  assert.equal(listener.isActive, true);
  assert.equal(source.stopped, true);
  assert.equal(tracks[0].stopped, true);
  assert.equal(listener._playbackWatch, null);
  assert.equal(sockets[0].sent.filter(message => message.type === 'playback_ack').length, 0);
  assert.equal(errors.length, 0);
  assert.equal(listener.microphone, false);
  sockets[0].event({ type: 'interrupted', generation_id: 2 });
  assert.equal(listener.sendText('텍스트로 계속'), true);
  assert.equal(sockets[0].sent.at(-1).output_audio, false);
  sockets[0].event({ type: 'interrupted', generation_id: 3 });
  sockets[0].event({ type: 'turn_done', generation_id: 3 });
  assert.deepEqual(sockets[0].sent.at(-1), { type: 'text_ack', generation_id: 3 });
  await listener.stop();
});

test('advancing output clock keeps playback active and interruption clears the watchdog', async () => {
  const { listener, sockets, advanceTime, errors } = browser();
  await listener.start();
  sockets[0].event(audio(1));
  for (let i = 0; i < 5; i++) {
    advanceTime(2000);
    listener._context.currentTime += 2;
    listener._checkPlaybackClock();
    assert.equal(listener.isActive, true);
  }
  assert.equal(errors.length, 0);
  listener.interrupt();
  assert.equal(listener._playbackWatch, null);
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

test('microphone permission failure restores text mode without stopping output', async () => {
  const { listener, navigator, sockets } = browser({ microphone: false });
  await listener.start();
  sockets[0].event(audio(1));
  const source = [...listener._sources][0];
  navigator.mediaDevices.getUserMedia = async () => { throw new Error('denied'); };
  await assert.rejects(listener.setMicrophone(true));
  assert.equal(listener.microphone, false);
  assert.equal(listener._media, null);
  assert.equal(listener._capture, null);
  assert.equal(listener.isActive, true);
  assert.equal(source.stopped, false);
  assert.equal(listener.sendText('텍스트 질문'), true);
  await listener.stop();
});

test('unsupported echo cancellation releases the track and restores microphone off', async () => {
  const { listener, tracks } = browser({ microphone: false });
  await listener.start();
  tracks[0].getSettings = () => ({ echoCancellation: false });
  await assert.rejects(listener.setMicrophone(true));
  assert.equal(tracks[0].stopped, true);
  assert.equal(listener.microphone, false);
  assert.equal(listener._media, null);
  assert.equal(listener.isActive, true);
  await listener.stop();
});

test('lost microphone or failed capture releases input while preserving playback and text', async () => {
  for (const kind of ['track', 'worklet']) {
    const { listener, tracks, sockets } = browser();
    const notices = [];
    listener.onNotice = text => notices.push(text);
    await listener.start();
    sockets[0].event(audio(1));
    const source = [...listener._sources][0];
    const queuedCapture = listener._capture.port.onmessage;
    const lost = kind === 'track' ? tracks[0].onended : listener._capture.onprocessorerror;
    lost();
    assert.equal(listener.microphone, false);
    assert.equal(listener._capture, null);
    assert.equal(tracks[0].stopped, true);
    assert.equal(source.stopped, false);
    assert.equal(listener.isActive, true);
    assert.equal(notices.length, 1);
    assert.equal(sockets[0].sent.at(-1).type, 'input_reset');
    const count = sockets[0].sent.length;
    queuedCapture({ data: new ArrayBuffer(3200) });
    assert.equal(sockets[0].sent.length, count);
    await listener.setMicrophone(true);
    lost();
    assert.equal(listener.microphone, true);
    assert.equal(notices.length, 1);
    assert.equal(listener.sendText('계속 질문'), true);
    await listener.stop();
  }
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

test('microphone off clears partial captions and rejects late partials without stopping playback', async () => {
  const { listener, sockets } = browser();
  const transcripts = [];
  listener.onTranscript = (text, final) => transcripts.push({ text, final });
  await listener.start();
  sockets[0].event(audio(1));
  const source = [...listener._sources][0];
  sockets[0].event({ type: 'transcript_partial', generation_id: 1, data: { text: '작성 중' } });
  await listener.setMicrophone(false);
  assert.deepEqual(transcripts.at(-1), { text: '', final: false });
  const count = transcripts.length;
  sockets[0].event({ type: 'transcript_partial', generation_id: 1, data: { text: '늦은 부분 전사' } });
  assert.equal(transcripts.length, count);
  assert.equal(source.stopped, false);
  assert.equal(listener.isActive, true);
  await listener.setMicrophone(true);
  sockets[0].event({ type: 'transcript_partial', generation_id: 1, data: { text: '새 발화' } });
  assert.deepEqual(transcripts.at(-1), { text: '새 발화', final: false });
  sockets[0].event({ type: 'transcript_partial', generation_id: 1, data: { text: '' } });
  assert.deepEqual(transcripts.at(-1), { text: '', final: false });
  await listener.stop();
});

test('text input and connection loss clear the unfinished voice caption', async () => {
  const { listener, sockets } = browser();
  const transcripts = [];
  listener.onTranscript = (text, final) => transcripts.push({ text, final });
  await listener.start();
  sockets[0].event({ type: 'transcript_partial', generation_id: 0, data: { text: '미완성 발화' } });
  listener.sendText('텍스트로 질문');
  assert.deepEqual(transcripts.at(-1), { text: '', final: false });
  sockets[0].event({ type: 'interrupted', generation_id: 1 });
  sockets[0].event({ type: 'transcript_partial', generation_id: 1, data: { text: '다음 발화' } });
  sockets[0].close();
  assert.deepEqual(transcripts.at(-1), { text: '', final: false });
  assert.equal(listener.isActive, false);
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

test('empty final transcript keeps listening without waiting for a reply', async () => {
  const { listener, sockets, tracks, states } = browser();
  await listener.start();
  sockets[0].event({ type: 'transcript_final', generation_id: 1, data: { text: '' } });
  assert.equal(states.at(-1), 'listening');
  assert.equal(listener.isActive, true);
  assert.equal(tracks[0].stopped, false);
  assert.equal(listener.sendText('다음 질문'), true);
  await listener.stop();
});
