// Screenshots of the Ira app and the console: phone and desktop, light and
// dark, for docs/images. Needs a running server with the clinic demo and the
// fictional accounts, and the installed Google Chrome.
//
//   IRA_OWNER_PASSWORD=... IRA_ADMIN_PASSWORD=... IRA_VIEWER_PASSWORD=... IRA_STAFF_PASSWORD=... \
//     node scripts/screenshots.mjs --base http://127.0.0.1:8790 --out ../docs/images [--scene pin]
//
// Scenes that need a server with no owner yet (the setup form and the wizard)
// run only when IRA_SETUP_BASE names such a server.
//
// Action outcomes (done, wrong PIN, locked, ...) are shown by answering the
// confirm request locally with the server's own messages, so a run never
// changes clinic data and never trips the wrong-PIN lock. The proposal itself
// is real.
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

const args = Object.fromEntries(
  process.argv.slice(2).map((a, i, all) => (a.startsWith("--") ? [a.slice(2), all[i + 1] ?? "true"] : [])).filter((x) => x.length),
);
const BASE = args.base || "http://127.0.0.1:8790";
const OUT = resolve(args.out || "../docs/images");
const ONLY = args.scene ? args.scene.split(",") : null;
const SIZES = {
  phone: { width: 390, height: 844, scale: 2 },
  desktop: { width: 1440, height: 900, scale: 1 },
};
const THEMES = ["light", "dark"];
const SETUP_BASE = process.env.IRA_SETUP_BASE || null;

const ACCOUNTS = {
  owner: ["owner@example.com", process.env.IRA_OWNER_PASSWORD],
  admin: ["admin@example.com", process.env.IRA_ADMIN_PASSWORD],
  viewer: ["viewer@example.com", process.env.IRA_VIEWER_PASSWORD],
  staff: ["staff@example.com", process.env.IRA_STAFF_PASSWORD],
};

const sse = (events) => events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("");
const stub = (page, path, response) =>
  page.route(`**${path}`, (route) => route.fulfill(typeof response === "function" ? response(route) : response));

async function login(context, who) {
  const [email, password] = ACCOUNTS[who];
  if (!password) throw new Error(`set IRA_${who.toUpperCase()}_PASSWORD`);
  const r = await context.request.post(`${BASE}/v1/auth/login`, {
    data: { email, password },
    headers: { "X-Ira-Request": "1" },
  });
  if (!r.ok()) throw new Error(`login as ${who} failed: ${r.status()}`);
}

async function ask(page, text) {
  await page.fill("#text", text);
  await page.press("#text", "Enter");
  await page.waitForSelector(".turn.ira .how:not([hidden])", { timeout: 20000 });
}

async function proposal(page, text = "cancel appointment 17") {
  await page.fill("#text", text);
  await page.press("#text", "Enter");
  await page.waitForSelector(".action .pin", { timeout: 20000 });
  return (await page.textContent(".action-summary")).trim();
}

const outcome = (status, body) => ({ status, contentType: "application/json", body: JSON.stringify(body) });

async function settled(page) {
  await page.waitForSelector("main .page, main .gate-card", { timeout: 20000 });
  await page.waitForFunction(() => !document.querySelector("main .skeleton"), null, { timeout: 20000 });
  await page.waitForTimeout(150);
}

