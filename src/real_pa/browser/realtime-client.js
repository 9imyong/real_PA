/* Standalone realtime API client. No model engine or business SDK dependency. */
class BrowserCaptureDevice {
  async open({ context }) {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: {
      channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: false,
    } });
    if (stream.getAudioTracks()[0]?.getSettings().echoCancellation !== true) {
      stream.getTracks().forEach(track => track.stop());
      throw new Error('반향 제거를 지원하는 브라우저가 필요합니다.');
    }
    return { stream, echoCancellation: true };
  }
  close(stream) {
    stream.getTracks().forEach(track => track.stop());
  }
}

class RealPAClient {
  constructor({
    path = '/v1/realtime',
    capturePath = '/capture.js',
    captureDevice = new BrowserCaptureDevice(),
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
    this.captureDevice = captureDevice;
    this.onState = onState;
    this.onText = onText;
    this.onResult = onResult;
    this.onError = onError;
    this.onNotice = onNotice;
    this._enabled = true;
    this._active = false;
    this._epoch = 0;
    this._microphoneEpoch = 0;
    this._inputId = 0;
    this._audioOutput = true;
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
    this._playbackWatch = null;
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
    this._inputId = 0;
    this._audioOutput = true;
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
            socket.onclose = (event) => {
              if (epoch !== this._epoch) return;
              this.stop();
              this.onError(event?.code === 4000
                ? '입출력이 없어 대화를 종료했어요. 다시 시작해 주세요.'
                : '음성 연결이 종료됐어요. 다시 시작해 주세요.');
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
    let capture;
    try {
      capture = await this.captureDevice.open({ context });
    } catch (error) {
      if (current()) throw error;
      return;
    }
    const media = capture.stream;
    if (!current()) {
      this._releaseMedia(media);
      return;
    }
    if (capture.echoCancellation !== true || !media.getAudioTracks().length) {
      this._releaseMedia(media);
      throw new Error('반향 제거를 지원하는 브라우저가 필요합니다.');
    }
    this._media = media;
  }

  _releaseMedia(media) {
    if (!media) return;
    try { this.captureDevice.close(media); }
    catch (_) { this.onNotice('음성 입력 장치 정리 중 오류가 발생했어요.'); }
    finally { media.getTracks().forEach(track => track.stop()); }
  }

  _attachCapture(epoch) {
    const microphoneEpoch = this._microphoneEpoch;
    const context = this._context;
    this._input = context.createMediaStreamSource(this._media);
    this._capture = new AudioWorkletNode(context, 'real-pa-capture');
    const inputLost = () => {
      if (!this._active || epoch !== this._epoch || microphoneEpoch !== this._microphoneEpoch) return;
      this.setMicrophone(false);
      this.onNotice('음성 입력이 중단됐어요. 마이크를 다시 켜거나 텍스트로 대화해 주세요.');
      this.onState(this._sources.size ? 'speaking' : this._turnDone ? 'idle' : 'listening');
    };
    this._media.getAudioTracks().forEach(track => { track.onended = inputLost; });
    this._capture.onprocessorerror = inputLost;
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
    if (enabled && !this._audioOutput) throw new Error('output device requires reconnect');
    const microphoneEpoch = ++this._microphoneEpoch;
    this.microphone = !!enabled;
    this.onTranscript('', false);
    if (!this._active) return;
    this._send({ type: 'input_reset', input_id: ++this._inputId });
    this._capture?.disconnect();
    this._input?.disconnect();
    this._releaseMedia(this._media);
    this._capture = this._input = this._media = null;
    if (this.microphone) {
      const epoch = this._epoch;
      try {
        await this._openMicrophone(this._context, epoch);
        if (this._active && epoch === this._epoch && microphoneEpoch === this._microphoneEpoch && this._media) this._attachCapture(epoch);
      } catch (error) {
        if (epoch !== this._epoch || microphoneEpoch !== this._microphoneEpoch) return;
        this.microphone = false;
        this._microphoneEpoch++;
        this._capture?.disconnect();
        this._input?.disconnect();
        this._releaseMedia(this._media);
        this._capture = this._input = this._media = null;
        throw error;
      }
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
    if (['transcript_partial', 'transcript_final'].includes(message.type) &&
        message.data.input_id !== undefined && message.data.input_id !== this._inputId) return;
    if (message.type === 'request_started') {
      this.lastRequestId = message.data.request_id;
      this.onResult(null);
    } else if (message.type === 'input_rejected') {
      this.onTranscript('', false);
      this.onNotice(message.data.code === 'context_capacity_exceeded'
        ? '입력 길이 한도를 넘었어요. 더 짧게 입력하거나 새 대화를 시작해 주세요.'
        : '말씀이 너무 길어요. 잠시 멈춘 뒤 나누어 말씀해 주세요.');
      this.onState('listening');
    } else if (message.type === 'context_trimmed') {
      this.onNotice('대화가 길어져 오래된 내용 일부를 제외했어요. 필요한 내용은 다시 알려 주세요.');
    } else if (message.type === 'tool_started') this.onState('thinking');
    else if (message.type === 'tool_result') this.onResult(message.data.result.ui);
    else if (message.type === 'transcript_partial' && this.microphone) {
      this.onTranscript(message.data.text, false);
      if (message.data.text) this.onState('listening');
    }
    else if (message.type === 'transcript_final') {
      this.onTranscript(message.data.text, true);
      this.onState(message.data.control === 'interrupt' ? 'listening' : 'thinking');
    }
    else if (message.type === 'text_delta') this.onText(message.data.text, false);
    else if (message.type === 'audio_chunk') this._play(message);
    else if (message.type === 'turn_done') {
      this._turnDone = true;
      if (!this._audioOutput) this._send({ type: 'text_ack', generation_id: message.generation_id });
      if (!this._sources.size) this.onState('idle');
    }
  }

  _play(message) {
    if (!this._audioOutput) return;
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
      source.disconnect();
      this._sources.delete(source);
      if (!this._sources.size) this._clearPlaybackWatch();
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
    if (!this._playbackWatch) {
      this._playbackWatch = { audioTime: this._context.currentTime, progressAt: performance.now(), timer: null };
      this._schedulePlaybackWatch();
    }
    this.onState('speaking');
  }

  _schedulePlaybackWatch() {
    this._playbackWatch.timer = setTimeout(() => {
      this._checkPlaybackClock();
      if (this._playbackWatch) this._schedulePlaybackWatch();
    }, 250);
  }

  _checkPlaybackClock() {
    const watch = this._playbackWatch;
    if (!watch) return;
    if (!this._sources.size || !this._context) {
      this._clearPlaybackWatch();
      return;
    }
    const now = performance.now();
    if (this._context.currentTime > watch.audioTime) {
      watch.audioTime = this._context.currentTime;
      watch.progressAt = now;
    } else if (now - watch.progressAt >= 3000) {
      // Never acknowledge queued audio when the output clock has stopped.
      this._audioOutput = false;
      this.interrupt();
      this.setMicrophone(false);
      this._clock?.stop();
      this._clock?.disconnect();
      this._clock = null;
      this.onNotice('오디오 재생이 멈춰 음성 입출력을 껐어요. 텍스트로 계속 대화하거나 출력 장치를 확인한 뒤 다시 시작해 주세요.');
      this.onState('idle');
    }
  }

  _clearPlaybackWatch() {
    if (this._playbackWatch) clearTimeout(this._playbackWatch.timer);
    this._playbackWatch = null;
  }

  _send(message) {
    if (this._socket?.readyState !== WebSocket.OPEN) return false;
    this._socket.send(JSON.stringify(message));
    return true;
  }
  _stopAudio() {
    this._clearPlaybackWatch();
    for (const source of this._sources) {
      source.onended = null;
      source.stop();
      source.disconnect();
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
    this.onTranscript('', false);
    this.interrupt();
    return this._send({ type: 'text', text, output_audio: this._audioOutput });
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
    this.onTranscript('', false);
    this._clock?.stop();
    this._clock?.disconnect();
    this._clock = null;
    this._stopAudio();
    this._capture?.disconnect();
    this._input?.disconnect();
    this._releaseMedia(this._media);
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
