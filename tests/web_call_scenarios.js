// The web call client on simulated microphone frames: a browser's parts are stubbed, live.js
// runs as it is. Run by tests/test_web_call.py.
"use strict";
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SOURCE = fs.readFileSync(path.join(__dirname, "../src/ira/web/static/live.js"), "utf8");
const FRAME = 320; // 20 ms at 16 kHz

function element() {
  return {
    hidden: false,
    textContent: "",
    classList: { add() {}, remove() {} },
    setAttribute() {},
    addEventListener() {},
  };
}

async function newCall(options = {}) {
  const world = {
    now: 1000, sent: [], volume: [], sources: [], lines: [], turns: [], steps: [],
    sockets: 0, microphones: 0, tracksStopped: 0,
  };
  const elements = {};
  let socket;
  class WebSocket {
    static OPEN = 1;
    readyState = 1;
    constructor() {
      this.listeners = {};
      socket = this;
      world.sockets += 1;
    }
    addEventListener(type, listener) {
      this.listeners[type] = listener;
    }
    send(data) {
      world.sent.push(typeof data === "string" ? JSON.parse(data) : { pcm: data.byteLength });
    }
    close() {}
  }
  class AudioContext {
    state = "running";
    sampleRate = 16000;
    currentTime = 0;
    destination = {};
    audioWorklet = {
      addModule: async () => {
        if (options.workletFails) throw new Error("no worklet");
      },
    };
    resume = async () => {};
    close = async () => {};
    createMediaStreamSource = () => ({ connect() {} });
    createGain = () => ({ connect() {}, gain: { setTargetAtTime: (level) => world.volume.push(level) } });
    decodeAudioData = async () => ({ duration: 1 });
    createBufferSource = () => {
      const source = {
        connect() {},
        start() {},
        stop() {
          source.stopped = true;
        },
        addEventListener(type, listener) {
          source.ended = listener;
        },
      };
      world.sources.push(source);
      return source;
    };
  }
  let microphone;
  class AudioWorkletNode {
    port = {};
    constructor() {
      microphone = this;
    }
    disconnect() {}
  }
  const sandbox = {
    console,
    ArrayBuffer,
    WebSocket,
    AudioContext,
    AudioWorkletNode,
    window: { isSecureContext: true, AudioWorkletNode, WebSocket },
    navigator: {
      mediaDevices: {
        getUserMedia: async () => {
          world.microphones += 1;
          return { getTracks: () => [{ stop: () => (world.tracksStopped += 1) }] };
        },
      },
    },
    document: { addEventListener() {}, visibilityState: "visible" },
    location: { protocol: "https:", host: "ira.test" },
    performance: { now: () => world.now },
    state: { info: { live: true }, turns: world.turns },
    $: (selector, within) => {
      if (within) return within.text;
      return (elements[selector] ||= element());
    },
    addTurn: (kind, text = "") => {
      const li = { kind, text: { textContent: text }, remove: () => (li.removed = true) };
      world.lines.push(li);
      return li;
    },
    remember: (turn) => world.turns.push(turn),
    rms: (samples) => Math.sqrt(samples.reduce((sum, s) => sum + s * s, 0) / samples.length),
    setStatus() {},
    announce() {},
    actionCard() {},
    scrollDown() {},
    animateMeter() {},
    micMessage: () => "",
    // A tool's steps, as app.js shows them in the chat.
    toolPhrase: (name) => `Checking ${name}…`,
    startWorking: (li) => {
      sandbox.state.working = { li };
      world.steps.push("start");
    },
    workingOn: (name) => world.steps.push(`on ${name}`),
    workedOn: (name) => world.steps.push(`done ${name}`),
    stopWorking: () => {
      sandbox.state.working = null;
      world.steps.push("stop");
    },
  };
  sandbox.state.working = null;
  vm.createContext(sandbox);
  vm.runInContext(SOURCE, sandbox);
  const live = vm.runInContext("IraLive", sandbox);
  if (options.twoTaps) await Promise.all([live.start(), live.start()]);
  else await live.start();
  if (options.workletFails) return world;
  const server = (message) => socket.listeners.message({ data: JSON.stringify(message) });
  server({ type: "ready", conversation_id: "c1" });
  world.server = server;
  world.socket = socket;
  world.frames = (loudness, count) => {
    for (let i = 0; i < count; i++) {
      world.now += 20;
      microphone.port.onmessage({ data: new Float32Array(FRAME).fill(loudness) });
    }
  };
  // Ira's voice: a sentence of a turn, played until `.ended()`.
  world.sentence = async (turn) => {
    server({ type: "audio", turn, seq: 0 });
    socket.listeners.message({ data: new ArrayBuffer(4) });
    await new Promise((resolve) => setImmediate(resolve));
    return world.sources[world.sources.length - 1];
  };
  world.types = () => world.sent.map((m) => m.type || "pcm").filter((t) => !["start", "played"].includes(t));
  world.spoke = () => world.sent.filter((m) => m.type === "speech_start").length;
  world.ducked = () => world.volume[world.volume.length - 1] < 1;
  return world;
}

