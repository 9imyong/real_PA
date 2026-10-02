class Capture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.frame = new Int16Array(1600);
    this.index = 0;
    this.ratio = sampleRate / 16000;
    this.weight = 0;
    this.sum = 0;
  }
  process(inputs) {
    const channel = inputs[0]?.[0];
    if (channel) {
      for (const value of channel) {
        // Area-average resampling, with fractional weights retained across
        // render quanta. Output is always 100ms PCM16 at 16kHz.
        let remaining = 1;
        while (remaining > 1e-9) {
          const part = Math.min(remaining, this.ratio - this.weight);
          this.sum += value * part;
          this.weight += part;
          remaining -= part;
          if (this.weight >= this.ratio - 1e-9) {
            this.frame[this.index++] = Math.round(Math.max(-1, Math.min(1, this.sum / this.ratio)) * 32767);
            this.weight = this.sum = 0;
            if (this.index === 1600) {
              this.port.postMessage(this.frame.buffer, [this.frame.buffer]);
              this.frame = new Int16Array(1600);
              this.index = 0;
            }
          }
        }
      }
    }
    return true;
  }
}
registerProcessor('real-pa-capture', Capture);
