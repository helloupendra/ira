// The Ira app: sign in, ask by voice or text, see how an answer was found,
// and release an action with a PIN. Plain JavaScript on purpose: no build
// step, nothing to install.
"use strict";

const $ = (selector, root = document) => root.querySelector(selector);

const SPEECH_LEVEL = 0.02; // RMS above this counts as speech
const SILENCE_MS = 1500; // a pause this long after speech ends the recording
const NO_SPEECH_MS = 8000; // give up when nothing was said at all
const MAX_RECORD_MS = 60000;
const REST_HEIGHTS = [6, 14, 20, 10]; // the four bars of the mark, at rest

const state = {
  name: "Ira",
  info: null,
  conversationId: null,
  mode: "idle", // idle | listening | transcribing | thinking | answering | speaking
  recorder: null,
  recognizer: null, // the browser's own speech recognition, while it listens
  player: null,
  turns: [], // today's conversation, so a reload keeps it
  lastInputWasVoice: false,
  pendingText: null, // a question kept across a sign-in
  notice: "", // shown once the app is idle again
  online: navigator.onLine,
};

try {
  const theme = localStorage.getItem("ira.theme");
  if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme;
} catch {
  /* storage can be unavailable in private windows */
}

// --- API --------------------------------------------------------------------------

class Unreachable extends Error {
  constructor() {
    super(
      navigator.onLine
        ? "Can't reach Ira. Check your connection and try again."
        : "You're offline. Ira needs a connection to answer.",
    );
  }
}

class ModelFailure extends Error {}

async function api(path, { method = "GET", json, body, headers = {} } = {}) {
  const init = { method, credentials: "same-origin", headers: { "X-Ira-Request": "1", ...headers } };
  if (json !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(json);
  } else if (body !== undefined) {
    init.body = body;
  }
  try {
    return await fetch(path, init);
  } catch {
    throw new Unreachable();
  }
}

async function detail(response) {
  try {
    const data = await response.json();
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail)) return data.detail.map((d) => d.msg).join("; ");
    return data.message || response.statusText;
  } catch {
    return response.statusText || `HTTP ${response.status}`;
  }
}

const storage = {
  get(key) {
    try {
      return JSON.parse(localStorage.getItem(key));
    } catch {
      return null;
    }
  },
  set(key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* ignore */
    }
  },
  remove(key) {
    try {
      localStorage.removeItem(key);
    } catch {
      /* ignore */
    }
  },
};

// --- views ------------------------------------------------------------------------

function show(view) {
  for (const section of document.querySelectorAll(".view")) section.hidden = section.id !== `view-${view}`;
}

function setName(name) {
  state.name = name;
  document.title = name;
  for (const el of document.querySelectorAll(".brand-name")) el.textContent = name;
}

function gateMessage(text) {
  $("#view-loading p").textContent = text;
  show("loading");
}

async function start() {
  let status;
  try {
    status = await (await api("/v1/auth/status")).json();
  } catch {
    return gateMessage("Can't reach the server. Is Ira running?");
  }
  setName(status.name);
  if (status.setup_required) {
    // The setup link carries the code in the fragment, which never reaches the server.
    const code = new URLSearchParams(location.hash.slice(1)).get("code");
    if (code) $("#setup-form input[name=code]").value = code;
    show("setup");
    $(`#setup-form input[name=${code ? "email" : "code"}]`).focus();
    return;
  }
  let response;
  try {
    response = await api("/v1/info");
  } catch (error) {
    return gateMessage(error.message);
  }
  if (response.status === 401) return show("login");
  if (!response.ok) return gateMessage(await detail(response));
  state.info = await response.json();
  setName(state.info.name);
  enterChat();
}

function enterChat() {
  const { user, permissions } = state.info;
  $("#menu-email").textContent = user.email;
  $("#menu-role").textContent = user.role;
  $("#menu-admin").hidden = !permissions.includes("admin.read");
  $("#speak-toggle").checked = storage.get("ira.speak") === true;
  $("#handsfree-toggle").checked = storage.get("ira.handsfree") === true;
  $("#login-note").hidden = true;
  loadPinStatus();
  restoreToday();
  updateBanner();
  const canAsk = permissions.includes("ask");
  $("#text").disabled = !canAsk;
  for (const button of document.querySelectorAll(".voice-mark")) {
    button.classList.toggle("off", !canAsk || voiceProblem() !== null);
  }
  // A live call, when this server can take one (see live.js).
  $("#call").hidden = !(canAsk && typeof IraLive !== "undefined" && IraLive.available());
  if (!canAsk) {
    $("#hero-hint").textContent = `Your role (${user.role}) can't ask Ira. The admin console is in the menu.`;
  } else if (voiceProblem()) {
    $("#hero-hint").textContent = "Type below to ask. The mic explains why it is off.";
  } else {
    $("#hero-hint").textContent = "Tap to talk, or type below.";
  }
  show("chat");
  setMode("idle");
  if (state.pendingText) {
    $("#text").value = state.pendingText;
    state.pendingText = null;
  }
  if (canAsk && matchMedia("(hover: hover)").matches) $("#text").focus({ preventScroll: true });
  if (typeof IraPersonal !== "undefined") IraPersonal.entered(); // your devices' events
}

