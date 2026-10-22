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
    const kind = el("select", { name: "kind" }, el("option", { value: "mac", text: "Mac (reads Chrome tabs)" }), el("option", { value: "android", text: "Android phone (the ear, coming later)" }));
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
    events = new EventSource("/v1/me/events/stream");
    events.addEventListener("message", (message) => {
      let event;
      try {
        event = JSON.parse(message.data);
      } catch {
        return;
      }
      const text = event.text && event.text !== event.title ? `${event.title}. ${event.text}` : event.title;
      remember({ role: "note", text });
      addTurn("note", text);
      announce(text);
      if (speakOn() && (state.mode === "idle" || state.mode === "answering")) speak(text);
    });
  }

  function stopEvents() {
    if (events) events.close();
    events = null;
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

  return { entered: startEvents, left: stopEvents, open };
})();