const QUIET = 0;
const VOICE = 0.2;

const scenarios = {
  async "a second tap while the first waits opens no second call"() {
    const call = await newCall({ twoTaps: true });
    assert.strictEqual(call.sockets, 1);
    assert.strictEqual(call.microphones, 1);
  },

  async "a call whose audio part fails leaves the mic off"() {
    const call = await newCall({ workletFails: true });
    assert.strictEqual(call.sockets, 0);
    assert.strictEqual(call.tracksStopped, 1);
  },

  // As the chat shows them: the step in words and its receipt; and "let me look", written
  // before the tool, is not glued to the answer when "done" comes without its own text.
  async "a tool's steps show, and its lead-in is not the answer"() {
    const call = await newCall();
    call.server({ type: "heard", turn: 1, text: "kal ka calendar" });
    call.server({ type: "delta", turn: 1, text: "Let me look. " });
    call.server({ type: "tool", turn: 1, name: "calendar_read" });
    call.server({ type: "tool_result", turn: 1, name: "calendar_read", ok: true });
    call.server({ type: "delta", turn: 1, text: "Kal 3 baje meeting hai." });
    call.server({ type: "done", turn: 1, text: "" });
    const ira = call.lines.filter((li) => li.kind === "ira").pop();
    assert.strictEqual(ira.text.textContent, "Kal 3 baje meeting hai.");
    assert.deepStrictEqual(call.steps, ["start", "on calendar_read", "done calendar_read", "stop"]);
    const remembered = call.turns[call.turns.length - 1];
    assert.strictEqual(JSON.stringify(remembered.how.tools), JSON.stringify([{ name: "calendar_read", ok: true }]));
  },

  async "an answer with no tool is as before"() {
    const call = await newCall();
    call.server({ type: "heard", turn: 1, text: "namaste" });
    call.server({ type: "delta", turn: 1, text: "Namaste! " });
    call.server({ type: "done", turn: 1, text: "Namaste! Kaise ho?" });
    assert.strictEqual(call.lines.filter((li) => li.kind === "ira").pop().text.textContent, "Namaste! Kaise ho?");
    assert.deepStrictEqual(call.steps, []);
    assert.strictEqual(JSON.stringify(call.turns[call.turns.length - 1].how.tools), "[]");
  },

  async "a cough is not speech"() {
    const call = await newCall();
    call.frames(QUIET, 10);
    call.frames(VOICE, 6); // 120 ms
    call.frames(QUIET, 60);
    assert.deepStrictEqual(call.types(), []);
  },

  async "a voice starts a turn, and a pause in the sentence stays in it"() {
    const call = await newCall();
    call.frames(QUIET, 10);
    call.frames(VOICE, 20);
    call.frames(QUIET, 35); // 700 ms: a pause
    call.frames(VOICE, 20);
    assert.strictEqual(call.spoke(), 1);
    assert.ok(!call.types().includes("speech_end"));
    call.frames(QUIET, 50); // 1 s: the end
    assert.strictEqual(call.spoke(), 1);
    assert.strictEqual(call.types().filter((t) => t === "speech_end").length, 1);
  },

  async "her echo fades: nothing is sent and she comes back up"() {
    const call = await newCall();
    await call.sentence(1);
    call.frames(QUIET, 5);
    call.frames(VOICE, 11); // the sound starts; she is turned down
    assert.ok(call.ducked());
    call.frames(QUIET, 20); // with her quieter, it fades
    assert.strictEqual(call.spoke(), 0);
    assert.ok(!call.ducked());
    assert.ok(!call.types().includes("pcm"));
    assert.ok(!call.sources[0].stopped);
  },

  async "a voice over hers goes to the server, and only its answer stops her"() {
    const call = await newCall();
    const voice = await call.sentence(1);
    call.frames(VOICE, 30);
    assert.strictEqual(call.spoke(), 1);
    assert.ok(call.ducked());
    assert.ok(!voice.stopped); // only their words stop her
    call.server({ type: "interrupted", turn: 1 });
    assert.ok(voice.stopped);
    assert.ok(!call.ducked());
  },

  async "a soft voice is heard over her once her echo is known to be small"() {
    const call = await newCall();
    await call.sentence(1);
    call.frames(0.001, 300); // 6 s of her, with echo cancelling leaving almost nothing
    call.frames(0.025, 30); // quieter than the first bar, a normal voice in a room
    assert.strictEqual(call.spoke(), 1);
    assert.strictEqual(call.sent.find((m) => m.type === "speech_start").over, true);
  },

  async "her strong echo raises the bar, and she stays at full volume"() {
    const call = await newCall();
    await call.sentence(1);
    call.frames(0.02, 300); // her voice reaches the microphone well
    call.frames(0.04, 30); // a peak of it
    assert.deepStrictEqual(call.volume, []);
    assert.strictEqual(call.spoke(), 0);
  },

  async "she comes back up when the sound ends, without waiting for the server"() {
    const call = await newCall();
    const voice = await call.sentence(1);
    call.frames(VOICE, 30);
    assert.ok(call.ducked());
    call.frames(QUIET, 50);
    assert.ok(!call.ducked());
    assert.ok(!voice.stopped);
  },

  async "if you keep talking she stops, without waiting for words"() {
    const call = await newCall();
    const voice = await call.sentence(1);
    call.frames(VOICE, 50); // a second: the server has not found words yet
    assert.ok(!voice.stopped);
    call.frames(VOICE, 30);
    assert.ok(voice.stopped);
    assert.strictEqual(call.types().filter((t) => t === "interrupt").length, 1);
    call.frames(VOICE, 100);
    assert.strictEqual(call.types().filter((t) => t === "interrupt").length, 1);
  },

  async "she is never turned down for long, even under a sound that goes on"() {
    const call = await newCall();
    const voice = await call.sentence(1);
    call.frames(0.02, 300); // her echo is known: 0.02
    call.frames(0.2, 12); // a sound over her: she goes down, and it goes to the server
    assert.ok(call.ducked());
    call.frames(0.015, 200); // 4 s of something above the room, below her echo: no words came
    assert.ok(!call.ducked());
    assert.ok(!voice.stopped);
  },

  async "speech with her quiet says it did not begin over her"() {
    const call = await newCall();
    call.frames(VOICE, 12);
    assert.strictEqual(call.sent.find((m) => m.type === "speech_start").over, false);
  },

  async "a noise the server finds no words in leaves her answer playing"() {
    const call = await newCall();
    const voice = await call.sentence(1);
    call.frames(VOICE, 30);
    call.frames(QUIET, 50);
    assert.strictEqual(call.types().filter((t) => t === "speech_end").length, 1);
    call.server({ type: "speech_ignored" });
    assert.ok(!voice.stopped);
    assert.ok(!call.ducked());
  },

  async "the gap between two sentences still counts as her speaking"() {
    const call = await newCall();
    const first = await call.sentence(1);
    call.frames(QUIET, 5);
    first.ended();
    call.frames(VOICE, 11);
    assert.ok(call.ducked()); // checked, not sent as speech
    assert.strictEqual(call.spoke(), 0);
    call.frames(QUIET, 20);
    assert.strictEqual(call.spoke(), 0);
  },

  async "while she thinks, speech is sent and stops nothing"() {
    const call = await newCall();
    call.server({ type: "heard", turn: 1, text: "first" });
    call.frames(VOICE, 12);
    assert.strictEqual(call.spoke(), 1);
    assert.deepStrictEqual(call.volume, []);
  },

  async "a replaced turn's lines go"() {
    const call = await newCall();
    call.server({ type: "heard", turn: 1, text: "I want" });
    const [yours, hers] = call.lines;
    call.server({ type: "heard", turn: 2, text: "I want to go home", replaces: 1 });
    assert.ok(yours.removed && hers.removed);
    assert.deepStrictEqual(call.turns.map((t) => t.text), ["I want to go home"]);
  },
};

(async () => {
  for (const [name, scenario] of Object.entries(scenarios)) {
    await scenario().catch((error) => {
      console.error(`failed: ${name}`);
      throw error;
    });
    console.log(`ok: ${name}`);
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