function updateBanner() {
  const banner = $("#banner");
  let text = "";
  let danger = false;
  if (!state.online) {
    text = "You're offline. Ira needs a connection to answer.";
    danger = true;
  } else if (state.info && state.info.stt === "fake") {
    text = "Demo speech-to-text: the mic returns a fixed sentence.";
  }
  banner.textContent = text;
  banner.classList.toggle("danger", danger);
  banner.hidden = !text;
}

// --- state in words ---------------------------------------------------------------

function setMode(mode) {
  state.mode = mode;
  $("#view-chat").className = `view chat mode-${mode}`;
  const busy = mode !== "idle";
  $("#send").disabled = busy || !state.online || !$("#text") || $("#text").disabled;
  $("#mic").setAttribute("aria-pressed", mode === "listening" ? "true" : "false");
  $("#listen").hidden = !(mode === "listening" || mode === "transcribing");
  if (mode === "idle") {
    setStatus(state.notice);
    state.notice = "";
  }
}

function setStatus(text, button) {
  const el = $("#status");
  el.replaceChildren();
  if (text) el.append(document.createTextNode(text));
  if (button) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "text-btn";
    b.textContent = button.label;
    b.addEventListener("click", button.onClick);
    el.append(" ", b);
  }
}

function announce(text) {
  const live = $("#announce");
  live.textContent = "";
  setTimeout(() => {
    live.textContent = text;
  }, 50);
}

function humanize(name) {
  return name.replace(/[_-]+/g, " ");
}

function toolFor(name) {
  return (state.info.tools || []).find((t) => t.name === name);
}

function toolPhrase(name) {
  const tool = toolFor(name);
  return `${tool && tool.kind === "action" ? "Preparing" : "Checking"} ${humanize(name)}…`;
}

function listWords(items) {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} or ${items[items.length - 1]}`;
}

function mmss(seconds) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function clockTime(date) {
  return date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

// --- sign-in ----------------------------------------------------------------------

function formJson(form) {
  return Object.fromEntries(new FormData(form).entries());
}

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  const error = $(".error", form);
  error.textContent = "";
  $("button", form).disabled = true;
  try {
    const response = await api("/v1/auth/login", { method: "POST", json: formJson(form) });
    if (response.status === 429) {
      error.textContent = "Too many failed sign-ins. Try again in 15 minutes.";
    } else if (!response.ok) {
      error.textContent = await detail(response);
    } else {
      form.reset();
      await start();
    }
  } catch (problem) {
    error.textContent = problem.message;
  } finally {
    $("button", form).disabled = false;
  }
});

$("#setup-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  const error = $(".error", form);
  error.textContent = "";
  $("button", form).disabled = true;
  try {
    const response = await api("/v1/setup/owner", { method: "POST", json: formJson(form) });
    if (response.status === 403) error.textContent = "That setup code is wrong. It is printed where the server runs.";
    else if (response.status === 429) error.textContent = "Too many wrong codes. Try again in 15 minutes.";
    else if (response.status === 409) error.textContent = "Setup is already done. Sign in instead.";
    else if (!response.ok) error.textContent = await detail(response);
    else {
      form.reset();
      history.replaceState(null, "", location.pathname); // drop the code from the address
      state.notice = "Welcome. Next, set your action PIN in the menu: it releases actions.";
      await start();
    }
  } catch (problem) {
    error.textContent = problem.message;
  } finally {
    $("button", form).disabled = false;
  }
});

function sessionExpired(text) {
  stopSpeaking();
  if (typeof IraLive !== "undefined") IraLive.stop();
  state.pendingText = text || null;
  state.info = null;
  const note = $("#login-note");
  note.textContent = "Your session expired. Sign in to continue.";
  note.hidden = false;
  show("login");
  $("#login-form input[name=email]").focus();
}

$("#logout").addEventListener("click", async () => {
  $("#menu").close();
  stopSpeaking();
  if (typeof IraPersonal !== "undefined") IraPersonal.left();
  if (typeof IraLive !== "undefined") IraLive.stop();
  try {
    await api("/v1/auth/logout", { method: "POST" });
  } catch {
    /* signing out locally is enough */
  }
  storage.remove("ira.today");
  state.info = null;
  state.turns = [];
  state.conversationId = null;
  $("#messages").replaceChildren();
  show("login");
});

// --- settings sheet ---------------------------------------------------------------

$("#menu-open").addEventListener("click", () => {
  $("#menu").showModal();
  loadHistory();
});
$("#menu-close").addEventListener("click", () => $("#menu").close());
$("#menu").addEventListener("click", (event) => {
  if (event.target === event.currentTarget) event.currentTarget.close();
});
$("#speak-toggle").addEventListener("change", (event) => storage.set("ira.speak", event.target.checked));
$("#handsfree-toggle").addEventListener("change", (event) => storage.set("ira.handsfree", event.target.checked));
$("#new-chat").addEventListener("click", newConversation);

async function loadPinStatus() {
  const text = $("#pin-status");
  const open = $("#pin-open");
  text.className = "menu-user";
  open.hidden = true;
  let pin;
  try {
    const response = await api("/v1/me/pin");
    if (!response.ok) throw new Error(await detail(response));
    pin = await response.json();
  } catch {
    text.textContent = "";
    return;
  }
  if (!pin.can_confirm) {
    text.textContent = "Your role can't confirm actions, so no PIN is needed.";
    return;
  }
  const input = $("#pin-form input[name=pin]");
  if (pin.pin_min_length && pin.pin_max_length) {
    input.minLength = pin.pin_min_length;
    input.maxLength = pin.pin_max_length;
    input.pattern = `[0-9]{${pin.pin_min_length},${pin.pin_max_length}}`;
    $("#pin-rule").textContent = `${pin.pin_min_length} to ${pin.pin_max_length} digits`;
  }
  if (pin.locked_until || pin.locked_seconds) {
    const until = pin.locked_until
      ? new Date(pin.locked_until * 1000)
      : new Date(Date.now() + pin.locked_seconds * 1000);
    text.textContent = `Actions are locked after wrong PINs until ${clockTime(until)}.`;
  } else if (pin.has_pin) {
    text.textContent = pin.pin_set_at
      ? `Your action PIN is set (since ${new Date(pin.pin_set_at * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short" })}).`
      : "Your action PIN is set.";
  } else {
    text.textContent = "You have no action PIN yet. You need one to confirm actions.";
  }
  open.textContent = pin.has_pin ? "Change your PIN" : "Set your PIN";
  open.hidden = false;
}

function openPinForm() {
  const menu = $("#menu");
  if (!menu.open) menu.showModal();
  $("#pin-form").hidden = false;
  $("#pin-open").hidden = true;
  $("#pin-form input[name=password]").focus();
}

$("#pin-open").addEventListener("click", openPinForm);
$("#pin-cancel").addEventListener("click", () => {
  $("#pin-form").reset();
  $("#pin-form").hidden = true;
  $("#pin-open").hidden = false;
});
$("#pin-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  const error = $(".error", form);
  const body = formJson(form);
  form.reset(); // neither the password nor the PIN is kept
  error.textContent = "";
  try {
    const response = await api("/v1/me/pin", { method: "PUT", json: body });
    if (response.status === 401) return sessionExpired();
    if (response.status === 429) error.textContent = "Too many wrong passwords. Try again in 15 minutes.";
    else if (response.status === 403) error.textContent = "That is not your password.";
    else if (response.status === 422) error.textContent = "A PIN is 4 to 12 digits.";
    else if (!response.ok) error.textContent = await detail(response);
    else {
      form.hidden = true;
      $("#pin-status").textContent = "PIN saved. Wrong PINs lock actions after three tries.";
      $("#pin-status").className = "menu-user ok";
      $("#pin-open").textContent = "Change your PIN";
      $("#pin-open").hidden = false;
    }
  } catch (problem) {
    error.textContent = problem.message;
  }
});

