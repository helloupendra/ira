// A live call with Ira: talk and listen like a phone call, no button between turns.
// The protocol is docs/realtime.md (version 1). Loaded after app.js, whose helpers
// ($, state, addTurn, remember, setStatus, announce, actionCard, rms, scrollDown, and
// startWorking, workingOn, workedOn, stopWorking, toolPhrase for a tool's steps) it uses.
// The voice detector runs here, on the device: audio leaves only while you speak.
"use strict";

const IraLive = (() => {
  const RATE = 16000;
  const FRAME_MS = 40; // audio goes up in 40 ms frames
  const START_MS = 160; // this much speech starts a turn: a cough or a knock is shorter
  const BARGE_MS = 200; // while Ira speaks, a little more: its own voice is not you
  const HANGOVER_MS = 900; // this much quiet ends a turn: a pause in a sentence is shorter
  const CHECK_MS = 300; // a sound over Ira's voice is watched this long, with her turned down
  const LOUD_SHARE = 0.6; // and must stay loud for this share of it to be you, not her echo
  const DUCK_LEVEL = 0.15; // how far she is turned down meanwhile
  const ECHO_TAIL_MS = 400; // her voice may still be in the room this long after she stopped
  const DUCK_AT_MOST_MS = 3000; // she stays easy to hear, whatever the server says
  const SURE_MS = 1200; // this long louder than her echo, with her turned down, is you
  const ECHO_FACTOR = 2.5; // while she speaks, the bar is this many times her voice at the mic
  const ECHO_CEILING = 0.15; // but never past a level a normal voice reaches
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

  // Safari 17 and later: say this page plays and records, or the iPhone's silent switch
  // mutes Ira's voice (Web Audio counts as "ambient" sound otherwise).
  function audioSession(type) {
    try {
      if (navigator.audioSession) navigator.audioSession.type = type;
    } catch {
      /* not this browser */
    }
  }

  // Keep the screen on during a call where the browser allows it (Safari 16.4+, Chrome).
  async function keepAwake() {
    const current = call;
    if (!current || current.wakeLock || !("wakeLock" in navigator)) return;
    try {
      const lock = await navigator.wakeLock.request("screen");
      if (call !== current) return lock.release().catch(() => {});
      current.wakeLock = lock;
      lock.addEventListener("release", () => (current.wakeLock = null));
    } catch {
      /* not allowed now: the screen may dim */
    }
  }

  // Back from the lock screen or another app: the screen lock and the sound come back too.
  document.addEventListener("visibilitychange", () => {
    if (!call || document.visibilityState !== "visible") return;
    keepAwake();
    if (call.context.state !== "running") call.context.resume().catch(() => {});
  });

  async function start() {
    if (call || !available()) return;
    // iOS starts sound only inside the tap: the context is made here, before anything waits.
    const context = new AudioContext();
    context.resume().catch(() => {});
    audioSession("play-and-record");
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    } catch (error) {
      context.close().catch(() => {});
      audioSession("auto");
      return setStatus(micMessage(error));
    }
    await context.audioWorklet.addModule("/recorder-worklet.js");
    if (context.state !== "running") await context.resume().catch(() => {});
    const source = context.createMediaStreamSource(stream);
    const node = new AudioWorkletNode(context, "recorder");
    const volume = context.createGain();
    volume.connect(context.destination);
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${scheme}://${location.host}/v1/voice/live`);
    ws.binaryType = "arraybuffer";
    call = {
      ws,
      stream,
      context,
      node,
      volume,
      level: 0,
      floor: MIN_LEVEL / 2,
      voiced: 0,
      speaking: false,
      check: null, // a sound over Ira's voice, being watched before any of it is sent
      talkingOver: false, // you are talking over her: the server decides by your words
      echoLevel: MIN_LEVEL, // how loud her voice reaches the mic, learned while she speaks
      loudMs: null, // how long you stayed loud over her, once sent
      duckedAt: null,
      echoUntil: 0,
      voicedTurn: 0, // the last turn whose voice came
      heardTurn: 0,
      doneThrough: 0, // the last turn that is complete
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
      yours: new Map(), // turn number -> your line, and what was remembered of it
      tools: new Map(), // turn number -> the tools it used, for the answer's "how"
      ready: false,
      wakeLock: null,
    };
    keepAwake();
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
    for (const li of ending.turns.values()) doneWorking(li);
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
    if (ending.wakeLock) ending.wakeLock.release().catch(() => {});
    audioSession("auto");
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
    if (call.duckedAt !== null && now - call.duckedAt > DUCK_AT_MOST_MS) duck(false);
    const guarded = replying(now) && !call.talkingOver;
    const base = Math.max(MIN_LEVEL, call.floor * 3);
    const threshold = guarded ? Math.max(base, Math.min(call.echoLevel * ECHO_FACTOR, ECHO_CEILING)) : base;
    const loud = level > threshold;
    if (guarded && !call.speaking) {
      const weight = (level > call.echoLevel ? 0.02 : 0.01) * (ms / 20);
      call.echoLevel += (level - call.echoLevel) * weight;
    }
    if (call.talkingOver && call.loudMs !== null) {
      if (level > Math.max(base, call.echoLevel)) call.loudMs += ms;
      if (call.loudMs >= SURE_MS) {
        // You kept talking, and she is turned down: it is you. She stops without waiting for
        // the first words, which can take seconds.
        call.loudMs = null;
        send({ type: "interrupt" });
        cutOff();
        if (call.duckedAt !== null) duck(false);
      }
    }
    if (loud) {
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
      if (call.ready && call.voiced >= (guarded ? BARGE_MS : START_MS)) {
        call.speaking = true;
        call.frame = [...call.preroll];
        call.frameSamples = call.prerollSamples;
        call.preroll = [];
        call.prerollSamples = 0;
        if (guarded) {
          // Ira is talking: this may be you, or her own voice from the speakers. She is turned
          // down while it is checked; only your words, on the server, stop her.
          duck(true);
          call.check = { start: now, frames: 0, loud: 0 };
        } else {
          send({ type: "speech_start", at: now, over: false });
          label("Listening…");
        }
      }
      return;
    }
    call.frame.push(pcm);
    call.frameSamples += pcm.length;
    if (call.check) {
      call.check.frames += 1;
      // With her down, her echo is far below the bar she needs with her at full volume.
      if (level > base) call.check.loud += 1;
      if (now - call.check.start < CHECK_MS) return;
      const { start, frames, loud: stayed } = call.check;
      call.check = null;
      if (stayed < frames * LOUD_SHARE) {
        // It faded with her voice: her echo. Nothing was sent, and she comes back up.
        duck(false);
        call.speaking = false;
        call.voiced = 0;
        call.frame = [];
        call.frameSamples = 0;
        return;
      }
      call.talkingOver = true;
      call.loudMs = stayed * ms;
      send({ type: "speech_start", at: start, over: true });
      label("Listening…");
    }
    if (call.frameSamples >= (RATE * FRAME_MS) / 1000) flush();
    if (now - call.lastVoiced >= HANGOVER_MS) {
      flush();
      call.speaking = false;
      call.talkingOver = false;
      call.loudMs = null;
      call.voiced = 0;
      send({ type: "speech_end", at: call.lastVoiced });
      // The sound is over: she comes back up now, if the server has not stopped her.
      if (call.duckedAt !== null) duck(false);
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

  // She is speaking, or about to go on, or was a moment ago: gaps between sentences count.
  function replying(now) {
    return call.sources.length > 0 || call.voicedTurn > call.doneThrough || now < call.echoUntil;
  }

  function duck(on) {
    call.duckedAt = on ? performance.now() : null;
    call.volume.gain.setTargetAtTime(on ? DUCK_LEVEL : 1, call.context.currentTime, 0.02);
  }

  // Nothing more of hers is playing or coming.
  function quiet() {
    if (call.voicedTurn > 0) call.echoUntil = performance.now() + ECHO_TAIL_MS;
    if (call.duckedAt !== null) duck(false);
  }

  function cutOff() {
    if (!call) return;
    call.echoUntil = performance.now() + ECHO_TAIL_MS;
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
        source.connect(current.volume);
        const at = Math.max(current.context.currentTime + 0.02, current.nextStart);
        source.start(at);
        current.nextStart = at + buffer.duration;
        current.sources.push(source);
        current.playingTurn = turn;
        source.addEventListener("ended", () => {
          current.sources = current.sources.filter((s) => s !== source);
          if (current.sources.length || call !== current) return;
          // Between two sentences she is still speaking: the next is on its way.
          if (current.voicedTurn > current.doneThrough) return;
          quiet();
          if (!current.speaking) label(current.heardTurn > current.doneThrough ? "Thinking…" : "Listening…");
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

  // That turn was the first half of a sentence: its lines go, its words are in the next.
  function forget(turn) {
    const yours = call.yours.get(turn);
    if (yours) {
      yours.li.remove();
      const index = state.turns.lastIndexOf(yours.remembered);
      if (index >= 0) state.turns.splice(index, 1);
      call.yours.delete(turn);
    }
    const li = call.turns.get(turn);
    if (li) {
      doneWorking(li);
      li.remove();
      call.turns.delete(turn);
    }
    call.tools.delete(turn);
  }

  // The answer this bubble holds is no longer being worked on: its steps and their receipts go.
  function doneWorking(li) {
    if (state.working && state.working.li === li) stopWorking();
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
      case "heard": {
        if (message.replaces != null) forget(message.replaces);
        call.heardTurn = Math.max(call.heardTurn, message.turn);
        const remembered = { role: "user", text: message.text };
        call.yours.set(message.turn, { li: addTurn("user", message.text), remembered });
        remember(remembered);
        bubble(message.turn);
        break;
      }
      case "delta": {
        const li = bubble(message.turn);
        doneWorking(li);
        const text = $(".turn-text", li);
        text.textContent += message.text;
        scrollDown();
        break;
      }
      case "tool": {
        // Ira is using a tool: say so, as the chat does, with its receipt while it runs. What
        // she wrote before it was a lead-in ("let me look"), not the answer: it goes.
        const li = bubble(message.turn);
        $(".turn-text", li).textContent = "";
        if (!state.working || state.working.li !== li) startWorking(li);
        workingOn(message.name);
        label(toolPhrase(message.name));
        if (!call.tools.has(message.turn)) call.tools.set(message.turn, []);
        call.tools.get(message.turn).push({ name: message.name });
        break;
      }
      case "tool_result": {
        workedOn(message.name);
        const used = [...(call.tools.get(message.turn) || [])]
          .reverse()
          .find((tool) => tool.name === message.name && tool.ok === undefined);
        if (used) used.ok = message.ok !== false;
        break;
      }
      case "audio":
        call.header = message;
        if (!call.stopped.has(message.turn)) call.voicedTurn = Math.max(call.voicedTurn, message.turn);
        break;
      case "action":
        actionCard(message.action);
        break;
      case "done": {
        const li = bubble(message.turn);
        doneWorking(li);
        if (message.text) $(".turn-text", li).textContent = message.text;
        remember({ role: "ira", text: message.text, how: { model: null, tools: call.tools.get(message.turn) || [] } });
        call.tools.delete(message.turn);
        if (message.message_id && typeof IraPersonal !== "undefined") IraPersonal.answered(li, message.message_id);
        announce(message.text);
        call.doneThrough = Math.max(call.doneThrough, message.turn);
        if (!call.sources.length && call.voicedTurn <= call.doneThrough) {
          quiet();
          if (!call.speaking) label(call.heardTurn > call.doneThrough ? "Thinking…" : "Listening…");
        }
        break;
      }
      case "interrupted":
        if (call.turns.has(message.turn)) doneWorking(call.turns.get(message.turn));
        call.stopped.add(message.turn);
        call.doneThrough = Math.max(call.doneThrough, message.turn);
        // Your words were heard: she stops now, even an answer that was fully sent.
        if (call.playingTurn !== null && call.playingTurn <= message.turn) cutOff();
        if (call.duckedAt !== null) duck(false);
        break;
      case "speech_ignored":
        // A noise, or her own voice: she comes back up, and the answer on its way stands.
        if (call.duckedAt !== null) duck(false);
        if (!call.speaking) {
          if (call.sources.length) label("Ira is speaking…");
          else label(call.heardTurn > call.doneThrough ? "Thinking…" : "Listening…");
        }
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