// Each scene: the surface, who is signed in, and what to do before the shot.
const SCENES = [
  { name: "app-signin", surface: "app", run: (p) => p.waitForSelector("#view-login:not([hidden])") },
  {
    name: "app-setup",
    surface: "app",
    base: "setup",
    url: "/#code=7F3A-91C2-0B4E",
    run: (p) => p.waitForSelector("#view-setup:not([hidden])"),
  },
  { name: "app-idle", surface: "app", as: "owner", run: (p) => p.waitForSelector("#hero:not([hidden])") },
  {
    name: "app-listening",
    surface: "app",
    as: "owner",
    mic: true,
    run: async (p) => {
      await p.waitForSelector("#hero:not([hidden])");
      await p.click("#hero-mic");
      await p.waitForSelector("#listen:not([hidden])");
      await p.waitForTimeout(700);
    },
  },
  {
    name: "app-thinking",
    surface: "app",
    as: "owner",
    run: async (p) => {
      await p.waitForSelector("#hero:not([hidden])");
      await p.evaluate(() => {
        addTurn("user", "any free slots tomorrow afternoon?");
        addTurn("ira");
        setMode("thinking");
        setStatus("Checking find slots…");
      });
    },
  },
  {
    name: "app-answer",
    surface: "app",
    as: "owner",
    run: async (p) => {
      await ask(p, "show appointments for Avery");
      await ask(p, "find slots tomorrow");
      await p.click(".turn.ira:last-of-type .how summary");
    },
  },
  {
    name: "app-hindi",
    surface: "app",
    as: "owner",
    run: async (p) => {
      await ask(p, "कल के खाली स्लॉट बताओ");
      await p.click(".turn.ira .how summary");
    },
  },
  { name: "app-pin", surface: "app", as: "owner", run: (p) => proposal(p) },
  {
    name: "app-pin-wrong",
    surface: "app",
    as: "owner",
    run: async (p) => {
      await proposal(p);
      await stub(p, "/v1/actions/*/confirm", outcome(403, { status: "wrong_pin", message: "Wrong PIN. 2 attempts left before actions lock.", attempts_left: 2 }));
      await p.fill(".action .pin", "0000");
      await p.click(".action-form button[type=submit]");
      await p.waitForSelector(".action[data-status=wrong_pin]");
    },
  },
  {
    name: "app-pin-done",
    surface: "app",
    as: "owner",
    run: async (p) => {
      const summary = await proposal(p);
      await stub(p, "/v1/actions/*/confirm", outcome(200, { status: "executed", message: `Done: ${summary}.`, result: { id: 17, status: "cancelled" } }));
      await p.fill(".action .pin", "0000");
      await p.click(".action-form button[type=submit]");
      await p.waitForSelector(".action[data-status=executed]");
    },
  },
  {
    name: "app-pin-locked",
    surface: "app",
    as: "owner",
    run: async (p) => {
      await proposal(p);
      await stub(p, "/v1/actions/*/confirm", outcome(423, { status: "locked", message: "Wrong PIN. Actions are now locked for 15 minutes.", locked_seconds: 900 }));
      await p.fill(".action .pin", "0000");
      await p.click(".action-form button[type=submit]");
      await p.waitForSelector(".action[data-status=locked]");
    },
  },
  {
    name: "app-pin-not-allowed",
    surface: "app",
    as: "owner",
    run: async (p) => {
      await proposal(p);
      await stub(p, "/v1/actions/*/confirm", outcome(403, { status: "not_allowed", message: "Your role cannot confirm this action. Allowed: owner, admin." }));
      await p.fill(".action .pin", "0000");
      await p.click(".action-form button[type=submit]");
      await p.waitForSelector(".action[data-status=not_allowed]");
    },
  },
  {
    name: "app-pin-no-pin",
    surface: "app",
    as: "owner",
    run: async (p) => {
      await proposal(p);
      await stub(p, "/v1/actions/*/confirm", outcome(409, { status: "no_pin", message: "You have no action PIN yet." }));
      await p.fill(".action .pin", "0000");
      await p.click(".action-form button[type=submit]");
      await p.waitForSelector(".action[data-status=no_pin]");
    },
  },
  {
    name: "app-pin-expired",
    surface: "app",
    as: "owner",
    run: async (p) => {
      await stub(p, "/v1/ask/stream", {
        status: 200,
        contentType: "text/event-stream",
        body: sse([
          { type: "start", conversation_id: "shot" },
          { type: "tool", name: "cancel_appointment" },
          { type: "action", action: { id: "act_shot", tool: "cancel_appointment", summary: "Cancel appointment #17: Avery Example on Tuesday 20 October at 09:30", status: "pending", expires_in: 1 } },
          { type: "delta", text: "I've prepared this: Cancel appointment #17: Avery Example on Tuesday 20 October at 09:30. Confirm it with your PIN to go ahead." },
          { type: "done", text: "I've prepared this: Cancel appointment #17: Avery Example on Tuesday 20 October at 09:30. Confirm it with your PIN to go ahead.", model: "demo:router", conversation_id: "shot" },
        ]),
      });
      await p.fill("#text", "cancel appointment 17");
      await p.press("#text", "Enter");
      await p.waitForSelector(".action[data-status=expired]", { timeout: 10000 });
    },
  },
  {
    name: "app-error-model",
    surface: "app",
    as: "owner",
    run: async (p) => {
      await stub(p, "/v1/ask/stream", {
        status: 200,
        contentType: "text/event-stream",
        body: sse([
          { type: "start", conversation_id: "shot" },
          { type: "error", message: "every model in the tier failed: openai:gpt-4o-mini (timeout), demo:router (unavailable)" },
        ]),
      });
      await p.fill("#text", "find slots tomorrow");
      await p.press("#text", "Enter");
      await p.waitForSelector(".turn.ira.failed");
    },
  },
  {
    name: "app-error-session",
    surface: "app",
    as: "owner",
    run: async (p) => {
      await stub(p, "/v1/ask/stream", outcome(401, { detail: "session expired; sign in again" }));
      await p.fill("#text", "find slots tomorrow");
      await p.press("#text", "Enter");
      await p.waitForSelector("#login-note:not([hidden])");
    },
  },
  {
    name: "app-error-offline",
    surface: "app",
    as: "owner",
    run: async (p, context) => {
      await p.waitForSelector("#hero:not([hidden])");
      await context.setOffline(true);
      await p.waitForSelector("#banner:not([hidden])");
    },
  },
  {
    name: "app-error-mic",
    surface: "app",
    as: "owner",
    micBlocked: true,
    run: async (p) => {
      await p.waitForSelector("#hero:not([hidden])");
      await p.click("#hero-mic");
      await p.waitForFunction(() => document.querySelector("#status").textContent.includes("blocked"));
    },
  },
  {
    name: "app-menu",
    surface: "app",
    as: "owner",
    run: async (p) => {
      await p.waitForSelector("#hero:not([hidden])");
      await p.click("#menu-open");
      await p.waitForSelector("#menu[open]");
      await p.waitForFunction(() => document.querySelector("#pin-status").textContent.length > 0);
    },
  },
  // The console. "settled" waits for the page and for every skeleton to go.
  { name: "console-login", surface: "console", url: "/admin/login", run: (p) => p.waitForSelector("main form") },
  { name: "console-overview", surface: "console", as: "owner", url: "/admin/", run: settled },
  { name: "console-conversations", surface: "console", as: "owner", url: "/admin/conversations", run: settled },
  {
    name: "console-conversation",
    surface: "console",
    as: "owner",
    url: "/admin/conversations",
    run: async (p, context) => {
      const rows = await (await context.request.get(`${BASE}/v1/admin/conversations?limit=5`)).json();
      const row = rows.find((r) => r.turns >= 2) || rows[0];
      await p.goto(`/admin/conversations/${encodeURIComponent(row.id)}`);
      await settled(p);
    },
  },
  { name: "console-actions", surface: "console", as: "owner", url: "/admin/actions", run: async (p) => { await settled(p); await p.click("main details summary"); await p.waitForTimeout(200); } },
  { name: "console-tools", surface: "console", as: "owner", url: "/admin/tools", run: async (p) => { await settled(p); await p.click("main details summary"); await p.waitForTimeout(200); } },
  { name: "console-tools-viewer", surface: "console", as: "viewer", url: "/admin/tools", run: async (p) => { await settled(p); await p.click("main details summary"); await p.waitForTimeout(200); } },
  { name: "console-models", surface: "console", as: "owner", url: "/admin/models", run: settled },
  { name: "console-channels", surface: "console", as: "owner", url: "/admin/channels", run: settled },
  { name: "console-users", surface: "console", as: "owner", url: "/admin/users", run: settled },
  { name: "console-users-forbidden", surface: "console", as: "admin", url: "/admin/users", run: (p) => p.waitForSelector("main .forbidden") },
  { name: "console-tokens", surface: "console", as: "owner", url: "/admin/tokens", run: settled },
  { name: "console-audit", surface: "console", as: "owner", url: "/admin/audit", run: settled },
  { name: "console-audit-cost", surface: "console", as: "owner", url: "/admin/audit?view=cost", run: settled },
  { name: "console-staff", surface: "console", as: "staff", url: "/admin/", run: (p) => p.waitForSelector("main .gate-card") },
  { name: "console-not-found", surface: "console", as: "owner", url: "/admin/nothing-here", run: settled },
  {
    name: "console-error",
    surface: "console",
    as: "owner",
    url: "/admin/",
    run: async (p) => {
      await stub(p, "/v1/admin/overview", outcome(500, { detail: "the database file is locked" }));
      await p.goto("/admin/");
      await p.waitForSelector("main .error-state");
    },
  },
  {
    name: "console-loading",
    surface: "console",
    as: "owner",
    url: "/admin/",
    run: async (p) => {
      await p.route("**/v1/admin/overview", () => {}); // never answers: the loading state stays
      await p.goto("/admin/");
      await p.waitForSelector("main .skeleton");
    },
  },
  {
    name: "console-invite",
    surface: "console",
    as: "owner",
    url: "/admin/",
    run: async (p, context) => {
      const created = await (
        await context.request.post(`${BASE}/v1/admin/users/invites`, {
          data: { email: "desk@example.com", role: "staff" },
          headers: { "X-Ira-Request": "1" },
        })
      ).json();
      await context.clearCookies(); // the invitee is not signed in
      await p.goto(created.path);
      await p.waitForSelector("main form");
      await context.request.delete(`${BASE}/v1/admin/users/invites/${created.invite.id}`, { headers: { "X-Ira-Request": "1" } }).catch(() => {});
    },
  },
  // The wizard: step 1 on a server with no owner, later steps as the owner.
  { name: "console-setup", surface: "console", base: "setup", url: "/admin/setup#code=7F3A-91C2-0B4E", run: (p) => p.waitForSelector("main form") },
  { name: "console-setup-2", surface: "console", as: "owner", url: "/admin/setup", step: 2, run: settled },
  { name: "console-setup-3", surface: "console", as: "owner", url: "/admin/setup", step: 3, run: settled },
  { name: "console-setup-4", surface: "console", as: "owner", url: "/admin/setup", step: 4, run: settled },
  { name: "console-setup-5", surface: "console", as: "owner", url: "/admin/setup", step: 5, run: settled },
  { name: "console-setup-6", surface: "console", as: "owner", url: "/admin/setup", step: 6, run: settled },
];