function speakOn() {
  return $("#speak-toggle").checked;
}

function handsFreeOn() {
  return $("#handsfree-toggle").checked;
}

// --- today's conversation ---------------------------------------------------------

function today() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function remember(turn) {
  state.turns.push(turn);
  storage.set("ira.today", {
    user: state.info.user.id,
    day: today(),
    conversationId: state.conversationId,
    turns: state.turns,
  });
}

function renderTurns(turns) {
  $("#messages").replaceChildren();
  for (const turn of turns) {
    const li = addTurn(turn.role, turn.text);
    if (turn.role === "ira" && turn.how) explain(li, turn.how);
  }
  $("#hero").hidden = turns.length === 0 ? false : true;
}

// The server's transcript of a conversation, as the turns this page shows.
function turnsFromTranscript(messages) {
  const turns = [];
  let how = { tools: [], model: null };
  for (const m of messages) {
    if (m.role === "user") {
      turns.push({ role: "user", text: m.content || "" });
      how = { tools: [], model: null };
    } else if (m.role === "assistant") {
      for (const call of m.tool_calls || []) how.tools.push({ id: call.id, name: call.name, arguments: call.arguments });
      if (m.model) how.model = m.model;
      if (m.content) {
        turns.push({ role: "ira", text: m.content, how });
        how = { tools: [], model: null };
      }
    } else if (m.role === "tool") {
      const call = how.tools.find((t) => t.id === m.tool_call_id);
      if (call) call.result = m.content;
    }
    // A proposal rides on the tool result that made it (or, if the server
    // ever moves it, on the answer); either way it becomes a note.
    if (m.action) {
      turns.push({ role: "note", text: `${KICKER[m.action.status] || m.action.status}: ${m.action.summary}` });
    }
  }
  return turns;
}

async function openConversation(id) {
  const response = await api(`/v1/conversations/${encodeURIComponent(id)}`);
  if (response.status === 401) return sessionExpired();
  if (!response.ok) throw new Error(await detail(response));
  const turns = turnsFromTranscript(await response.json());
  state.conversationId = id;
  state.turns = turns;
  renderTurns(turns);
  storage.set("ira.today", { user: state.info.user.id, day: today(), conversationId: id, turns });
}

