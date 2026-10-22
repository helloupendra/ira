// The reader against fixture pages, in jsdom: what it returns, and what it never reads.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";
import { JSDOM } from "jsdom";

const here = (path) => new URL(path, import.meta.url);
const reader = readFileSync(here("../reader.js"), "utf8");

function read(fixture, url = "https://example.com/page?session=abc#top") {
  const html = readFileSync(here(`./fixtures/${fixture}`), "utf8");
  const dom = new JSDOM(html, { url, runScripts: "outside-only" });
  // The reader's value is the last expression, as when Chrome injects it.
  return JSON.parse(JSON.stringify(dom.window.eval(reader)));
}

test("an upload at 63% with time left", () => {
  const page = read("upload.html");
  assert.equal(page.title, "Upload - Example Drive");
  assert.deepEqual(page.progress.bars, [{ source: "progress", percent: 63 }]);
  assert.deepEqual(page.progress.percents, [63]);
  assert.deepEqual(page.progress.eta, ["4 min"]);
  assert.match(page.text, /quarterly-report\.pdf/);
  assert.match(page.text, /Cancel upload/);
  assert.doesNotMatch(page.text, /Hidden helper text|Also hidden/);
});

test("a CI page at step 4 of 5", () => {
  const page = read("ci.html");
  assert.deepEqual(page.progress.counts[0], { done: 4, total: 5, text: "Step 4/5" });
  assert.deepEqual(page.progress.bars, [{ source: "progressbar", percent: 80, label: "Steps" }]);
  assert.deepEqual(page.progress.eta, ["3 min"]);
  assert.ok(page.progress.status.includes("done"));
  assert.doesNotMatch(page.text, /script text/);
  assert.equal(page.text.split("\n")[0], "Build #812");
});

test("a page that says Completed", () => {
  const page = read("completed.html");
  assert.ok(page.progress.status.includes("completed"));
  assert.deepEqual(page.progress.counts, [{ done: 3, total: 3, text: "3 of 3" }]);
});

test("form fields and passwords are never read", () => {
  const page = read("login.html");
  const everything = JSON.stringify(page);
  for (const secret of ["hunter2-very-secret", "riley@example.com", "draft that I typed", "Premium choice", "screen reader only"]) {
    assert.ok(!everything.includes(secret), `read ${secret}`);
  }
  assert.match(page.text, /Welcome back\./);
  assert.match(page.text, /Password/); // the label is page text; the value is not
});

test("the text is cut at 20,000 characters", () => {
  const long = `<!doctype html><title>Long</title><p>${"word ".repeat(6000)}</p>`;
  const dom = new JSDOM(long, { url: "https://example.com/", runScripts: "outside-only" });
  const page = JSON.parse(JSON.stringify(dom.window.eval(reader)));
  assert.equal(page.text.length, 20000);
  assert.equal(page.truncated, true);
});

// The service worker's address rules, run with a stand-in for the chrome API.
function worker() {
  const noop = { addListener() {} };
  const chrome = {
    runtime: { onStartup: noop, onInstalled: noop, onMessage: noop, connectNative() { throw new Error("no host in tests"); }, getManifest: () => ({ version: "test" }) },
  };
  const context = { chrome, URL, setTimeout: () => 0, console };
  vm.createContext(context);
  vm.runInContext(readFileSync(here("../background.js"), "utf8"), context);
  return context;
}

test("restricted tabs say why, and addresses lose their query", () => {
  const { restriction, cleanUrl } = worker();
  assert.match(restriction("chrome://settings/"), /its own pages/);
  assert.match(restriction("https://chromewebstore.google.com/detail/x"), /Web Store/);
  assert.match(restriction("https://chrome.google.com/webstore/category"), /Web Store/);
  assert.match(restriction("https://example.com/files/report.PDF"), /PDF/);
  assert.match(restriction("file:///Users/x/notes.txt"), /files on this Mac/);
  assert.equal(restriction("https://drive.example.com/upload"), "");
  assert.equal(cleanUrl("https://example.com/a/b?token=abc#frag"), "https://example.com/a/b");
});
