// A live call with Ira: talk and listen like a phone call, no button between turns.
// The protocol is docs/realtime.md (version 1). Loaded after app.js, whose helpers
// ($, state, addTurn, remember, setStatus, announce, actionCard, rms, scrollDown) it uses.
// The voice detector runs here, on the device: audio leaves only while you speak.
"use strict";

const IraLive = (() => {
  const RATE = 16000;
  const FRAME_MS = 40; // audio goes up in 40 ms frames
  const START_MS = 120; // this much speech starts a turn
  const BARGE_MS = 250; // while Ira speaks, a little more: its own voice is not you
  const HANGOVER_MS = 600; // this much quiet ends a turn
  const PREROLL_MS = 300; // and the 300 ms before speech goes too
  const MIN_LEVEL = 0.012;

  let call = null;

  function available() {
    return Boolean(
      state.info &&
        state.info.live &&
        window.isSecureContext &&
        window.AudioWorkletNode &&
        navigator.mediaDevices &&
        window.WebSocket,
    );
  }

  function label(text) {
    $("#call-label").textContent = text;
  }

  function send(message) {
    if (call && call.ws.readyState === WebSocket.OPEN) call.ws.send(JSON.stringify(message));
  }

  // 16 kHz 16-bit PCM from one block of the microphone's samples.
  function pcm16(samples, from) {
    const ratio = from / RATE;
    const out = new Int16Array(Math.floor(samples.length / ratio));
    for (let i = 0; i < out.length; i++) {
      const start = Math.floor(i * ratio);
      const end = Math.min(samples.length, Math.floor((i + 1) * ratio));
      let sum = 0;
      for (let j = start; j < end; j++) sum += samples[j];
      const value = end > start ? sum / (end - start) : samples[start] || 0;
      const clipped = Math.max(-1, Math.min(1, value));
      out[i] = clipped < 0 ? clipped * 0x8000 : clipped * 0x7fff;
    }
    return out;
  }

  function join(parts) {
    const length = parts.reduce((sum, p) => sum + p.length, 0);
    const out = new Int16Array(length);
    let offset = 0;
    for (const p of parts) {
      out.set(p, offset);
      offset += p.length;
    }
    return out;
  }

  async function start() {
    if (call || !available()) return;
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    } catch (error) {
      return setStatus(micMessage(error));
    }
    const context = new AudioContext();
    await context.audioWorklet.addModule("/recorder-worklet.js");
    const source = context.createMediaStreamSource(stream);
    const node = new AudioWorkletNode(context, "recorder");
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${scheme}://${location.host}/v1/voice/live`);
    ws.binaryType = "arraybuffer";
    call = {
      ws,
      stream,
      context,
      node,
      level: 0,
      floor: MIN_LEVEL / 2,
      voiced: 0,
      speaking: false,
      lastVoiced: 0,
      frame: [],
      frameSamples: 0,
      preroll: [],
      prerollSamples: 0,
      sources: [],
      nextStart: 0,
      playingTurn: null,
      reported: new Set(),
      header: null,
      decoding: Promise.resolve(),
      stopped: new Set(), // turns whose audio was cut off
      turns: new Map(), // turn number -> its Ira bubble
      ready: false,
    };
    ws.addEventListener("open", () =>
      send({ type: "start", protocol: 1, client: "ira-pwa/0.2", conversation_id: state.conversationId || undefined }),
    );
    ws.addEventListener("message", (event) => onMessage(event.data));
    ws.addEventListener("close", () => stop());
    node.port.onmessage = (event) => onAudio(event.data);
    source.connect(node);
    $("#call-bar").hidden = false;
    $("#composer").classList.add("in-call");
    $("#call").setAttribute("aria-pressed", "true");
    label("Connecting…");
    animateMeter(
      () => (call ? call.level * 2 : 0),
      () => call !== null,
    );
  }

  function stop(message) {
    if (!call) return;
    const ending = call;
    call = null;
    try {
      if (ending.ws.readyState === WebSocket.OPEN) ending.ws.send(JSON.stringify({ type: "bye" }));
      ending.ws.close();
    } catch {
      /* already closed */
    }
    for (const s of ending.sources) {
      try {
        s.stop();
      } catch {
        /* finished */
      }
    }
    ending.node.disconnect();
    ending.stream.getTracks().forEach((track) => track.stop());
    ending.context.close();
    $("#call-bar").hidden = true;
    $("#composer").classList.remove("in-call");
    $("#call").setAttribute("aria-pressed", "false");
    setStatus(message || "");
  }

  // --- your voice -----------------------------------------------------------------

  function onAudio(samples) {
    if (!call) return;
    const now = performance.now();
    const ms = (samples.length / call.context.sampleRate) * 1000;
    const level = rms(samples);
    call.level = level;
    const playing = call.sources.length > 0;
    const threshold = Math.max(MIN_LEVEL, call.floor * 3) * (playing ? 1.5 : 1);
    if (level > threshold) {
      call.voiced += ms;
      call.lastVoiced = now;
    } else {
      call.voiced = Math.max(0, call.voiced - ms / 2);
      if (!call.speaking) call.floor = call.floor * 0.97 + level * 0.03;
    }
    const pcm = pcm16(samples, call.context.sampleRate);
    if (!call.speaking) {
      call.preroll.push(pcm);
      call.prerollSamples += pcm.length;
      while (call.prerollSamples > (RATE * PREROLL_MS) / 1000) call.prerollSamples -= call.preroll.shift().length;
      if (call.ready && call.voiced >= (playing ? BARGE_MS : START_MS)) {
        call.speaking = true;
        if (playing) cutOff();
        send({ type: "speech_start", at: now });
        call.frame = [...call.preroll];
        call.frameSamples = call.prerollSamples;
        call.preroll = [];
        call.prerollSamples = 0;
        label("Listening…");
      }
      return;
    }
    call.frame.push(pcm);
    call.frameSamples += pcm.length;
    if (call.frameSamples >= (RATE * FRAME_MS) / 1000) flush();
    if (now - call.lastVoiced >= HANGOVER_MS) {
      flush();
      call.speaking = false;
      call.voiced = 0;
      send({ type: "speech_end", at: call.lastVoiced });
      label("Thinking…");
    }
  }

  function flush() {
    if (!call || !call.frameSamples) return;
    const pcm = join(call.frame);
    call.frame = [];
    call.frameSamples = 0;
    if (call.ws.readyState === WebSocket.OPEN) call.ws.send(pcm.buffer);
  }

  // --- Ira's voice -----------------------------------------------------------------

  function cutOff() {
    if (!call) return;
    for (const s of call.sources) {
      try {
        s.stop();
      } catch {
        /* finished */
      }
    }
    call.sources = [];
    call.nextStart = 0;
    if (call.playingTurn !== null) call.stopped.add(call.playingTurn);
  }

  function play(header, bytes) {
    if (!call || call.stopped.has(header.turn)) return;
    const turn = header.turn;
    const current = call;
    current.decoding = current.decoding
      .then(() => current.context.decodeAudioData(bytes))
      .then((buffer) => {
        if (call !== current || current.stopped.has(turn)) return;
        const source = current.context.createBufferSource();
        source.buffer = buffer;
        source.connect(current.context.destination);
        const at = Math.max(current.context.currentTime + 0.02, current.nextStart);
        source.start(at);
        current.nextStart = at + buffer.duration;
        current.sources.push(source);
        current.playingTurn = turn;
        source.addEventListener("ended", () => {
          current.sources = current.sources.filter((s) => s !== source);
          if (!current.sources.length && call === current && !current.speaking) label("Listening…");
        });
        if (!current.reported.has(turn)) {
          current.reported.add(turn);
          const startsIn = (at - current.context.currentTime) * 1000;
          send({ type: "played", turn, at: performance.now() + startsIn });
        }
        label("Ira is speaking…");
      })
      .catch(() => {
        /* a sentence that does not decode is skipped */
      });
  }

  // --- the server --------------------------------------------------------------------

  function bubble(turn) {
    let li = call.turns.get(turn);
    if (!li) {
      li = addTurn("ira");
      call.turns.set(turn, li);
    }
    return li;
  }

  function onMessage(data) {
    if (!call) return;
    if (data instanceof ArrayBuffer) {
      const header = call.header;
      call.header = null;
      if (header) play(header, data);
      return;
    }
    let message;
    try {
      message = JSON.parse(data);
    } catch {
      return;
    }
    switch (message.type) {
      case "ready":
        call.ready = true;
        state.conversationId = message.conversation_id;
        label("Listening… just talk.");
        break;
      case "partial":
        label(message.text || "Listening…");
        break;
      case "heard":
        addTurn("user", message.text);
        remember({ role: "user", text: message.text });
        bubble(message.turn);
        break;
      case "delta": {
        const li = bubble(message.turn);
        const text = $(".turn-text", li);
        text.textContent += message.text;
        scrollDown();
        break;
      }
      case "audio":
        call.header = message;
        break;
      case "action":
        actionCard(message.action);
        break;
      case "done": {
        const li = bubble(message.turn);
        if (message.text) $(".turn-text", li).textContent = message.text;
        remember({ role: "ira", text: message.text, how: { model: null, tools: [] } });
        if (message.message_id && typeof IraPersonal !== "undefined") IraPersonal.answered(li, message.message_id);
        announce(message.text);
        if (!call.sources.length && !call.speaking) label("Listening…");
        break;
      }
      case "interrupted":
        call.stopped.add(message.turn);
        break;
      case "ping":
        send({ type: "pong" });
        break;
      case "error":
        if (message.fatal) stop(message.message);
        else setStatus(message.message);
        break;
      default:
        break;
    }
  }

  // Typing during a call goes into the call.
  function type(text) {
    if (!call || !text.trim()) return false;
    send({ type: "text", text });
    return true;
  }

  $("#call").addEventListener("click", () => (call ? stop() : start()));
  $("#call-end").addEventListener("click", () => stop());

  return { available, start, stop, type, active: () => call !== null };
})();