async function restoreToday() {
  $("#messages").replaceChildren();
  state.turns = [];
  state.conversationId = null;
  $("#hero").hidden = false;
  const saved = storage.get("ira.today");
  if (!saved || saved.user !== state.info.user.id || saved.day !== today()) return;
  if (saved.conversationId) {
    try {
      await openConversation(saved.conversationId); // the server's copy is the truth
      return;
    } catch {
      /* fall back to what this device remembered */
    }
  }
  if (Array.isArray(saved.turns) && saved.turns.length) {
    state.conversationId = saved.conversationId;
    state.turns = saved.turns;
    renderTurns(saved.turns);
  }
}

async function loadHistory() {
  const list = $("#history-list");
  list.replaceChildren();
  let rows = [];
  try {
    const response = await api("/v1/conversations?limit=20");
    if (response.ok) rows = await response.json();
  } catch {
    /* the list is a convenience; the menu still works without it */
  }
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  rows = rows.filter((row) => row.last_at * 1000 >= start.getTime());
  if (!rows.length) {
    const empty = document.createElement("li");
    empty.className = "history-empty";
    empty.textContent = "No conversations yet today.";
    list.append(empty);
    return;
  }
  for (const row of rows) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "history-item";
    if (row.id === state.conversationId) button.setAttribute("aria-current", "true");
    const text = document.createElement("span");
    text.className = "history-text";
    text.textContent = row.preview || `Conversation at ${clockTime(new Date(row.started_at * 1000))}`;
    const meta = document.createElement("span");
    meta.className = "history-meta";
    meta.textContent = `${row.turns} ${row.turns === 1 ? "turn" : "turns"} · ${clockTime(new Date(row.last_at * 1000))}`;
    button.append(text, meta);
    button.addEventListener("click", async () => {
      $("#menu").close();
      try {
        await openConversation(row.id);
      } catch (error) {
        state.notice = error.message;
        setMode("idle");
      }
    });
    item.append(button);
    list.append(item);
  }
}

function newConversation() {
  stopSpeaking();
  state.turns = [];
  state.conversationId = null;
  storage.remove("ira.today");
  $("#messages").replaceChildren();
  $("#hero").hidden = false;
  state.notice = "";
  setMode("idle");
  if (matchMedia("(hover: hover)").matches) $("#text").focus();
}

// --- turns ------------------------------------------------------------------------

function scrollDown() {
  const scroll = $("#scroll");
  scroll.scrollTop = scroll.scrollHeight;
}

function addTurn(kind, text = "") {
  const template = $(`#turn-${kind}`) || $("#turn-note");
  const li = template.content.firstElementChild.cloneNode(true);
  $(".turn-text", li).textContent = text; // never innerHTML: answers are untrusted text
  $("#messages").append(li);
  $("#hero").hidden = true;
  scrollDown();
  return li;
}

