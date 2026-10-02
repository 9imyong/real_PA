/* Standalone realtime API client. No model engine or business SDK dependency. */
class RealPAClient {
  constructor({
    path = '/v1/realtime',
    capturePath = '/capture.js',
    token = '',
    microphone = false,
    outputSampleRate,
    onTranscript = () => {},
    onState = () => {},
    onText = () => {},
    onResult = () => {},
    onError = () => {},
    onNotice = () => {},
  } = {}) {
    this.path = path;
    this.token = token;
    this.microphone = microphone;
    this.outputSampleRate = outputSampleRate;
    this.onTranscript = onTranscript;
    this.capturePath = capturePath;
    this.onState = onState;
    this.onText = onText;
    this.onResult = onResult;
    this.onError = onError;
    this.onNotice = onNotice;
    this._enabled = true;
    this._active = false;
    this._epoch = 0;
    this._microphoneEpoch = 0;
    this._generation = -1;
    this._sources = new Set();
    this._playbackQueue = [];
    this._nextStart = 0;
    this._awaitingInterrupt = false;
    this._turnDone = false;
    this._starting = null;
    this._cancelStart = null;
    this._socket = this._context = this._media = this._capture = this._input = null;
    this._clock = null;
    window.addEventListener('pagehide', () => this.stop());
  }
  get isActive() {
    return this._active;
  }
  get isEnabled() {
    return this._enabled;
  }
  get isListening() {
    return this._active;
  }

  async start() {
    if (this._starting) await this._starting;
    if (this._active || !this._enabled) return;
    const epoch = ++this._epoch;
    this._starting = this._start(epoch).catch(async () => {
      if (epoch !== this._epoch) return;
      await this.stop();
      this.onError('음성 연결을 확인하고 다시 시작해 주세요.');
    });
    await this._starting;
    this._starting = null;
  }

