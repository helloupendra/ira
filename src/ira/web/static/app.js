// IRA web chat: sign-in, streamed answers, PIN-confirmed actions, and voice.
// Plain JavaScript on purpose: no build step, nothing to install.
"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const state = { name: "Ira", info: null, conversationId: null, recorder: null };

// --- API --------------------------------------------------------------------------

async function api(path, { method = "GET", json, body, headers = {} } = {}) {
  const init = { method, credentials: "same-origin", headers: { "X-Ira-Request": "1", ...headers } };
  if (json !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(json);
  } else if (body !== undefined) {
    init.body = body;
  }
  return fetch(path, init);
}

async function detail(response) {
  try {
    const data = await response.json();
    return typeof data.detail === "string" ? data.detail : data.message || response.statusText;
  } catch {
    return response.statusText || `HTTP ${response.status}`;
  }
}

// --- views ------------------------------------------------------------------------

function show(view) {
  for (const section of document.querySelectorAll(".view")) section.hidden = section.id !== `view-${view}`;
  if (view === "chat") $("#text").focus();
}

function setName(name) {
  state.name = name;
  document.title = name;
  for (const el of document.querySelectorAll(".brand-name")) el.textContent = name;
}

function setStatus(text) {
  $("#status").textContent = text || "";
}

async function start() {
  try {
    const status = await (await api("/v1/auth/status")).json();
    setName(status.name);
    if (status.setup_required) return show("setup");
  } catch {
    $("#view-loading p").textContent = "Cannot reach the server.";
    return;
  }
  const response = await api("/v1/info");
  if (response.status === 401) return show("login");
  if (!response.ok) return show("login");
  state.info = await response.json();
  setName(state.info.name);
  enterChat();
}

function enterChat() {
  const canVoice = state.info.permissions.includes("voice");
  $("#mic").hidden = !canVoice || !state.info.stt || !window.AudioWorkletNode;
  if (state.info.stt === "fake") setStatus("Demo speech-to-text: the mic returns a fixed sentence.");
  try {
    $("#speak-toggle").checked = localStorage.getItem("ira.speak") === "1";
  } catch {
    /* storage can be unavailable in private windows */
  }
  show("chat");
}

// --- sign-in ----------------------------------------------------------------------

function formJson(form) {
  return Object.fromEntries(new FormData(form).entries());
}

$("#setup-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const response = await api("/v1/auth/setup", { method: "POST", json: formJson(event.target) });
  if (!response.ok) return ($(".error", event.target).textContent = await detail(response));
  start();
});

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const response = await api("/v1/auth/login", { method: "POST", json: formJson(event.target) });
  if (!response.ok) return ($(".error", event.target).textContent = await detail(response));
  event.target.reset();
  start();
});

$("#logout").addEventListener("click", async () => {
  await api("/v1/auth/logout", { method: "POST" });
  $("#messages").replaceChildren();
  state.conversationId = null;
  show("login");
});

$("#new-chat").addEventListener("click", () => {
  state.conversationId = null;
  $("#messages").replaceChildren();
  setStatus("");
});

$("#speak-toggle").addEventListener("change", (event) => {
  try {
    localStorage.setItem("ira.speak", event.target.checked ? "1" : "0");
  } catch {
    /* ignore */
  }
});

// --- chat -------------------------------------------------------------------------

function scrollDown() {
  const list = $("#messages");
  list.scrollTop = list.scrollHeight;
}

function bubble(role, text = "") {
  const item = document.createElement("li");
  item.className = `msg ${role}`;
  item.textContent = text; // never innerHTML: answers are untrusted text
  $("#messages").append(item);
  scrollDown();
  return item;
}

async function* sseEvents(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let cut;
    while ((cut = buffer.indexOf("\n\n")) >= 0) {
      const chunk = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      for (const line of chunk.split("\n")) {
        if (line.startsWith("data:")) yield JSON.parse(line.slice(5));
      }
    }
  }
}

async function send(text) {
  text = text.trim();
  if (!text) return;
  bubble("user", text);
  const answer = bubble("assistant");
  answer.classList.add("pending");
  let full = "";
  try {
    const response = await api("/v1/ask/stream", {
      method: "POST",
      json: { text, conversation_id: state.conversationId },
    });
    if (response.status === 401) return show("login");
    if (!response.ok) throw new Error(await detail(response));
    for await (const event of sseEvents(response)) {
      if (event.type === "start") state.conversationId = event.conversation_id;
      else if (event.type === "delta") {
        full += event.text;
        answer.textContent = full;
        scrollDown();
      } else if (event.type === "action") actionCard(event.action);
      else if (event.type === "done") {
        if (event.text) answer.textContent = full = event.text;
      }
    }
  } catch (error) {
    answer.textContent = `Something went wrong: ${error.message}`;
    answer.classList.add("failed");
  } finally {
    answer.classList.remove("pending");
    scrollDown();
  }
  if (full && $("#speak-toggle").checked) speak(full);
}

$("#composer").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = $("#text");
  const text = input.value;
  input.value = "";
  send(text);
});

// --- actions ----------------------------------------------------------------------