function argumentsText(raw) {
  if (raw === undefined || raw === null || raw === "") return "";
  let value = raw;
  if (typeof raw === "string") {
    try {
      value = JSON.parse(raw);
    } catch {
      return raw;
    }
  }
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return Object.entries(value)
      .map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`)
      .join(", ");
  }
  return JSON.stringify(value);
}

function explain(li, how) {
  const list = $(".how-list", li);
  list.replaceChildren();
  for (const used of how.tools || []) {
    const call = typeof used === "string" ? { name: used } : used;
    const tool = toolFor(call.name);
    const item = document.createElement("li");
    const verb = document.createElement("b");
    verb.textContent = tool && tool.kind === "action" ? "Prepared " : "Looked up ";
    item.append(verb, humanize(call.name));
    const args = argumentsText(call.arguments);
    if (args) item.append(` (${args})`);
    if (tool && tool.description) item.append(`: ${tool.description}`);
    if (tool && tool.kind === "action") item.append(" (needs a PIN)");
    if (call.result !== undefined && call.result !== null && call.result !== "") {
      const data = document.createElement("pre");
      data.className = "how-data";
      const text = typeof call.result === "string" ? call.result : JSON.stringify(call.result, null, 2);
      data.textContent = call.ok === false ? `The tool failed: ${text}` : text;
      item.append(data);
    }
    list.append(item);
  }
  if (!how.tools || !how.tools.length) {
    const item = document.createElement("li");
    item.textContent = "No tools were needed: answered from the conversation.";
    list.append(item);
  }
  const model = document.createElement("li");
  model.textContent = how.model ? `Answered by the model ${how.model}.` : "No model answered.";
  list.append(model);
  $(".how", li).hidden = false;
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

async function send(text, { voice = false, retry = false } = {}) {
  text = text.trim();
  if (!text || state.mode !== "idle" || !state.info) return;
  if (!state.online) return setStatus(new Unreachable().message);
  state.lastInputWasVoice = voice;
  if (!retry) addTurn("user", text);
  const li = addTurn("ira");
  const textEl = $(".turn-text", li);
  const how = { tools: [], model: null };
  let full = "";
  setMode("thinking");
  setStatus("Thinking…");
  try {
    const response = await api("/v1/ask/stream", {
      method: "POST",
      json: { text, conversation_id: state.conversationId },
    });
    if (response.status === 401) {
      li.remove();
      return sessionExpired(text);
    }
    if (!response.ok) throw new Error(await detail(response));
    for await (const event of sseEvents(response)) {
      if (event.type === "start") state.conversationId = event.conversation_id;
      else if (event.type === "tool") {
        how.tools.push({ name: event.name, id: event.id, arguments: event.arguments });
        setStatus(toolPhrase(event.name));
      } else if (event.type === "tool_result") {
        const call =
          how.tools.find((t) => t.id !== undefined && t.id === event.id) ||
          [...how.tools].reverse().find((t) => t.name === event.name && t.result === undefined);
        if (call) {
          call.result = event.result;
          call.ok = event.ok;
        }
      } else if (event.type === "action") actionCard(event.action);
      else if (event.type === "delta") {
        if (!full) {
          setMode("answering");
          setStatus("");
        }
        full += event.text;
        textEl.textContent = full;
        scrollDown();
      } else if (event.type === "error") throw new ModelFailure(event.message);
      else if (event.type === "done") {
        if (event.text) full = event.text;
        textEl.textContent = full;
        how.model = event.model || null;
        how.messageId = event.message_id || null;
      }
    }
    explain(li, how);
    if (typeof IraPersonal !== "undefined" && how.messageId) IraPersonal.answered(li, how.messageId);
    remember({ role: "user", text });
    remember({ role: "ira", text: full, how });
    announce(full);
    if (full && (speakOn() || voice)) await speak(full);
  } catch (error) {
    failTurn(li, error, text);
  } finally {
    if (state.info) {
      setMode("idle");
      scrollDown();
      if (handsFreeOn() && voice && !li.classList.contains("failed")) listen();
    }
  }
}

function failTurn(li, error, text) {
  li.classList.add("failed");
  const textEl = $(".turn-text", li);
  textEl.textContent =
    error instanceof ModelFailure ? `No model could answer right now. ${error.message}` : error.message;
  const retry = document.createElement("button");
  retry.type = "button";
  retry.className = "text-btn retry";
  retry.textContent = "Try again";
  retry.addEventListener("click", () => {
    li.remove();
    send(text, { voice: state.lastInputWasVoice, retry: true });
  });
  li.append(retry);
  announce(textEl.textContent);
}

$("#composer").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = $("#text");
  const text = input.value;
  input.value = "";
  if (typeof IraLive !== "undefined" && IraLive.active()) {
    IraLive.type(text); // typing during a call goes into the call
    return;
  }
  send(text);
});

// --- the PIN card -----------------------------------------------------------------

const KICKER = {
  pending: "Needs a PIN",
  expiring: "Needs a PIN",
  wrong_pin: "Needs a PIN",
  executed: "Done",
  failed: "Failed",
  expired: "Expired",
  cancelled: "Cancelled",
  locked: "Locked",
  already_done: "Already done",
  not_allowed: "Not allowed for your role",
  no_pin: "No PIN set yet",
  needs_pin: "Needs a PIN",
};

function actionCard(action) {
  const card = $("#action-template").content.firstElementChild.cloneNode(true);
  const kicker = $(".action-kicker", card);
  const who = $(".action-who", card);
  const expiry = $(".action-expiry", card);
  const status = $(".action-status", card);
  const form = $(".action-form", card);
  const pin = $(".pin", card);
  $(".action-summary", card).textContent = action.summary;
  // Tier 2: the person who asked says yes; no PIN. Saying "haan" in the chat works too.
  const byYes = action.tier === 2;
  if (byYes) {
    kicker.textContent = "Needs your yes";
    pin.hidden = true;
    pin.required = false;
    $("button[type=submit]", form).textContent = "Yes, do it";
    $(".cancel", form).textContent = "No";
    if (action.can_approve === false) {
      $("button[type=submit]", form).hidden = true;
      who.textContent = "Only the person who asked can say yes.";
      who.hidden = false;
    }
  } else if (Array.isArray(action.confirm_roles) && action.confirm_roles.length) {
    who.textContent = `${listWords(action.confirm_roles)} can confirm.`;
    who.hidden = false;
  }
  if (!byYes && action.can_confirm === false) {
    // This person may still cancel the proposal, but not release it.
    pin.hidden = true;
    $("button[type=submit]", form).hidden = true;
    const role = state.info ? state.info.user.role : "your role";
    who.textContent = `${who.textContent} Not ${role}: ask someone who can.`.trim();
    who.hidden = false;
  }

  const deadline = Date.now() + action.expires_in * 1000;
  let timer = 0;
  const tick = () => {
    const left = Math.max(0, Math.round((deadline - Date.now()) / 1000));
    expiry.textContent = left > 0 ? `Expires in ${mmss(left)}` : "";
    if (left <= 20 && card.dataset.status === "pending") card.dataset.status = "expiring";
    if (byYes && card.dataset.status === "expiring") kicker.textContent = "Needs your yes";
    if (left <= 0) settle("expired", "This action expired. Ask again to re-propose it.");
  };
  const settle = (outcome, message, result) => {
    clearInterval(timer);
    card.dataset.status = outcome;
    kicker.textContent = KICKER[outcome] || outcome;
    for (const el of form.elements) el.disabled = true;
    pin.value = "";
    form.hidden = true;
    expiry.textContent = "";
    status.textContent = message || "";
    if (result !== undefined && result !== null) {
      const details = document.createElement("details");
      details.className = "action-result";
      const summary = document.createElement("summary");
      summary.textContent = "What the action returned";
      const pre = document.createElement("pre");
      pre.textContent = typeof result === "string" ? result : JSON.stringify(result, null, 2);
      details.append(summary, pre);
      card.append(details);
    }
    remember({ role: "note", text: `${KICKER[outcome] || outcome}: ${action.summary}` });
    announce(`${KICKER[outcome] || outcome}. ${message || ""}`);
  };
  const waiting = (on) => {
    for (const el of form.elements) el.disabled = on;
  };
  timer = setInterval(tick, 1000);
  tick();

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const value = pin.value;
    pin.value = ""; // the PIN is never kept
    waiting(true);
    let response;
    try {
      const path = `/v1/actions/${encodeURIComponent(action.id)}/${byYes ? "approve" : "confirm"}`;
      response = await api(path, byYes ? { method: "POST" } : { method: "POST", json: { pin: value } });
    } catch (error) {
      status.textContent = error.message;
      waiting(false);
      return;
    }
    if (response.status === 401) return sessionExpired();
    const outcome = await response.json().catch(() => ({ status: "error", message: response.statusText }));
    if (response.status === 422) {
      status.textContent = "A PIN is 4 to 12 digits.";
      waiting(false);
      pin.focus();
      return;
    }
    switch (outcome.status) {
      case "wrong_pin":
        card.dataset.status = "wrong_pin";
        status.textContent = outcome.message;
        waiting(false);
        pin.focus();
        break;
      case "locked": {
        const until = outcome.locked_until
          ? new Date(outcome.locked_until * 1000)
          : new Date(Date.now() + (outcome.locked_seconds || 0) * 1000);
        settle("locked", `${outcome.message} Try again after ${clockTime(until)}.`);
        break;
      }
      case "no_pin": {
        settle("no_pin", outcome.message || "You have no action PIN yet.");
        const set = document.createElement("button");
        set.type = "button";
        set.className = "text-btn";
        set.textContent = "Set your PIN";
        set.addEventListener("click", openPinForm);
        status.append(" ", set);
        break;
      }
      case "executed":
        settle(
          "executed",
          `Done. ${byYes ? "Approved" : "Confirmed"} by ${state.info.user.email} at ${clockTime(new Date())}.`,
          outcome.result,
        );
        break;
      case "failed":
        settle("failed", outcome.message, outcome.result);
        break;
      case "expired":
      case "cancelled":
      case "already_done":
      case "not_allowed":
      case "needs_pin":
        settle(outcome.status, outcome.message);
        break;
      case "not_found":
        settle("already_done", outcome.message);
        break;
      default:
        status.textContent = outcome.message || outcome.detail || "Something went wrong.";
        waiting(false);
    }
  });

  $(".cancel", form).addEventListener("click", async () => {
    waiting(true);
    try {
      const response = await api(`/v1/actions/${encodeURIComponent(action.id)}/cancel`, { method: "POST" });
      if (response.status === 401) return sessionExpired();
      const outcome = await response.json().catch(() => ({}));
      settle(outcome.status === "already_done" ? "already_done" : "cancelled", outcome.message || "Cancelled. Nothing was changed.");
    } catch (error) {
      status.textContent = error.message;
      waiting(false);
    }
  });

  $("#messages").append(card);
  $("#hero").hidden = true;
  scrollDown();
  if (!byYes) pin.focus({ preventScroll: true });
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
  const { tts, permissions } = state.info;
  stopSpeaking();
  setMode("speaking");
  setStatus("Speaking…", { label: "Stop", onClick: stopSpeaking });
  try {
    if (tts && tts !== "fake" && permissions.includes("voice")) {
      const response = await api("/v1/voice/speak", { method: "POST", json: { text } });
      if (!response.ok) throw new Error(await detail(response));
      await playBlob(await response.blob());
    } else if ("speechSynthesis" in window) {
      await speakWithBrowser(plainForSpeech(text));
    }
  } catch (error) {
    state.notice = `Couldn't speak the reply: ${error.message}`;
  }
}

