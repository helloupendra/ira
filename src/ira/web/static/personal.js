// Your own Ira: your devices, your assistant's name and languages, what Ira did, and your
// data. Also listens for your devices' events ("the upload finished") and says them.
// Loaded after app.js, whose helpers ($, api, detail, state, addTurn, speak...) it uses.
// Everything shown here is built with textContent: nothing from the server is HTML.
"use strict";

const IraPersonal = (() => {
  const LANGUAGE_NAMES = { en: "English", hi: "Hindi", hinglish: "Hinglish" };
  const REPLY_NAMES = { auto: "The language I speak", en: "English", hi: "Hindi", hinglish: "Hinglish" };
  const TIER_NAMES = ["read", "small change", "needed your yes", "needed your PIN"];
  const OUTCOME_NAMES = {
    ok: "done",
    error: "failed",
    proposed: "waited for you",
    refused: "refused",
    executed: "done after you confirmed",
    failed: "failed after you confirmed",
  };
  let events = null;
  let pairingTimer = 0;

  // --- small DOM helpers ----------------------------------------------------------

  function el(tag, props = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
      if (value === undefined || value === null || value === false) continue;
      if (key === "text") node.textContent = value;
      else if (key === "className") node.className = value;
      else if (key.startsWith("on")) node.addEventListener(key.slice(2).toLowerCase(), value);
      else if (key === "checked" || key === "disabled" || key === "hidden" || key === "required") node[key] = Boolean(value);
      else if (key === "value") node.value = value;
      else node.setAttribute(key, value === true ? "" : String(value));
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) continue;
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  function when(seconds) {
    if (!seconds) return "never";
    const ago = Date.now() / 1000 - seconds;
    if (ago < 60) return "just now";
    if (ago < 3600) return `${Math.round(ago / 60)} min ago`;
    if (ago < 86400) return `${Math.round(ago / 3600)} h ago`;
    return new Date(seconds * 1000).toLocaleDateString();
  }

  function words(name) {
    return String(name || "").replace(/_/g, " ");
  }

  const TOOL_WORDS = {
    chrome_list_tabs: "Listed your Chrome tabs",
    chrome_read_tab: "Read a Chrome tab",
    chrome_watch_tab: "Watched a Chrome tab",
    files_find: "Looked for files",
    file_read: "Read a file",
    file_open: "Opened a file",
    screen_read: "Read your screen",
    remember_person: "Remembered someone",
    forget_person: "Forgot someone",
    remind_me: "Set a reminder",
    web_search: "Searched the web",
    news_search: "Searched the news",
  };

  async function call(path, options = {}) {
    const response = await api(path, options);
    if (response.status === 401) {
      close();
      sessionExpired();
      throw new Error("Your session expired.");
    }
    if (!response.ok) throw new Error(await detail(response));
    return response.status === 204 ? null : response.json();
  }

  function pinField(label = "Your action PIN") {
    return el(
      "label",
      {},
      label,
      el("input", {
        name: "pin",
        type: "password",
        inputmode: "numeric",
        pattern: "[0-9]{4,12}",
        minlength: "4",
        maxlength: "12",
        autocomplete: "off",
        required: true,
      }),
    );
  }

  // --- the panel sheet --------------------------------------------------------------

  const PANELS = {
    devices: { title: "Your devices", render: renderDevices },
    assistant: { title: "Your assistant", render: renderAssistant },
    activity: { title: "What Ira did", render: renderActivity },
    data: { title: "Your data", render: renderData },
    knows: { title: "What Ira knows about you", render: renderKnows },
    connections: { title: "Your connections", render: renderConnections },
    businesses: { title: "Your businesses", render: renderBusinesses },
  };

  function open(name) {
    const panel = PANELS[name];
    if (!panel) return;
    $("#menu").close();
    $("#panel-title").textContent = panel.title;
    const body = $("#panel-body");
    body.replaceChildren(el("p", { className: "muted", text: "Loading…" }));
    const dialog = $("#panel");
    if (!dialog.open) dialog.showModal();
    panel.render(body).catch((error) => {
      body.replaceChildren(el("p", { className: "error", role: "alert", text: error.message }));
    });
  }

  function close() {
    clearInterval(pairingTimer);
    const dialog = $("#panel");
    if (dialog.open) dialog.close();
  }

  // --- devices ----------------------------------------------------------------------

  async function renderDevices(body) {
    const [devices, downloads] = await Promise.all([
      call("/v1/me/devices"),
      call("/v1/downloads").catch(() => []),
    ]);
    const list = el("ul", { className: "cards", "aria-label": "Your devices" });
    if (!devices.length) {
      list.append(el("li", { className: "muted", text: "No devices yet. Add your Mac to let Ira read and watch Chrome tabs when you ask." }));
    }
    for (const device of devices) list.append(deviceCard(device, body));
    body.replaceChildren(
      el("p", { className: "muted", text: "A device works for you alone. Ira uses only the skills you switch on, and only when you ask." }),
      list,
      addDeviceForm(body, downloads),
    );
  }

  function deviceCard(device, body) {
    const status = device.connected ? "Connected" : `Last seen ${when(device.last_seen_at)}`;
    const card = el(
      "li",
      { className: "card" },
      el("p", { className: "card-title" }, device.label, " ", el("span", { className: device.connected ? "chip ok" : "chip", text: status })),
      el("p", { className: "muted small", text: `${device.kind === "mac" ? "Mac" : "Android phone"}${device.version ? ` · version ${device.version}` : ""}` }),
    );
    for (const skill of device.skills) {
      const pin = pinField("Your PIN, to switch it on");
      pin.hidden = true;
      const toggle = el("input", { type: "checkbox", checked: skill.on });
      const error = el("p", { className: "error", role: "alert" });
      const confirm = el("button", { type: "submit", className: "btn btn-primary", text: "Switch on", hidden: true });
      const form = el(
        "form",
        { className: "skill" },
        el("label", { className: "switch" }, toggle, el("span", { text: skill.description })),
        pin,
        confirm,
        error,
      );
      const save = async (pinValue) => {
        const wanted = device.skills.filter((s) => (s.name === skill.name ? toggle.checked : s.on)).map((s) => s.name);
        await call(`/v1/me/devices/${device.id}`, { method: "PATCH", json: { skills: wanted, pin: pinValue || undefined } });
        await renderDevices(body);
      };
      toggle.addEventListener("change", () => {
        error.textContent = "";
        if (toggle.checked && !skill.on) {
          pin.hidden = false; // a new grant: Tier 3, your PIN
          confirm.hidden = false;
          $("input", pin).focus();
        } else {
          save().catch((problem) => (error.textContent = problem.message));
        }
      });
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        const value = $("input", pin).value;
        $("input", pin).value = "";
        save(value).catch((problem) => (error.textContent = problem.message));
      });
      card.append(form);
    }
    if (device.tools.length) {
      card.append(
        el(
          "details",
          { className: "small" },
          el("summary", { text: `${device.tools.length} tools it offers` }),
          el("ul", {}, device.tools.map((tool) => el("li", { text: `${words(tool.name)} (${TIER_NAMES[tool.tier] || tool.tier})${tool.on ? "" : " — off"}` }))),
        ),
      );
    }
    const remove = el("button", {
      type: "button",
      className: "text-btn danger",
      text: "Remove this device",
      onClick: async () => {
        if (!window.confirm(`Remove ${device.label}? Its token stops working at once.`)) return;
        try {
          await call(`/v1/me/devices/${device.id}`, { method: "DELETE" });
          await renderDevices(body);
        } catch (problem) {
          remove.textContent = problem.message;
        }
      },
    });
    card.append(remove);
    return card;
  }

  function addDeviceForm(body, downloads) {
    const kind = el("select", { name: "kind" }, el("option", { value: "mac", text: "Mac (reads Chrome tabs)" }), el("option", { value: "android", text: "Android phone" }));
    const chrome = el("input", { type: "checkbox", name: "skill-chrome", checked: true });
    const chromeRow = el("label", { className: "switch" }, chrome, el("span", { text: "Chrome: list your tabs, read the one you ask about, and tell you when it finishes" }));
    kind.addEventListener("change", () => (chromeRow.hidden = kind.value !== "mac"));
    const error = el("p", { className: "error", role: "alert" });
    const form = el(
      "form",
      { className: "stack add-device" },
      el("h3", { text: "Add a device" }),
      el("label", {}, "Kind", kind),
      el("label", {}, "Name", el("input", { name: "label", maxlength: "60", placeholder: "My Mac" })),
      chromeRow,
      pinField("Your action PIN (a new device is a new permission)"),
      el("button", { type: "submit", className: "btn btn-primary", text: "Make a pairing code" }),
      error,
    );
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      error.textContent = "";
      const data = new FormData(form);
      $("input[name=pin]", form).value = "";
      const skills = data.get("kind") === "mac" && chrome.checked ? ["chrome"] : [];
      try {
        const pairing = await call("/v1/me/devices/pairing", {
          method: "POST",
          json: { kind: data.get("kind"), label: data.get("label") || null, skills, pin: data.get("pin") },
        });
        form.replaceWith(pairingCard(pairing, body, downloads));
      } catch (problem) {
        error.textContent = problem.message;
      }
    });
    return form;
  }

  function copyButton(text, label, className = "text-btn") {
    const button = el("button", { type: "button", className, text: label });
    button.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(text);
        button.textContent = "Copied";
      } catch {
        button.textContent = "Copy did not work: select it instead";
      }
    });
    return button;
  }

  function pairingCard(pairing, body, downloads) {
    const left = el("p", { className: "muted small", role: "status" });
    const mac = downloads.find((d) => d.name === "ira-mac.zip");
    const steps =
      pairing.kind === "mac"
        ? el(
            "ol",
            { className: "steps" },
            el("li", {}, "Download ", mac ? el("a", { href: mac.url, text: "the Ira companion for Mac" }) : "the Ira companion for Mac", " and open the zip."),
            el("li", {}, "In Terminal, run: ", el("code", { text: "cd ~/Downloads/ira-mac && ./install.sh" })),
            el("li", { text: "When it asks, paste the pairing link you copied above." }),
            el("li", {}, "In Chrome, open ", el("code", { text: "chrome://extensions" }), ", switch on Developer mode, click Load unpacked, and choose the folder the installer names."),
            el("li", {}, "Ask Ira: ", el("q", { text: "Chrome mein kaunse tabs khule hain?" })),
          )
        : el("p", { className: "muted", text: "Open the Ira app on your phone and scan this code." });
    const card = el(
      "div",
      { className: "card pairing" },
      el("h3", { text: `Pair ${pairing.label}` }),
      el("div", { className: "row" }, copyButton(pairing.pair_url, "Copy the pairing link", "btn btn-primary")),
      el("p", { className: "muted", text: "Paste the link when the installer asks. Or type this code:" }),
      el("p", { className: "pair-code", text: pairing.code }),
      el("img", { className: "qr", src: pairing.qr_svg, alt: `QR code for pairing ${pairing.label}`, width: "180", height: "180" }),
      left,
      steps,
    );
    if (/^http:\/\/(127\.0\.0\.1|localhost)/.test(pairing.server) && pairing.kind !== "mac") {
      card.append(el("p", { className: "note", text: "This server is only reachable on this computer. A phone needs its public address (public_url)." }));
    }
    clearInterval(pairingTimer);
    const tick = async () => {
      const seconds = Math.max(0, Math.round(pairing.expires_at - Date.now() / 1000));
      left.textContent = seconds ? `Waiting for the device… the code works for ${mmss(seconds)} more, once.` : "This code expired. Make a new one.";
      if (!seconds) return clearInterval(pairingTimer);
      try {
        const state = await call(`/v1/me/devices/pairings/${encodeURIComponent(pairing.id)}`);
        if (state.state === "paired") {
          clearInterval(pairingTimer);
          await renderDevices(body);
          body.prepend(el("p", { className: "note ok", role: "status", text: `${pairing.label} is paired.` }));
        }
      } catch {
        /* keep waiting */
      }
    };
    pairingTimer = setInterval(tick, 3000);
    tick();
    return card;
  }

  // --- your assistant ---------------------------------------------------------------

  async function renderAssistant(body) {
    const [settings, grants] = await Promise.all([call("/v1/me/settings"), call("/v1/me/grants")]);
    const error = el("p", { className: "error", role: "alert" });
    const saved = el("p", { className: "muted small", role: "status" });
    const languages = settings.language_options.map((code) =>
      el("label", { className: "switch" }, el("input", { type: "checkbox", name: "languages", value: code, checked: settings.languages.includes(code) }), el("span", { text: LANGUAGE_NAMES[code] || code })),
    );
    const reply = el("select", { name: "reply_language" }, settings.reply_language_options.map((code) => el("option", { value: code, text: REPLY_NAMES[code] || code })));
    reply.value = settings.reply_language;
    const form = el(
      "form",
      { className: "stack" },
      el("label", {}, "What you call your assistant", el("input", { name: "assistant_name", maxlength: "32", value: settings.assistant_name.value })),
      el("label", {}, "Wake phrase (for your phone)", el("input", { name: "wake_phrase", maxlength: "40", value: settings.wake_phrase.value })),
      el("fieldset", { className: "stack-tight" }, el("legend", { text: "I speak" }), languages),
      el("label", {}, "Reply in", reply),
      el("button", { type: "submit", className: "btn btn-primary", text: "Save" }),
      saved,
      error,
    );
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      error.textContent = "";
      const data = new FormData(form);
      try {
        const updated = await call("/v1/me/settings", {
          method: "PATCH",
          json: {
            assistant_name: data.get("assistant_name") || null,
            wake_phrase: data.get("wake_phrase") || null,
            languages: data.getAll("languages"),
            reply_language: data.get("reply_language"),
          },
        });
        setName(updated.assistant_name.value);
        saved.textContent = "Saved.";
      } catch (problem) {
        error.textContent = problem.message;
      }
    });
    body.replaceChildren(form, webSearch(settings.web_search, body), grantList(grants, body));
  }

  function webSearch(state, body) {
    const readiness = [];
    if (!state.web_ready) readiness.push("this server has no web search key yet (its owner adds one)");
    if (!state.news_ready) readiness.push("it reads no news feeds yet");
    const toggle = el("input", { type: "checkbox", checked: state.on });
    const pin = pinField("Your PIN, to switch it on");
    pin.hidden = true;
    const confirm = el("button", { type: "submit", className: "btn btn-primary", text: "Switch on", hidden: true });
    const error = el("p", { className: "error", role: "alert" });
    const form = el(
      "form",
      { className: "stack card" },
      el("h3", { text: "Web and news search" }),
      el("label", { className: "switch" }, toggle, el("span", { text: "Let Ira search the web and the news for me. My questions go to the search service." })),
      readiness.length ? el("p", { className: "muted small", text: `Note: ${readiness.join(", and ")}.` }) : null,
      pin,
      confirm,
      error,
    );
    const save = async (value) => {
      await call("/v1/me/settings", { method: "PATCH", json: { web_search: toggle.checked, pin: value || undefined } });
      await renderAssistant(body);
    };
    toggle.addEventListener("change", () => {
      error.textContent = "";
      if (toggle.checked && !state.on) {
        pin.hidden = false;
        confirm.hidden = false;
        $("input", pin).focus();
      } else {
        save().catch((problem) => (error.textContent = problem.message));
      }
    });
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const value = $("input", pin).value;
      $("input", pin).value = "";
      save(value).catch((problem) => (error.textContent = problem.message));
    });
    return form;
  }

  function grantList(grants, body) {
    const list = el("ul", { className: "cards" });
    if (!grants.length) list.append(el("li", { className: "muted", text: "Nothing yet." }));
    for (const grant of grants) {
      list.append(
        el(
          "li",
          { className: "card grant" },
          el("p", {}, el("strong", { text: grant.device ? `${words(grant.skill)} on ${grant.device}` : "Web and news search" })),
          el("p", { className: "muted small", text: grant.description }),
          el("button", {
            type: "button",
            className: "btn btn-ghost",
            text: "Turn off",
            onClick: async () => {
              await call(`/v1/me/grants/${encodeURIComponent(grant.id)}`, { method: "DELETE" });
              await renderAssistant(body);
            },
          }),
        ),
      );
    }
    return el("section", { className: "stack" }, el("h3", { text: "What you allowed Ira to use" }), list);
  }

  // --- what Ira did -----------------------------------------------------------------

  async function renderActivity(body) {
    const list = el("ol", { className: "activity" });
    const more = el("button", { type: "button", className: "btn btn-ghost", text: "Older", hidden: true });
    let before = null;
    const load = async () => {
      const response = await api(`/v1/me/activity?limit=50${before ? `&before_id=${before}` : ""}`);
      if (!response.ok) throw new Error(await detail(response));
      const rows = await response.json();
      for (const row of rows) {
        list.append(
          el(
            "li",
            {},
            el("span", { className: "activity-when", text: new Date(row.at * 1000).toLocaleString([], { dateStyle: "short", timeStyle: "short" }) }),
            el("span", { text: `${TOOL_WORDS[row.tool] || words(row.tool)}${row.device ? ` on ${row.device}` : ""}` }),
            el("span", { className: "muted small", text: `${TIER_NAMES[row.tier] || ""} · ${OUTCOME_NAMES[row.outcome] || row.outcome}${row.seconds !== null ? ` · ${row.seconds.toFixed(1)} s` : ""}` }),
          ),
        );
        before = row.id;
      }
      more.hidden = response.headers.get("X-Has-More") !== "true";
      if (!list.children.length) list.append(el("li", { className: "muted", text: "Nothing yet." }));
    };
    more.addEventListener("click", () => load().catch((error) => (more.textContent = error.message)));
    body.replaceChildren(
      el("p", { className: "muted", text: "Every tool Ira used for you, and every action that ran. Only what, where and when: never what it read." }),
      list,
      more,
    );
    await load();
  }

  // --- your data --------------------------------------------------------------------

  async function renderData(body) {
    const error = el("p", { className: "error", role: "alert" });
    const done = el("p", { className: "note", role: "status", hidden: true });
    const form = el(
      "form",
      { className: "stack card" },
      el("h3", { text: "Delete my data" }),
      el("p", { className: "muted small", text: "Deletes your conversations, devices (they disconnect), their events, what Ira did, and your settings. Your account stays; the owner can remove it." }),
      el("label", {}, "Your password", el("input", { name: "password", type: "password", autocomplete: "current-password", required: true })),
      el("label", { className: "switch" }, el("input", { type: "checkbox", name: "sure", required: true }), el("span", { text: "Yes, delete it. This cannot be undone." })),
      el("button", { type: "submit", className: "btn btn-danger", text: "Delete my data" }),
      error,
      done,
    );
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      error.textContent = "";
      const password = new FormData(form).get("password");
      $("input[name=password]", form).value = "";
      try {
        const gone = await call("/v1/me/data/delete", { method: "POST", json: { password } });
        done.textContent = `Deleted ${gone.conversations} conversations, ${gone.devices} devices, ${gone.events} events and ${gone.activity} activity rows.`;
        done.hidden = false;
        storage.remove("ira.today");
        state.turns = [];
        state.conversationId = null;
        $("#messages").replaceChildren();
      } catch (problem) {
        error.textContent = problem.message;
      }
    });
    body.replaceChildren(
      el(
        "div",
        { className: "stack card" },
        el("h3", { text: "Export my data" }),
        el("p", { className: "muted small", text: "A file with your conversations, devices, events, settings and what Ira did. Never a password, PIN or token." }),
        el("a", { className: "btn btn-ghost", href: "/v1/me/export", download: "", text: "Download my data" }),
      ),
      form,
    );
  }

  // --- your devices' events -----------------------------------------------------------

  function startEvents() {
    if (events || !state.info || !state.info.permissions.includes("ask")) return;
    loadLearning();
    ensureTimezone();
    events = new EventSource("/v1/me/events/stream");
    events.addEventListener("message", (message) => {
      let event;
      try {
        event = JSON.parse(message.data);
      } catch {
        return;
      }
      const joint = /[.?!:]$/.test(event.title) ? " " : ". ";
      const text = event.text && event.text !== event.title ? `${event.title}${joint}${event.text}` : event.title;
      remember({ role: "note", text });
      const li = addTurn("note", text);
      if (event.event === "learning_question" && event.data && event.data.learning_id) askAbout(li, event.data.learning_id);
      announce(text);
      if (speakOn() && (state.mode === "idle" || state.mode === "answering")) speak(text);
    });
  }

  // A learning question in the chat: answer it there.
  function askAbout(li, learningId) {
    const path = `/v1/me/learnings/${encodeURIComponent(learningId)}`;
    const row = el("div", { className: "row" });
    const answer = (what, said) => async () => {
      try {
        await call(`${path}/${what}`, { method: "POST" });
        row.replaceChildren(el("span", { className: "muted small", text: said }));
      } catch (problem) {
        row.replaceChildren(el("span", { className: "error small", text: problem.message }));
      }
    };
    row.append(
      el("button", { type: "button", className: "btn btn-primary", text: "Yes, remember", onClick: answer("approve", "Remembered.") }),
      el("button", { type: "button", className: "btn btn-ghost", text: "No", onClick: answer("reject", "I won't ask again.") }),
    );
    li.append(row);
  }

  function stopEvents() {
    if (events) events.close();
    events = null;
  }

  // --- what Ira knows about you ---------------------------------------------------

  const SOURCE_NAMES = {
    phone: "My phone, when it says I reached or left a place I named",
    conversation: "What I tell Ira about where I'm going",
    feedback: "My thumbs on Ira's answers",
  };
  const STATUS_NAMES = {
    proposed: "still checking",
    ready: "waiting for your answer",
    asked: "waiting for your answer",
    changed: "seems to have changed",
    active: "remembered",
    rejected: "you said no",
    faded: "not seen lately",
  };
  const KEEP_DAYS = [30, 60, 90, 180, 365];
  let learning = null; // your learning settings, for thumbs on answers

  async function loadLearning() {
    try {
      learning = await call("/v1/me/learning");
    } catch {
      learning = null;
    }
    return learning;
  }

  async function renderKnows(body) {
    const view = await loadLearning();
    if (!view) throw new Error("Learning isn't available on this server.");
    body.replaceChildren(
      learningSwitches(view, body),
      learningsList(view, body),
      placesList(view, body),
      remindersList(view, body),
      phoneSection(view, body),
    );
  }

  function learningSwitches(view, body) {
    const on = el("input", { type: "checkbox", name: "on", checked: view.on });
    const sources = view.sources.map((source) =>
      el("label", { className: "switch" }, el("input", { type: "checkbox", name: "sources", value: source.name, checked: source.on }), el("span", { text: SOURCE_NAMES[source.name] || source.description })),
    );
    const macs = view.macs.length
      ? view.macs.map((mac) => el("li", { text: `${mac.label}: ${mac.on ? "its lock, sleep and network are noticed" : "off (switch its routine on under Your devices)"}` }))
      : [el("li", { className: "muted", text: "No Mac paired. A Mac's routine is switched on under Your devices." })];
    const days = el("select", { name: "days" }, KEEP_DAYS.map((n) => el("option", { value: String(n), text: `${n} days` })));
    days.value = String(view.days);
    const nudges = el("input", { type: "checkbox", name: "nudges", checked: view.nudges });
    const pin = pinField("Your PIN, to switch something on");
    const error = el("p", { className: "error", role: "alert" });
    const saved = el("p", { className: "muted small", role: "status" });
    const form = el(
      "form",
      { className: "stack card" },
      el("p", { className: "muted small", text: "Off until you switch it on. Ira only notices what you choose here, keeps it for as long as you say, and asks you before it remembers anything." }),
      el("label", { className: "switch" }, on, el("span", { text: "Let Ira learn my routine" })),
      el("fieldset", { className: "stack-tight" }, el("legend", { text: "From" }), sources, el("ul", { className: "small" }, macs)),
      el("label", {}, "Keep what it noticed for", days),
      el("label", { className: "switch" }, nudges, el("span", { text: "Nudge me 15 minutes before a routine I approved" })),
      pin,
      el("button", { type: "submit", className: "btn btn-primary", text: "Save" }),
      saved,
      error,
    );
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      error.textContent = "";
      const data = new FormData(form);
      const value = $("input", pin).value;
      $("input", pin).value = "";
      try {
        await call("/v1/me/learning", {
          method: "PATCH",
          json: { on: on.checked, sources: data.getAll("sources"), days: Number(data.get("days")), nudges: nudges.checked, pin: value || undefined },
        });
        await renderKnows(body);
        body.prepend(el("p", { className: "note ok", role: "status", text: "Saved." }));
      } catch (problem) {
        error.textContent = problem.message;
      }
    });
    return el("section", { className: "stack" }, el("h3", { text: "What Ira may notice" }), form);
  }

  function learningsList(view, body) {
    const list = el("ul", { className: "cards" });
    const shown = view.learnings.filter((item) => item.status !== "rejected");
    if (!shown.length) list.append(el("li", { className: "muted", text: view.on ? "Nothing yet. Ira needs at least 8 days over two weeks before it suggests a routine." : "Nothing: learning is off." }));
    const act = async (path, method = "POST", json) => {
      await call(path, { method, json });
      await renderKnows(body);
    };
    for (const item of shown) {
      const path = `/v1/me/learnings/${encodeURIComponent(item.id)}`;
      const evidence = item.evidence || {};
      const facts = evidence.days ? `Seen on ${evidence.days} days` : "";
      const error = el("p", { className: "error", role: "alert" });
      const guard = (work) => () => work().catch((problem) => (error.textContent = problem.message));
      const actions = el("div", { className: "row" });
      if (["ready", "asked", "changed"].includes(item.status)) {
        actions.append(
          el("button", { type: "button", className: "btn btn-primary", text: "Yes, remember", onClick: guard(() => act(`${path}/approve`)) }),
          el("button", { type: "button", className: "btn btn-ghost", text: "No", onClick: guard(() => act(`${path}/reject`)) }),
        );
      }
      if (item.status === "active") {
        actions.append(
          el("button", {
            type: "button",
            className: "btn btn-ghost",
            text: "Reword",
            onClick: () => {
              const input = el("input", { value: item.text, maxlength: "300", "aria-label": "Reword it" });
              const save = el("button", { type: "button", className: "btn btn-primary", text: "Save", onClick: guard(() => act(path, "PATCH", { text: input.value })) });
              actions.replaceChildren(input, save);
              input.focus();
            },
          }),
        );
      }
      actions.append(
        el("button", {
          type: "button",
          className: "text-btn danger",
          text: "Forget it",
          onClick: guard(async () => {
            if (!confirm("Forget this, and what Ira noticed for it?")) return;
            await act(path, "DELETE");
          }),
        }),
      );
      list.append(
        el(
          "li",
          { className: "card" },
          el("p", { text: item.text }),
          el("p", { className: "muted small", text: [STATUS_NAMES[item.status] || item.status, facts].filter(Boolean).join(" · ") }),
          actions,
          error,
        ),
      );
    }
    const look = el("button", {
      type: "button",
      className: "btn btn-ghost",
      text: "Look for patterns now",
      disabled: !view.on,
      onClick: async () => {
        await call("/v1/me/learning/refresh", { method: "POST" });
        await renderKnows(body);
      },
    });
    return el("section", { className: "stack" }, el("h3", { text: "What Ira knows" }), list, look);
  }

  function placesList(view, body) {
    const list = el("ul", { className: "cards" });
    if (!view.networks.length) list.append(el("li", { className: "muted", text: "No networks yet. With a Mac's routine on, the networks it joins show up here, as codes only, for you to name." }));
    for (const network of view.networks) {
      const path = `/v1/me/networks/${encodeURIComponent(network.fingerprint)}`;
      const input = el("input", { value: network.label || "", maxlength: "40", placeholder: "Office, Home", "aria-label": "Name this network" });
      const error = el("p", { className: "error", role: "alert" });
      const form = el(
        "form",
        { className: "row" },
        input,
        el("button", { type: "submit", className: "btn btn-ghost", text: "Name it" }),
        el("button", {
          type: "button",
          className: "text-btn danger",
          text: "Forget",
          onClick: async () => {
            await call(path, { method: "DELETE" });
            await renderKnows(body);
          },
        }),
      );
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        try {
          await call(path, { method: "PUT", json: { label: input.value } });
          await renderKnows(body);
        } catch (problem) {
          error.textContent = problem.message;
        }
      });
      list.append(
        el(
          "li",
          { className: "card" },
          el("p", {}, el("strong", { text: network.label || "A network without a name" })),
          el("p", { className: "muted small", text: `Code ${network.fingerprint.slice(0, 8)}${network.device ? `, from ${network.device}` : ""}, last seen ${when(network.last_seen)}` }),
          form,
          error,
        ),
      );
    }
    return el("section", { className: "stack" }, el("h3", { text: "Places" }), list);
  }

  function remindersList(view, body) {
    const list = el("ul", { className: "cards" });
    if (!view.reminders.length) list.append(el("li", { className: "muted", text: 'None. Ask Ira: "kal subah 9 baje yaad dilana".' }));
    for (const reminder of view.reminders) {
      const due =
        reminder.trigger === "time"
          ? new Date(reminder.due_at * 1000).toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })
          : `when you ${reminder.trigger === "arrive" ? "reach" : "leave"} ${reminder.place}`;
      list.append(
        el(
          "li",
          { className: "card" },
          el("p", { text: reminder.text }),
          el("p", { className: "muted small", text: due }),
          el("button", {
            type: "button",
            className: "text-btn danger",
            text: "Cancel",
            onClick: async () => {
              await call(`/v1/me/reminders/${encodeURIComponent(reminder.id)}`, { method: "DELETE" });
              await renderKnows(body);
            },
          }),
        ),
      );
    }
    return el("section", { className: "stack" }, el("h3", { text: "Reminders" }), list);
  }

  function phoneSection(view, body) {
    const section = el("section", { className: "stack" }, el("h3", { text: "Your iPhone" }));
    section.append(el("p", { className: "muted small", text: "An iPhone Shortcut can tell Ira when you reach or leave a place you name. It gets a key that can do nothing else." }));
    for (const token of view.phone_tokens) {
      section.append(
        el(
          "div",
          { className: "card row" },
          el("span", { text: `${token.label}, made ${when(token.created_at)}, last used ${when(token.last_used_at)}` }),
          el("button", {
            type: "button",
            className: "text-btn danger",
            text: "Revoke",
            onClick: async () => {
              await call("/v1/me/learning/phone-token", { method: "DELETE" });
              await renderKnows(body);
            },
          }),
        ),
      );
    }
    const pin = pinField();
    const error = el("p", { className: "error", role: "alert" });
    const form = el("form", { className: "stack card" }, pin, el("button", { type: "submit", className: "btn btn-ghost", text: view.phone_tokens.length ? "Make a new key" : "Make a key for Shortcuts" }), error);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const value = $("input", pin).value;
      $("input", pin).value = "";
      try {
        const made = await call("/v1/me/learning/phone-token", { method: "POST", json: { pin: value } });
        form.replaceWith(
          el(
            "div",
            { className: "stack card" },
            el("p", { text: "Shown once. In the Shortcut, post to:" }),
            el("code", { text: made.url }),
            el("p", { text: "with the header Authorization: Bearer and this key:" }),
            el("code", { className: "breakable", text: made.token }),
            el("div", { className: "row" }, copyButton(made.token, "Copy the key"), copyButton(made.url, "Copy the address")),
            el("p", { className: "muted small", text: 'The body is {"event": "arrive", "place": "Office"} (or "leave"). The docs page "Learning" has the steps.' }),
          ),
        );
      } catch (problem) {
        error.textContent = problem.message;
      }
    });
    section.append(form);
    return section;
  }

  // --- your connections (MCP servers) ------------------------------------------------

  const TIER_WORDS = ["reads only", "small change", "needs your yes", "needs your PIN"];
  const PRESETS = {
    github: { name: "GitHub", url: "https://api.githubcopilot.com/mcp/readonly", hint: "A fine-grained personal access token from github.com/settings/tokens. This address is read-only." },
  };

  // --- your businesses ---------------------------------------------------------------

  const BUSINESS_FIELDS = [
    ["about", "What it is, to you", "For example: a small clinic; I keep its books.", 600],
    ["people", "Its people", "For example: Dr. Mehta, the owner; Priya at the front desk.", 600],
    ["terms", "Terms", "For example: a monthly invoice, paid in 15 days.", 600],
    ["may_do", "What Ira may do for it", "For example: read its appointments; never message its patients.", 400],
  ];

  async function renderBusinesses(body) {
    const businesses = await call("/v1/me/businesses");
    const list = el("ul", { className: "cards" });
    if (!businesses.length) {
      list.append(el("li", { className: "muted", text: "None yet. Tell Ira about each business you work with, here or in a chat (\"Sunrise pays in 30 days\"), and it keeps them in mind." }));
    }
    for (const business of businesses) {
      const gist = [business.about, business.may_do && `Ira may: ${business.may_do}`].filter(Boolean).join(" ");
      list.append(
        el(
          "li",
          { className: "card" },
          el("details", {}, el("summary", {}, el("strong", { text: business.name }), gist ? el("span", { className: "muted small", text: ` ${gist}` }) : null), businessForm(business, body)),
        ),
      );
    }
    const add = el("details", { className: "card" }, el("summary", { text: "Add a business" }), businessForm(null, body));
    body.replaceChildren(
      el("p", { className: "muted small", text: "Ira follows what you say it may do. Anything that changes something still waits for your yes or your PIN." }),
      list,
      add,
    );
  }

  function businessForm(business, body) {
    const name = el("input", { name: "name", required: true, maxlength: "80", value: business ? business.name : "" });
    const fields = Object.fromEntries(
      BUSINESS_FIELDS.map(([key, , hint, max]) => [key, el("textarea", { name: key, rows: 2, maxlength: String(max), placeholder: hint, value: business ? business[key] : "" })]),
    );
    const error = el("p", { className: "error", role: "alert" });
    const form = el(
      "form",
      { className: "stack-tight" },
      el("label", {}, "Name", name),
      ...BUSINESS_FIELDS.map(([key, label]) => el("label", {}, label, fields[key])),
      el(
        "div",
        { className: "row" },
        el("button", { type: "submit", className: "btn btn-primary", text: business ? "Save" : "Add" }),
        business
          ? el("button", {
              type: "button",
              className: "btn btn-ghost",
              text: "Remove",
              onClick: async () => {
                if (!confirm(`Remove ${business.name}? Ira forgets what you told it about it.`)) return;
                try {
                  await call(`/v1/me/businesses/${encodeURIComponent(business.id)}`, { method: "DELETE" });
                  await renderBusinesses(body);
                } catch (problem) {
                  error.textContent = problem.message;
                }
              },
            })
          : null,
      ),
      error,
    );
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const json = { name: name.value.trim() };
      for (const [key] of BUSINESS_FIELDS) json[key] = fields[key].value.trim();
      try {
        await call(business ? `/v1/me/businesses/${encodeURIComponent(business.id)}` : "/v1/me/businesses", { method: business ? "PATCH" : "POST", json });
        await renderBusinesses(body);
      } catch (problem) {
        error.textContent = problem.message;
      }
    });
    return form;
  }

  async function renderConnections(body) {
    const view = await call("/v1/me/connections");
    if (!view.available) {
      body.replaceChildren(el("p", { className: "muted", text: "This server does not offer connections yet: its owner installs them (the connectors extra)." }));
      return;
    }
    const list = el("ul", { className: "cards" });
    if (!view.connections.length) list.append(el("li", { className: "muted", text: "None yet. A connection lets Ira use a service for you, with its own tiers: reading is free, changes need your yes or your PIN." }));
    for (const connection of view.connections) list.append(connectionCard(connection, body));
    body.replaceChildren(el("section", { className: "stack" }, list), addConnection(view, body));
  }

  function connectionCard(connection, body) {
    const path = `/v1/me/connections/${encodeURIComponent(connection.id)}`;
    const error = el("p", { className: "error", role: "alert" });
    const guard = (work) => () => work().catch((problem) => (error.textContent = problem.message));
    const reload = () => renderConnections(body);
    const where = connection.url || `${connection.server} (on this server)`;
    const state =
      connection.status === "ok"
        ? `${connection.tools.filter((t) => t.enabled).length} of ${connection.tools.length} tools on`
        : connection.status === "error"
          ? `Could not connect: ${connection.error || "unknown error"}`
          : connection.status === "needs_auth"
            ? "Sign in to the service to use it."
            : connection.status === "needs_code"
              ? "Telegram sent you a code: type it below."
              : connection.status === "needs_password"
                ? "Your account has a two-step password: type it with the code."
                : "Not checked yet";
    const tools = el("details", {}, el("summary", { text: "Tools" }));
    for (const tool of connection.tools) {
      const on = el("input", { type: "checkbox", checked: tool.enabled, "aria-label": `Use ${tool.mcp_name}` });
      const tier = el("select", { "aria-label": `Tier of ${tool.mcp_name}` });
      for (let n = tool.min_tier; n <= 3; n++) tier.append(el("option", { value: String(n), text: TIER_WORDS[n] }));
      tier.value = String(tool.tier);
      const save = guard(async () => {
        await call(path, { method: "PATCH", json: { tools: { [tool.name]: { enabled: on.checked, tier: Number(tier.value) } } } });
      });
      on.addEventListener("change", save);
      tier.addEventListener("change", save);
      tools.append(el("div", { className: "row tool-row" }, on, el("span", { className: "small", text: tool.mcp_name, title: tool.description || "" }), tier));
    }
    const pin = pinField("Your PIN, to switch it back on");
    pin.hidden = true;
    const toggle = el("button", {
      type: "button",
      className: "btn btn-ghost",
      text: connection.enabled ? "Switch off" : "Switch on",
      onClick: guard(async () => {
        if (connection.enabled) {
          await call(path, { method: "PATCH", json: { enabled: false } });
          return reload();
        }
        if (pin.hidden) {
          pin.hidden = false;
          return $("input", pin).focus();
        }
        const value = $("input", pin).value;
        $("input", pin).value = "";
        await call(path, { method: "PATCH", json: { enabled: true, pin: value } });
        await reload();
      }),
    });
    return el(
      "li",
      { className: "card" },
      el("p", {}, el("strong", { text: connection.name }), connection.enabled ? "" : " (off)"),
      el("p", { className: "muted small breakable", text: where }),
      el("p", { className: connection.status === "error" ? "error small" : "muted small", text: state }),
      connection.tools.length && connection.status === "ok" ? tools : null,
      connection.status === "needs_code" || connection.status === "needs_password" ? telegramCode(connection, body) : null,
      pin,
      el(
        "div",
        { className: "row" },
        toggle,
        el("button", { type: "button", className: "btn btn-ghost", text: "Check again", onClick: guard(async () => { await call(`${path}/refresh`, { method: "POST" }); await reload(); }) }),
        connection.status === "needs_auth" || connection.status === "new"
          ? el("button", {
              type: "button",
              className: "btn btn-primary",
              text: "Sign in",
              onClick: guard(async () => {
                const popup = window.open("about:blank", "_blank"); // opened on the tap: not blocked
                signIn(await call(`${path}/sign-in`, { method: "POST" }), body, popup);
              }),
            })
          : null,
        el("button", {
          type: "button",
          className: "text-btn danger",
          text: "Remove",
          onClick: guard(async () => {
            if (!confirm(`Remove ${connection.name}? Its token is deleted from this server.`)) return;
            await call(path, { method: "DELETE" });
            await reload();
          }),
        }),
      ),
      error,
    );
  }

  function telegramCode(connection, body) {
    const code = el("input", { name: "code", inputmode: "numeric", autocomplete: "one-time-code", maxlength: "10", required: true });
    const password = el("input", { name: "password", type: "password", autocomplete: "off", maxlength: "200" });
    const error = el("p", { className: "error", role: "alert" });
    const form = el(
      "form",
      { className: "stack-tight" },
      el("label", {}, "The code from Telegram", code),
      el("label", { hidden: connection.status !== "needs_password" }, "Two-step password", password),
      el("button", { type: "submit", className: "btn btn-primary", text: "Finish" }),
      error,
    );
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        await call(`/v1/me/connections/${encodeURIComponent(connection.id)}/code`, {
          method: "POST",
          json: { code: code.value, password: password.value || undefined },
        });
        await renderConnections(body);
      } catch (problem) {
        password.closest("label").hidden = false;
        error.textContent = problem.message;
      }
    });
    return form;
  }

  function addConnection(view, body) {
    const name = el("input", { name: "name", maxlength: "40", required: true, placeholder: "GitHub" });
    const url = el("input", { name: "url", type: "url", maxlength: "500", placeholder: "https://…/mcp" });
    const token = el("input", { name: "token", type: "password", autocomplete: "off", maxlength: "500" });
    const oauth = el("input", { type: "checkbox", name: "oauth" });
    oauth.addEventListener("change", () => {
      token.closest("label").hidden = oauth.checked;
    });
    const hint = el("p", { className: "muted small", text: "The token is sent as Authorization: Bearer, and kept sealed on this server; it is never shown again." });
    const server = el("select", { name: "server" }, el("option", { value: "", text: "A remote server, by its address" }), view.servers.map((s) => el("option", { value: s.name, text: `${s.name}: ${s.description || "on this server"}` })));
    const needs = el("div", { className: "stack-tight" });
    // Mail over IMAP: the server, the address and an app password.
    const imapHost = el("input", { name: "imap_host", maxlength: "253", placeholder: "imap.gmail.com" });
    const imapUser = el("input", { name: "imap_user", type: "email", maxlength: "254", autocomplete: "off" });
    const imapPassword = el("input", { name: "imap_password", type: "password", maxlength: "200", autocomplete: "off" });
    const imapFields = el(
      "div",
      { className: "stack-tight", hidden: true },
      el("label", {}, "Mail server", imapHost),
      el("label", {}, "Your address", imapUser),
      el("label", {}, "App password (from your mail provider, not your usual password)", imapPassword),
    );
    // Telegram as you: your own api_id and api_hash, and your phone number.
    const tgId = el("input", { name: "tg_id", inputmode: "numeric", maxlength: "12" });
    const tgHash = el("input", { name: "tg_hash", maxlength: "32", autocomplete: "off" });
    const tgPhone = el("input", { name: "tg_phone", type: "tel", maxlength: "20", placeholder: "+91…" });
    const telegramFields = el(
      "div",
      { className: "stack-tight", hidden: true },
      el("label", {}, "api_id (my.telegram.org, API development tools)", tgId),
      el("label", {}, "api_hash", tgHash),
      el("label", {}, "Your phone number", tgPhone),
    );
    let mode = "mcp"; // mcp, google, imap or telegram
    const telegram = (view.builtins || []).find((b) => b.kind === "telegram");
    const google = (view.builtins || []).find((b) => b.kind === "google");
    const pin = pinField();
    const error = el("p", { className: "error", role: "alert" });
    const showNeeds = () => {
      const chosen = view.servers.find((s) => s.name === server.value);
      url.closest("label").hidden = Boolean(chosen);
      token.closest("label").hidden = Boolean(chosen);
      needs.replaceChildren(...(chosen ? chosen.needs.map((key) => el("label", {}, key, el("input", { name: `env:${key}`, type: "password", autocomplete: "off", required: true }))) : []));
    };
    const form = el(
      "form",
      { className: "stack card" },
      el(
        "div",
        { className: "row" },
        el("span", { className: "muted small", text: "Quick:" }),
        el("button", {
          type: "button",
          className: "text-btn",
          text: "GitHub (read-only)",
          onClick: () => {
            setMode("mcp");
            name.value = PRESETS.github.name;
            url.value = PRESETS.github.url;
            server.value = "";
            showNeeds();
            hint.textContent = PRESETS.github.hint;
            token.focus();
          },
        }),
        google && google.available
          ? el("button", {
              type: "button",
              className: "text-btn",
              text: "Google (Gmail and Calendar)",
              onClick: () => {
                setMode("google");
                name.value = "Google";
                hint.textContent = "Read-only. You sign in with Google in a page that opens; Ira never sees your password.";
              },
            })
          : null,
        telegram && telegram.available
          ? el("button", {
              type: "button",
              className: "text-btn",
              text: "Telegram (as you)",
              onClick: () => {
                setMode("telegram");
                name.value = "Telegram";
                hint.textContent = "Ira reads your chats when you ask, and sends only after your yes. Telegram allows clients made with your own api_id; heavy automation can get an account limited.";
                tgId.focus();
              },
            })
          : null,
        el("button", {
          type: "button",
          className: "text-btn",
          text: "Mail (IMAP)",
          onClick: () => {
            setMode("imap");
            name.value = "Mail";
            hint.textContent = "Read-only, with an app password. Gmail: Google Account, Security, 2-Step Verification, App passwords.";
            imapHost.focus();
          },
        }),
      ),
      view.servers.length ? el("label", {}, "Where", server) : null,
      el("label", {}, "Name", name),
      el("label", {}, "Address of the MCP server", url),
      el("label", { className: "switch" }, oauth, el("span", { text: "Sign in with the service instead of a token" })),
      el("label", {}, "Token", token),
      imapFields,
      telegramFields,
      hint,
      needs,
      pin,
      el("button", { type: "submit", className: "btn btn-primary", text: "Connect" }),
      error,
    );
    server.addEventListener("change", showNeeds);
    function setMode(next) {
      mode = next;
      for (const field of [url, token, oauth]) field.closest("label").hidden = mode !== "mcp";
      if (server.closest("label")) server.closest("label").hidden = mode !== "mcp";
      imapFields.hidden = mode !== "imap";
      telegramFields.hidden = mode !== "telegram";
    }
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      error.textContent = "";
      const data = new FormData(form);
      const env = {};
      for (const [key, value] of data.entries()) if (key.startsWith("env:")) env[key.slice(4)] = value;
      const payload = { name: name.value, pin: $("input", pin).value || undefined };
      if (mode === "google") Object.assign(payload, { builtin: "google" });
      else if (mode === "telegram") Object.assign(payload, { builtin: "telegram", telegram: { api_id: Number(tgId.value), api_hash: tgHash.value.trim(), phone: tgPhone.value } });
      else if (mode === "imap") Object.assign(payload, { builtin: "imap", imap: { host: imapHost.value, user: imapUser.value, password: imapPassword.value } });
      else if (server.value) Object.assign(payload, { server: server.value, env });
      else if (oauth.checked) Object.assign(payload, { url: url.value, oauth: true });
      else Object.assign(payload, { url: url.value, headers: token.value ? { Authorization: `Bearer ${token.value}` } : {} });
      token.value = "";
      imapPassword.value = "";
      $("input", pin).value = "";
      const signsIn = payload.oauth || payload.builtin === "google";
      const popup = signsIn ? window.open("about:blank", "_blank") : null; // on the tap
      try {
        const made = await call("/v1/me/connections", { method: "POST", json: payload });
        if (made.authorize_url) return signIn(made, body, popup);
        if (popup) popup.close();
        await renderConnections(body);
      } catch (problem) {
        if (popup) popup.close();
        error.textContent = problem.message;
      }
    });
    return el("section", { className: "stack" }, el("h3", { text: "Connect a service" }), form);
  }

  // Signing in to a service (OAuth): open its page, then wait for the connection to finish.
  function signIn(connection, body, popup) {
    if (!connection.authorize_url) {
      if (popup) popup.close();
      return renderConnections(body);
    }
    if (popup && !popup.closed) {
      popup.opener = null;
      popup.location.href = connection.authorize_url;
    } else {
      window.open(connection.authorize_url, "_blank", "noopener");
    }
    body.prepend(el("p", { className: "note", role: "status", text: `Sign in to ${connection.name} in the page that opened. This updates when you are back.` }));
    const started = Date.now();
    const poll = async () => {
      if (!$("#panel").open || Date.now() - started > 600000) return;
      const view = await call("/v1/me/connections").catch(() => null);
      const now = view && view.connections.find((c) => c.id === connection.id);
      if (now && now.status !== "new" && now.status !== "needs_auth") return renderConnections(body);
      setTimeout(poll, 2000);
    };
    setTimeout(poll, 2000);
  }

  // Thumbs on an answer, when you let Ira learn from them.
  const REPORT_REASONS = {
    wrong: "It is wrong",
    harmful: "It is harmful or dangerous",
    offensive: "It is offensive",
    private: "It shows something private",
    other: "Something else",
  };

  // Every answer can be reported; thumbs only when you let Ira learn from them.
  function answered(li, messageId) {
    li.append(reportControl(messageId));
    if (!learning || !learning.on || !learning.sources.some((source) => source.name === "feedback" && source.on)) return;
    const row = el("div", { className: "row thumbs" });
    const rate = (rating) => async () => {
      try {
        await call("/v1/me/feedback", { method: "POST", json: { message_id: messageId, rating } });
        row.replaceChildren(el("span", { className: "muted small", text: "Thanks, noted." }));
      } catch (problem) {
        row.replaceChildren(el("span", { className: "error small", text: problem.message }));
      }
    };
    row.append(
      el("button", { type: "button", className: "text-btn", text: "Good answer", onClick: rate("up") }),
      el("button", { type: "button", className: "text-btn", text: "Not good", onClick: rate("down") }),
    );
    li.append(row);
  }

  function reportControl(messageId) {
    const holder = el("div", { className: "report" });
    const open = el("button", {
      type: "button",
      className: "text-btn small",
      text: "Report",
      "aria-label": "Report this answer",
      onClick: () => {
        const reason = el("select", { "aria-label": "Why" }, Object.entries(REPORT_REASONS).map(([value, text]) => el("option", { value, text })));
        const note = el("input", { maxlength: "500", placeholder: "What was wrong (optional)", "aria-label": "What was wrong" });
        const form = el(
          "form",
          { className: "row report-form" },
          reason,
          note,
          el("button", { type: "submit", className: "btn btn-ghost", text: "Send" }),
        );
        form.addEventListener("submit", async (event) => {
          event.preventDefault();
          try {
            await call("/v1/me/reports", { method: "POST", json: { message_id: messageId, reason: reason.value, note: note.value || undefined } });
            holder.replaceChildren(el("span", { className: "muted small", text: "Reported. Thank you: the people who run this Ira will look at it." }));
          } catch (problem) {
            holder.replaceChildren(el("span", { className: "error small", text: problem.message }));
          }
        });
        holder.replaceChildren(form);
        reason.focus();
      },
    });
    holder.append(open);
    return holder;
  }

  // Your time zone, from this browser, the first time: routines and reminders use it.
  async function ensureTimezone() {
    try {
      const settings = await call("/v1/me/settings");
      const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
      if (!settings.timezone && zone) await call("/v1/me/settings", { method: "PATCH", json: { timezone: zone } });
    } catch {
      /* not now: it is asked again next time */
    }
  }

  // --- wiring -------------------------------------------------------------------------

  for (const button of document.querySelectorAll("[data-panel]")) {
    button.addEventListener("click", () => open(button.dataset.panel));
  }
  $("#panel-close").addEventListener("click", close);
  $("#panel-back").addEventListener("click", () => {
    close();
    $("#menu").showModal();
  });
  $("#panel").addEventListener("click", (event) => {
    if (event.target === event.currentTarget) close();
  });
  $("#panel").addEventListener("close", () => clearInterval(pairingTimer));

  if (state.info) startEvents(); // app.js may have entered the chat already

  return { entered: startEvents, left: stopEvents, open, answered };
})();