function actionCard(action) {
  const card = $("#action-template").content.firstElementChild.cloneNode(true);
  $(".action-summary", card).textContent = action.summary;
  const status = $(".action-status", card);
  const form = $(".action-form", card);
  let left = action.expires_in;
  const tick = () => {
    status.textContent = left > 0 ? `Expires in ${left}s` : "Expired. Ask again to re-propose it.";
    if (left <= 0) finish();
    left -= 1;
  };
  const timer = setInterval(tick, 1000);
  const finish = () => {
    clearInterval(timer);
    for (const el of form.elements) el.disabled = true;
  };
  tick();

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const pin = $(".pin", form);
    const response = await api(`/v1/actions/${encodeURIComponent(action.id)}/confirm`, {
      method: "POST",
      json: { pin: pin.value },
    });
    pin.value = "";
    const outcome = await response.json().catch(() => ({ message: response.statusText }));
    if (outcome.status === "wrong_pin") {
      status.textContent = outcome.message;
      return;
    }
    finish();
    status.textContent = outcome.message || outcome.detail;
    card.classList.add(outcome.status === "executed" ? "done" : "failed");
  });
  $(".cancel", form).addEventListener("click", async () => {
    const response = await api(`/v1/actions/${encodeURIComponent(action.id)}/cancel`, { method: "POST" });
    const outcome = await response.json().catch(() => ({}));
    finish();
    status.textContent = outcome.message || "Cancelled.";
  });

  $("#messages").append(card);
  scrollDown();
  $(".pin", card).focus({ preventScroll: true });
}

// --- voice out --------------------------------------------------------------------

function plainForSpeech(text) {
  return text
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/https?:\/\/\S+/g, "")
    .replace(/[*_`#>|]/g, "")
    .slice(0, 400);
}

async function speak(text) {
  const tts = state.info && state.info.tts;
  if (tts && tts !== "fake" && state.info.permissions.includes("voice")) {
    const response = await api("/v1/voice/speak", { method: "POST", json: { text } });
    if (response.ok) {
      const url = URL.createObjectURL(await response.blob());
      const audio = new Audio(url);
      audio.addEventListener("ended", () => URL.revokeObjectURL(url));
      audio.play().catch(() => setStatus("Tap the page once to allow audio."));
      return;
    }
  }
  if ("speechSynthesis" in window) {
    speechSynthesis.cancel();
    speechSynthesis.speak(new SpeechSynthesisUtterance(plainForSpeech(text)));
  }
}

// --- voice in: AudioWorklet -> 16 kHz mono WAV ---------------------------------------

async function startRecording() {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
  });
  const context = new AudioContext();
  await context.audioWorklet.addModule("/recorder-worklet.js");
  const source = context.createMediaStreamSource(stream);
  const node = new AudioWorkletNode(context, "recorder");
  const chunks = [];
  node.port.onmessage = (event) => chunks.push(event.data);
  source.connect(node);
  state.recorder = { stream, context, node, chunks, started: Date.now() };
}

async function stopRecording() {
  const { stream, context, node, chunks } = state.recorder;
  state.recorder = null;
  node.disconnect();
  stream.getTracks().forEach((track) => track.stop());
  const rate = context.sampleRate;
  await context.close();
  return encodeWav(downsample(chunks, rate, 16000), 16000);
}

function downsample(chunks, from, to) {
  const length = chunks.reduce((sum, c) => sum + c.length, 0);
  const input = new Float32Array(length);
  let offset = 0;
  for (const c of chunks) {
    input.set(c, offset);
    offset += c.length;
  }
  if (from === to) return input;
  const ratio = from / to;
  const output = new Float32Array(Math.floor(length / ratio));
  for (let i = 0; i < output.length; i++) {
    // Average the source samples that fall in this output sample: a simple low-pass.
    const start = Math.floor(i * ratio);
    const end = Math.min(length, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < end; j++) sum += input[j];
    output[i] = end > start ? sum / (end - start) : input[start] || 0;
  }
  return output;
}

function encodeWav(samples, rate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const text = (at, s) => [...s].forEach((ch, i) => view.setUint8(at + i, ch.charCodeAt(0)));
  text(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  text(8, "WAVE");
  text(12, "fmt ");
  view.setUint32(16, 16, true); // PCM header size
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true); // byte rate
  view.setUint16(32, 2, true); // block align
  view.setUint16(34, 16, true); // bits per sample
  text(36, "data");
  view.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([buffer], { type: "audio/wav" });
}

$("#mic").addEventListener("click", async () => {
  const mic = $("#mic");
  if (!state.recorder) {
    try {
      await startRecording();
    } catch (error) {
      setStatus(`Microphone unavailable: ${error.message}`);
      return;
    }
    mic.setAttribute("aria-pressed", "true");
    setStatus("Listening... tap the mic again to send.");
    return;
  }
  mic.setAttribute("aria-pressed", "false");
  setStatus("Transcribing...");
  try {
    const wav = await stopRecording();
    const response = await api("/v1/voice/transcribe", {
      method: "POST",
      body: wav,
      headers: { "Content-Type": "audio/wav" },
    });
    if (!response.ok) throw new Error(await detail(response));
    const { text } = await response.json();
    setStatus(state.info.stt === "fake" ? "Demo speech-to-text: the mic returns a fixed sentence." : "");
    if (text) {
      $("#speak-toggle").checked = true; // spoke to it: it speaks back
      send(text);
    } else {
      setStatus("I didn't catch that.");
    }
  } catch (error) {
    setStatus(`Voice failed: ${error.message}`);
  }
});

// --- boot -------------------------------------------------------------------------

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}
start();