function playBlob(blob) {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    let context = null;
    let analyser = null;
    let data = null;
    let finished = false;
    const done = () => {
      if (finished) return;
      finished = true;
      URL.revokeObjectURL(url);
      if (context) context.close().catch(() => {});
      if (state.player === player) state.player = null;
      resolve();
    };
    const player = {
      stop() {
        audio.pause();
        done();
      },
    };
    state.player = player;
    try {
      context = new AudioContext();
      const source = context.createMediaElementSource(audio);
      analyser = context.createAnalyser();
      analyser.fftSize = 512;
      source.connect(analyser);
      analyser.connect(context.destination);
      data = new Float32Array(analyser.fftSize);
    } catch {
      /* no meter, but the reply still plays */
    }
    audio.addEventListener("ended", done);
    audio.addEventListener("error", done);
    if (analyser) {
      animateMeter(
        () => {
          analyser.getFloatTimeDomainData(data);
          return rms(data);
        },
        () => state.player === player,
      );
    }
    audio.play().catch(() => {
      state.notice = "Tap the page once to allow sound, then ask again.";
      done();
    });
  });
}

function speakWithBrowser(text) {
  return new Promise((resolve) => {
    speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    let finished = false;
    const done = () => {
      if (finished) return;
      finished = true;
      if (state.player === player) state.player = null;
      resolve();
    };
    const player = {
      stop() {
        speechSynthesis.cancel();
        done();
      },
    };
    state.player = player;
    utterance.addEventListener("end", done);
    utterance.addEventListener("error", done);
    speechSynthesis.speak(utterance);
  });
}

