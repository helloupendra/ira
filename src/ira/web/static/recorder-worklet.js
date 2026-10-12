// Runs on the audio thread: copies each block of microphone samples to the
// page, which joins them and encodes a 16 kHz WAV when recording stops.
class RecorderProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (channel && channel.length) {
      this.port.postMessage(channel.slice(0));
    }
    return true;
  }
}

registerProcessor("recorder", RecorderProcessor);
