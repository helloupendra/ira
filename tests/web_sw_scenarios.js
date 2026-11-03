// The web app's service worker, offline and online: a browser's parts are stubbed, sw.js runs as
// it is. Run by tests/test_web_sw.py.
"use strict";
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SOURCE = fs.readFileSync(path.join(__dirname, "../src/ira/web/static/sw.js"), "utf8");
const ORIGIN = "https://ira.test";
const TYPES = { ".js": "text/javascript", ".css": "text/css", ".html": "text/html" };

function absolute(input) {
  return typeof input === "string" ? new URL(input, ORIGIN).href : input.url;
}

// A request as a page makes it: relative paths resolve against the app, and a page load is
// "navigate" (which Node's own Request will not take).
class SWRequest extends Request {
  constructor(input, init = {}) {
    const { mode, ...rest } = init;
    super(typeof input === "string" ? absolute(input) : input, rest);
    if (mode === "navigate" || input.mode === "navigate") Object.defineProperty(this, "mode", { value: "navigate" });
  }
}

function page(pathname) {
  const ext = path.extname(pathname) || ".html";
  return new Response(`${pathname === "/" ? "<!doctype html>" : ""}copy of ${pathname}`, {
    headers: { "Content-Type": TYPES[ext] || "application/octet-stream" },
  });
}

// The Cache API, as browsers match it: by the whole address unless told to ignore the query.
class Cache {
  constructor() {
    this.entries = new Map();
  }
  async put(request, response) {
    this.entries.set(absolute(request), response);
  }
  async addAll(requests) {
    for (const request of requests) this.entries.set(absolute(request), page(new URL(absolute(request)).pathname));
  }
  async match(request, options = {}) {
    const wanted = new URL(absolute(request));
    for (const [key, response] of this.entries) {
      const url = new URL(key);
      const same = options.ignoreSearch ? url.origin + url.pathname === wanted.origin + wanted.pathname : key === wanted.href;
      if (same) return response.clone();
    }
    return undefined;
  }
}

async function newWorker() {
  const world = { online: true, served: [], handlers: {} };
  const stores = new Map();
  const caches = {
    async open(name) {
      if (!stores.has(name)) stores.set(name, new Cache());
      return stores.get(name);
    },
    async keys() {
      return [...stores.keys()];
    },
    async delete(name) {
      return stores.delete(name);
    },
    async match(request, options) {
      for (const cache of stores.values()) {
        const hit = await cache.match(request, options);
        if (hit) return hit;
      }
      return undefined;
    },
  };
  const self = {
    location: { origin: ORIGIN },
    addEventListener(type, handler) {
      world.handlers[type] = handler;
    },
    skipWaiting() {},
    clients: { claim() {} },
  };
  async function fetch(request) {
    if (!world.online) throw new TypeError("Failed to fetch");
    const url = new URL(absolute(request));
    world.served.push(url.pathname + url.search);
    return page(url.pathname);
  }
  vm.runInNewContext(SOURCE, { self, caches, fetch, Request: SWRequest, Response, URL, Promise, console });

  const waiting = [];
  world.handlers.install({ waitUntil: (promise) => waiting.push(promise) });
  world.handlers.activate({ waitUntil: (promise) => waiting.push(promise) });
  await Promise.all(waiting);

  world.get = async (address, mode) => {
    let answer;
    const event = {
      request: new SWRequest(address, { mode }),
      respondWith(promise) {
        answer = promise;
      },
    };
    world.handlers.fetch(event);
    if (answer === undefined) return undefined; // left to the network: the worker kept out
    const response = await answer;
    await new Promise((resolve) => setTimeout(resolve, 0)); // let a copy land in the cache
    return response;
  };
  world.stores = stores;
  return world;
}

async function text(response) {
  return response.type === "error" ? "(network error)" : response.text();
}

const scenarios = {
  // The page asks for "/app.js?v=28"; offline, it gets the script, not the app's page.
  async "offline, a versioned script is the script"() {
    const world = await newWorker();
    world.online = false;
    const script = await world.get("/app.js?v=28");
    assert.equal(await text(script), "copy of /app.js");
    assert.equal(script.headers.get("Content-Type"), "text/javascript");
    const style = await world.get("/style.css?v=34");
    assert.equal(await text(style), "copy of /style.css");
  },

  async "offline, the app's page opens, with or without a query"() {
    const world = await newWorker();
    world.online = false;
    assert.match(await text(await world.get("/", "navigate")), /<!doctype html>/);
    assert.match(await text(await world.get("/?share=1", "navigate")), /<!doctype html>/);
  },

  // Never HTML for a script: the page would break on it.
  async "offline, a file that is not kept fails as itself"() {
    const world = await newWorker();
    world.online = false;
    const missing = await world.get("/not-kept.js?v=1");
    assert.equal(missing.type, "error");
  },

  async "online, the newest copy is kept by its path and served offline under any version"() {
    const world = await newWorker();
    await world.get("/live.js?v=26");
    assert.deepEqual(world.served, ["/live.js?v=26"]);
    const kept = [...world.stores.get("ira-shell-v38").entries.keys()].filter((key) => key.includes("live.js"));
    assert.deepEqual(kept, [`${ORIGIN}/live.js`]);
    world.online = false;
    assert.equal(await text(await world.get("/live.js?v=27")), "copy of /live.js");
  },

  async "the API and the console are never answered from a cache"() {
    const world = await newWorker();
    world.online = false;
    assert.equal(await world.get("/v1/me/drop"), undefined);
    assert.equal(await world.get("/admin/"), undefined);
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