function stopSpeaking() {
  const player = state.player;
  state.player = null;
  if (player) player.stop();
}

// --- voice in: AudioWorklet -> level meter -> 16 kHz mono WAV -----------------------

// The browser's own recognition, when the server allows it: always ("prefer"), or
// when the server has no speech-to-text ("fallback"). It sends text, never audio, to
// Ira; the browser itself may send the audio to its maker (Chrome: Google).
function browserRecognition() {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const policy = state.info.browser_stt || "off";
  if (!Recognition || policy === "off") return null;
  return policy === "prefer" || !state.info.stt ? Recognition : null;
}

function voiceProblem() {
  const { permissions, stt } = state.info;
  if (!permissions.includes("voice")) return "Your role can't use the microphone.";
  const inBrowser = browserRecognition();
  if (!stt && !inBrowser) return "Speech-to-text isn't set up on this server, and this browser can't recognise speech. You can type.";
  if (!window.isSecureContext) return "The microphone needs a secure (HTTPS) address.";
  if (inBrowser) return null;
  if (!navigator.mediaDevices || !window.AudioWorkletNode) return "This browser can't record audio.";
  return null;
}

const RECOGNITION_ERRORS = {
  "not-allowed": "The microphone is blocked. Allow it for this site in your browser's site settings, then tap the mic again.",
  "service-not-allowed": "This browser won't recognise speech here. You can type.",
  "audio-capture": "No microphone was found on this device.",
  network: "The browser couldn't reach its speech service. Check the connection, or type.",
  "language-not-supported": "This browser can't recognise that language. Change your languages under Your assistant, or type.",
};

function startBrowserListening(Recognition) {
  const recognizer = new Recognition();
  recognizer.lang = state.info.mic_language || "en-IN";
  recognizer.interimResults = true;
  recognizer.continuous = false;
  recognizer.maxAlternatives = 1;
  const heard = { final: "", error: "", cancelled: false };
  recognizer.onresult = (event) => {
    let interim = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const result = event.results[i];
      if (result.isFinal) heard.final += result[0].transcript;
      else interim += result[0].transcript;
    }
    if (state.recognizer === recognizer) $("#listen-label").textContent = (heard.final + interim).trim() || "Listening…";
  };
  recognizer.onerror = (event) => {
    if (event.error === "aborted") return;
    heard.error = event.error === "no-speech" ? "I didn't hear anything. Tap the mic to try again." : RECOGNITION_ERRORS[event.error] || `Voice failed: ${event.error}.`;
  };
  recognizer.onend = () => {
    if (state.recognizer !== recognizer) return;
    state.recognizer = null;
    const text = heard.final.trim();
    if (heard.cancelled) return;
    if (text) {
      setMode("idle");
      send(text, { voice: true });
      return;
    }
    state.notice = heard.error || "I didn't catch that. Tap the mic to try again.";
    setMode("idle");
  };
  recognizer.cancel = () => {
    heard.cancelled = true;
    recognizer.abort();
  };
  state.recognizer = recognizer;
  recognizer.start();
}

function micMessage(error) {
  const name = error && error.name;
  if (name === "NotAllowedError" || name === "SecurityError") {
    return "The microphone is blocked. Allow it for this site in your browser's site settings (the icon next to the address), then tap the mic again.";
  }
  if (name === "NotFoundError" || name === "OverconstrainedError") return "No microphone was found on this device.";
  if (name === "NotReadableError") return "Another app is using the microphone.";
  return `The microphone didn't start: ${(error && error.message) || name || "unknown error"}.`;
}

async function listen() {
  if (!state.info || !state.info.permissions.includes("ask")) return;
  const problem = voiceProblem();
  if (problem) return setStatus(problem);
  if (state.mode !== "idle") return;
  stopSpeaking();
  const inBrowser = browserRecognition();
  try {
    if (inBrowser) startBrowserListening(inBrowser);
    else await startRecording();
  } catch (error) {
    return setStatus(micMessage(error));
  }
  $("#handsfree-chip").hidden = !handsFreeOn();
  $("#listen-label").textContent = "Listening…";
  setMode("listening");
  setStatus("");
}