  async _start(epoch) {
    const context = new AudioContext({ latencyHint: 'interactive',
      ...(this.outputSampleRate ? { sampleRate: this.outputSampleRate } : {}) });
    this._context = context;
    await context.resume();
    if (epoch !== this._epoch) return;
    this._clock = context.createConstantSource();
    this._clock.offset.value = 0;
    this._clock.connect(context.destination);
    this._clock.start();
    if (this.microphone) await this._openMicrophone(context, epoch);
    if (epoch !== this._epoch) return;
    const socket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}${this.path}`);
    this._socket = socket;
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('connection timeout')), 30000);
      const fail = () => {
        clearTimeout(timer);
        reject(new Error('connection closed'));
      };
      this._cancelStart = fail;
      socket.onopen = () => socket.send(JSON.stringify({ type: 'start', token: this.token, ui_started: true }));
      socket.onerror = fail;
      socket.onclose = fail;
      socket.onmessage = (event) => {
        if (epoch !== this._epoch) return;
        try {
          const message = JSON.parse(event.data);
          if (message.type === 'session_started') {
            clearTimeout(timer);
            this._cancelStart = null;
            this._generation = -1;
            this._active = true;
            if (this._media) this._attachCapture(epoch);
            socket.onclose = () => {
              if (epoch !== this._epoch) return;
              this.stop();
              this.onError('음성 연결이 종료됐어요. 다시 시작해 주세요.');
            };
            socket.onerror = () => socket.close();
            this.onState('idle');
            resolve();
          } else if (message.type === 'error' && !this._active) {
            fail();
          } else {
            this._receive(message);
          }
        } catch (_) {
          fail();
          this.stop();
          this.onError('음성 응답을 처리하지 못했어요. 다시 시작해 주세요.');
        }
      };
    });
  }

  async _openMicrophone(context, epoch) {
    const microphoneEpoch = this._microphoneEpoch;
    const current = () => epoch === this._epoch && microphoneEpoch === this._microphoneEpoch && this.microphone;
    await context.audioWorklet.addModule(this.capturePath);
    if (!current()) return;
    let media;
    try {
      media = await navigator.mediaDevices.getUserMedia({ audio: {
        channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: false,
      } });
    } catch (error) {
      if (current()) throw error;
      return;
    }
    if (!current()) {
      media.getTracks().forEach(track => track.stop());
      return;
    }
    if (media.getAudioTracks()[0].getSettings().echoCancellation !== true) {
      media.getTracks().forEach(track => track.stop());
      throw new Error('반향 제거를 지원하는 브라우저가 필요합니다.');
    }
    this._media = media;
  }

  _attachCapture(epoch) {
    const microphoneEpoch = this._microphoneEpoch;
    const context = this._context;
    this._input = context.createMediaStreamSource(this._media);
    this._capture = new AudioWorkletNode(context, 'real-pa-capture');
    const mute = context.createGain();
    mute.gain.value = 0;
    this._input.connect(this._capture).connect(mute).connect(context.destination);
    this._capture.port.onmessage = ({ data }) => {
      if (epoch !== this._epoch || microphoneEpoch !== this._microphoneEpoch || !this.microphone || this._socket?.readyState !== WebSocket.OPEN) return;
      if (this._socket.bufferedAmount > 32000) {
        this.stop();
        this.onError('음성 전송이 지연되고 있어요. 다시 시작해 주세요.');
      } else this._socket.send(data);
    };
  }

  async setMicrophone(enabled) {
    const microphoneEpoch = ++this._microphoneEpoch;
    this.microphone = !!enabled;
    if (!this._active) return;
    this._send({ type: 'input_reset' });
    this._capture?.disconnect();
    this._input?.disconnect();
    this._media?.getTracks().forEach(track => track.stop());
    this._capture = this._input = this._media = null;
    if (this.microphone) {
      const epoch = this._epoch;
      await this._openMicrophone(this._context, epoch);
      if (this._active && epoch === this._epoch && microphoneEpoch === this._microphoneEpoch && this._media) this._attachCapture(epoch);
    }
  }

  _receive(message) {
    if (message.type === 'interrupted') {
      if (!Number.isInteger(message.generation_id) || message.generation_id < this._generation) return;
      this._generation = message.generation_id;
      this._awaitingInterrupt = false;
      this._turnDone = false;
      this._stopAudio();
      this.onText('', true);
      this.onState('listening');
      return;
    }
    if (message.type === 'error') {
      if (Number.isInteger(message.generation_id) && message.generation_id < this._generation) return;
      if (message.data?.code === 'turn_failed') {
        this.interrupt();
        this.onNotice('답변을 완료하지 못했어요. 다시 말씀하거나 메시지를 보내 주세요.');
        this.onState('listening');
        return;
      }
      this.stop();
      this.onError('음성 처리에 실패했어요. 다시 시작해 주세요.');
      return;
    }
    if (this._awaitingInterrupt || !Number.isInteger(message.generation_id) || message.generation_id < this._generation) return;
    if (message.type === 'request_started') {
      this.lastRequestId = message.data.request_id;
      this.onResult(null);
    } else if (message.type === 'input_rejected') {
      this.onTranscript('', false);
      this.onNotice('말씀이 너무 길어요. 잠시 멈춘 뒤 나누어 말씀해 주세요.');
      this.onState('listening');
    } else if (message.type === 'tool_started') this.onState('thinking');
    else if (message.type === 'tool_result') this.onResult(message.data.result.ui);
    else if (message.type === 'transcript_partial' && message.data.text) {
      this.onTranscript(message.data.text, false);
      this.onState('listening');
    }
    else if (message.type === 'transcript_final') {
      this.onTranscript(message.data.text, true);
      this.onState(message.data.control === 'interrupt' ? 'listening' : 'thinking');
    }
    else if (message.type === 'text_delta') this.onText(message.data.text, false);
    else if (message.type === 'audio_chunk') this._play(message);
    else if (message.type === 'turn_done') {
      this._turnDone = true;
      if (!this._sources.size) this.onState('idle');
    }
  }

  _play(message) {
    if (message.generation_id > this._generation) {
      this._stopAudio();
      this._generation = message.generation_id;
    }
    const binary = atob(message.data.pcm.$pcm16);
    const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
    if (bytes.length % 2 || !Number.isInteger(message.data.sample_rate) || message.data.sample_rate <= 0) throw new Error('invalid PCM');
    const view = new DataView(bytes.buffer);
    const buffer = this._context.createBuffer(1, bytes.length / 2, message.data.sample_rate);
    const channel = buffer.getChannelData(0);
    for (let i = 0; i < channel.length; i++) channel[i] = view.getInt16(i * 2, true) / 32768;
    const source = this._context.createBufferSource();
    source.buffer = buffer;
    source.connect(this._context.destination);
    this._sources.add(source);
    const generation = this._generation;
    const playback = { generation, chunk: message.data.chunk_id, done: false };
    this._playbackQueue.push(playback);
    source.onended = () => {
      this._sources.delete(source);
      if (generation !== this._generation || this._awaitingInterrupt) return;
      playback.done = true;
      while (this._playbackQueue[0]?.done) {
        const completed = this._playbackQueue.shift();
        this._send({ type: 'playback_ack', generation_id: completed.generation, chunk_id: completed.chunk });
      }
      if (!this._sources.size) this.onState(this._turnDone ? 'idle' : 'thinking');
    };
    const start = Math.max(this._context.currentTime + 0.01, this._nextStart);
    source.start(start);
    this._nextStart = start + buffer.duration;
    this.onState('speaking');
  }

  _send(message) {
    if (this._socket?.readyState !== WebSocket.OPEN) return false;
    this._socket.send(JSON.stringify(message));
    return true;
  }
  _stopAudio() {
    for (const source of this._sources) {
      source.onended = null;
      source.stop();
    }
    this._sources.clear();
    this._playbackQueue.length = 0;
    this._nextStart = this._context?.currentTime || 0;
  }
  interrupt() {
    this._awaitingInterrupt = true;
    this._stopAudio();
    this._send({ type: 'interrupt' });
  }
  async startListening() {
    await this.start();
    if (this._active) {
      this.interrupt();
      this._send({ type: 'listen' });
    }
  }
  stopListening() {
    this.interrupt();
  }
  sendText(text) {
    this.interrupt();
    return this._send({ type: 'text', text });
  }
  setEnabled(enabled) {
    this._enabled = !!enabled;
    if (this._enabled) this.start();
    else this.stop();
  }
  async stop() {
    this._epoch++;
    this._microphoneEpoch++;
    this._cancelStart?.();
    this._cancelStart = null;
    this._active = false;
    this._clock?.stop();
    this._clock?.disconnect();
    this._clock = null;
    this._stopAudio();
    this._capture?.disconnect();
    this._input?.disconnect();
    this._media?.getTracks().forEach((track) => track.stop());
    const context = this._context;
    if (this._socket) {
      this._socket.onclose = null;
      this._socket.close();
    }
    this._socket = this._context = this._media = this._capture = this._input = null;
    if (context && context.state !== 'closed') await context.close();
    this.onState('idle');
  }
}
window.RealPAClient = RealPAClient;