async function shoot(browser, scene, sizeName, theme) {
  const size = SIZES[sizeName];
  const base = scene.base === "setup" ? SETUP_BASE : BASE;
  const context = await browser.newContext({
    baseURL: base,
    viewport: { width: size.width, height: size.height },
    deviceScaleFactor: size.scale,
    colorScheme: theme,
    isMobile: sizeName === "phone",
    hasTouch: sizeName === "phone",
    permissions: scene.mic ? ["microphone"] : [],
  });
  const errors = [];
  const page = await context.newPage();
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  await page.addInitScript((step) => {
    try {
      localStorage.removeItem("ira.today");
      localStorage.removeItem("ira.theme");
      if (step) localStorage.setItem("ira.setup.step", String(step));
      else localStorage.removeItem("ira.setup.step");
    } catch {
      /* ignore */
    }
  }, scene.step || 0);
  if (scene.as) await login(context, scene.as);
  await page.goto(scene.url || "/");
  await scene.run(page, context);
  await page.waitForTimeout(250);
  const file = resolve(OUT, `${scene.name}-${sizeName}-${theme}.png`);
  await page.screenshot({ path: file });
  await context.close();
  return errors;
}

mkdirSync(OUT, { recursive: true });
const normal = await chromium.launch({
  channel: "chrome",
  args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"],
});
const strict = await chromium.launch({ channel: "chrome" }); // real permission prompts: denied
let failures = 0;
for (const scene of SCENES) {
  if (ONLY && !ONLY.some((s) => scene.name.includes(s))) continue;
  if (scene.base === "setup" && !SETUP_BASE) {
    console.log(`${scene.name}: skipped (set IRA_SETUP_BASE to a server with no owner)`);
    continue;
  }
  for (const sizeName of Object.keys(SIZES)) {
    for (const theme of THEMES) {
      try {
        const errors = await shoot(scene.micBlocked ? strict : normal, scene, sizeName, theme);
        const note = errors.length ? `  (page errors: ${errors.join(" | ")})` : "";
        console.log(`${scene.name}-${sizeName}-${theme}${note}`);
      } catch (error) {
        failures += 1;
        console.log(`${scene.name}-${sizeName}-${theme}: FAILED ${error.message.split("\n")[0]}`);
      }
    }
  }
}
await normal.close();
await strict.close();
process.exit(failures ? 1 : 0);