async function startRecording() {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
  });
  const context = new AudioContext();
  await context.audioWorklet.addModule("/recorder-worklet.js");
  const source = context.createMediaStreamSource(stream);
  const node = new AudioWorkletNode(context, "recorder");
  const rec = { stream, context, node, chunks: [], started: Date.now(), lastLoud: 0, spoke: false, level: 0 };
  node.port.onmessage = (event) => {
    const samples = event.data;
    rec.chunks.push(samples);
    rec.level = rms(samples);
    const now = Date.now();
    if (rec.level > SPEECH_LEVEL) {
      rec.spoke = true;
      rec.lastLoud = now;
    }
    if (state.recorder !== rec || state.mode !== "listening") return;
    if (rec.spoke && now - rec.lastLoud > SILENCE_MS) finishListening();
    else if (!rec.spoke && now - rec.started > NO_SPEECH_MS) cancelListening("I didn't hear anything. Tap the mic to try again.");
    else if (now - rec.started > MAX_RECORD_MS) finishListening();
  };
  source.connect(node);
  state.recorder = rec;
  animateMeter(
    () => rec.level,
    () => state.recorder === rec,
  );
}

async function stopRecording() {
  const rec = state.recorder;
  state.recorder = null;
  if (!rec) return null;
  rec.node.disconnect();
  rec.stream.getTracks().forEach((track) => track.stop());
  const rate = rec.context.sampleRate;
  await rec.context.close();
  return encodeWav(downsample(rec.chunks, rate, 16000), 16000);
}

async function finishListening() {
  if (state.recognizer && state.mode === "listening") {
    setMode("transcribing");
    $("#listen-label").textContent = "Transcribing…";
    state.recognizer.stop(); // its end event sends what it heard
    return;
  }
  if (!state.recorder || state.mode !== "listening") return;
  setMode("transcribing");
  $("#listen-label").textContent = "Transcribing…";
  let wav;
  try {
    wav = await stopRecording();
  } catch {
    return setMode("idle");
  }
  try {
    const response = await api("/v1/voice/transcribe", {
      method: "POST",
      body: wav,
      headers: { "Content-Type": "audio/wav" },
    });
    if (response.status === 401) return sessionExpired();
    if (!response.ok) throw new Error(await detail(response));
    const { text } = await response.json();
    setMode("idle");
    if (text && text.trim()) send(text, { voice: true });
    else setStatus("I didn't catch that. Tap the mic to try again.");
  } catch (error) {
    state.notice = `Voice failed: ${error.message}`;
    setMode("idle");
  }
}

async function cancelListening(message) {
  if (state.recognizer) {
    const recognizer = state.recognizer;
    state.recognizer = null;
    recognizer.cancel();
  }
  try {
    await stopRecording();
  } catch {
    /* already stopped */
  }
  state.notice = message || "";
  setMode("idle");
}

function rms(samples) {
  let sum = 0;
  for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
  return samples.length ? Math.sqrt(sum / samples.length) : 0;
}

const bars = {
  hero: [...document.querySelectorAll("#hero-mic .bar")],
  mic: [...document.querySelectorAll("#mic .bar")],
  meter: [...document.querySelectorAll("#listen .bar")],
  call: [...document.querySelectorAll("#call-bar .bar")],
};

function setBars(level) {
  for (const set of Object.values(bars)) {
    set.forEach((bar, i) => {
      const max = 30 / REST_HEIGHTS[i];
      const weight = [0.8, 1, 0.9, 0.7][i];
      const scale = 1 + (max - 1) * Math.min(1, level * weight);
      bar.style.transform = level > 0.01 ? `scaleY(${scale.toFixed(3)})` : "";
    });
  }
}

function animateMeter(getLevel, alive) {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  let smooth = 0;
  const frame = () => {
    if (!alive()) return setBars(0);
    const level = Math.min(1, getLevel() * 8);
    smooth = level > smooth ? level : smooth * 0.85; // quick to rise, slow to settle
    setBars(smooth);
    requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
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

for (const button of [$("#hero-mic"), $("#mic")]) {
  button.addEventListener("click", () => {
    if (state.mode === "listening") finishListening();
    else if (state.mode === "speaking") {
      stopSpeaking();
      listen();
    } else listen();
  });
}
$("#listen-done").addEventListener("click", finishListening);
$("#listen-cancel").addEventListener("click", () => cancelListening(""));
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && state.mode === "listening") cancelListening("");
});

// --- connection -------------------------------------------------------------------

function setOnline(online) {
  state.online = online;
  updateBanner();
  if (state.info) $("#send").disabled = !online || state.mode !== "idle" || $("#text").disabled;
}
window.addEventListener("online", () => setOnline(true));
window.addEventListener("offline", () => setOnline(false));

// --- boot -------------------------------------------------------------------------

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}
start();
