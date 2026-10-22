// The Ira extension's service worker. It connects to the Ira companion on this Mac
// (the native messaging host "in.ira.mac") and answers two requests from it: list
// the open tabs, and read one tab. It has no network access of its own, and no
// script runs in any page until someone asks Ira about that page.
"use strict";

const HOST = "in.ira.mac";
const MAX_RETRY_MS = 60000;

let port = null;
let ready = false; // the companion said it is listening
let retryMs = 1000;
let lastProblem = "";

function cleanUrl(url) {
  // Addresses lose their query and fragment: those can hold tokens and personal data.
  try {
    const parsed = new URL(url);
    parsed.search = "";
    parsed.hash = "";
    return parsed.toString();
  } catch {
    return "";
  }
}

function restriction(url) {
  let parsed;
  try {
    parsed = new URL(url || "");
  } catch {
    return "this tab has no address yet";
  }
  const own = ["chrome:", "chrome-extension:", "chrome-untrusted:", "chrome-search:", "devtools:", "edge:", "about:", "view-source:"];
  if (own.includes(parsed.protocol)) return `Chrome does not let extensions read its own pages (${parsed.protocol}//)`;
  if (parsed.hostname === "chromewebstore.google.com" || (parsed.hostname === "chrome.google.com" && parsed.pathname.startsWith("/webstore"))) {
    return "Chrome does not let extensions read the Chrome Web Store";
  }
  if (parsed.pathname.toLowerCase().endsWith(".pdf")) return "this tab shows a PDF, and Chrome's PDF viewer cannot be read by extensions";
  if (parsed.protocol === "file:") return "Ira does not read files on this Mac";
  return "";
}

async function listTabs() {
  const [tabs, front] = await Promise.all([chrome.tabs.query({}), chrome.windows.getLastFocused().catch(() => null)]);
  return tabs.map((tab) => ({
    id: tab.id,
    windowId: tab.windowId,
    active: tab.active,
    focused: front ? tab.windowId === front.id : false,
    title: tab.title || "",
    url: cleanUrl(tab.url || tab.pendingUrl || ""),
    lastAccessed: tab.lastAccessed || 0,
    restricted: restriction(tab.url || tab.pendingUrl) !== "",
  }));
}

async function readTab(tabId) {
  let tab;
  try {
    tab = await chrome.tabs.get(tabId);
  } catch {
    throw new Error(`No tab with id ${tabId}: it was closed`);
  }
  const why = restriction(tab.url);
  if (why) throw new Error(why);
  let results;
  try {
    results = await chrome.scripting.executeScript({ target: { tabId }, files: ["reader.js"] });
  } catch (error) {
    throw new Error(`Chrome would not let Ira read this tab (${error.message})`);
  }
  const page = results && results[0] ? results[0].result : null;
  if (!page) throw new Error("the page gave nothing back");
  page.url = cleanUrl(tab.url);
  return page;
}

async function handle(message) {
  switch (message.op) {
    case "list_tabs":
      return listTabs();
    case "read_tab":
      if (!Number.isInteger(message.tabId)) throw new Error("which tab? (tabId)");
      return readTab(message.tabId);
    default:
      throw new Error(`unknown request ${String(message.op).slice(0, 40)}`);
  }
}

async function onMessage(message) {
  if (!message || typeof message !== "object") return;
  if (message.type === "status") {
    ready = !!message.ready;
    return;
  }
  if (message.id === undefined) return;
  let reply;
  try {
    reply = { id: message.id, ok: true, result: await handle(message) };
  } catch (error) {
    reply = { id: message.id, ok: false, error: String((error && error.message) || error).slice(0, 300) };
  }
  if (port) port.postMessage(reply);
}

function connect() {
  if (port) return;
  try {
    port = chrome.runtime.connectNative(HOST);
  } catch (error) {
    lastProblem = String(error.message || error);
    port = null;
    setTimeout(connect, retryMs);
    retryMs = Math.min(retryMs * 2, MAX_RETRY_MS);
    return;
  }
  port.onMessage.addListener(onMessage);
  port.onDisconnect.addListener(() => {
    lastProblem = chrome.runtime.lastError ? chrome.runtime.lastError.message : "the companion closed";
    port = null;
    ready = false;
    setTimeout(connect, retryMs);
    retryMs = Math.min(retryMs * 2, MAX_RETRY_MS);
  });
  port.postMessage({ type: "hello", extension: chrome.runtime.getManifest().version });
  retryMs = 1000;
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message && message.type === "status") {
    sendResponse({ connected: !!port, ready, problem: port ? "" : lastProblem });
  }
});
chrome.runtime.onStartup.addListener(connect);
chrome.runtime.onInstalled.addListener(connect);
connect();
