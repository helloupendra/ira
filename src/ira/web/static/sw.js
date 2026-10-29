// A minimal service worker: it makes the app installable and keeps the shell
// available offline. It never touches /v1 (the API) or /admin: answers,
// audio and actions must always come from the server, never from a cache.
// It also takes what is shared to the installed app (Share → Ira) for Drop.

const CACHE = "ira-shell-v22";
const SHARE = "ira-share";
const SHELL = [
  "/",
  "/app.js",
  "/personal.js",
  "/live.js",
  "/style.css",
  "/tokens.css",
  "/recorder-worklet.js",
  "/manifest.webmanifest",
  "/icon.svg",
  "/icon-192.png",
  "/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE && k !== SHARE).map((k) => caches.delete(k)))),
  );
  self.clients.claim();
});

// Share → Ira: keep what was shared, then open the app, which shows it and sends it to
// your Drop only when you say so. Nothing here leaves the phone until then. A post that
// another site made (its page named as the referrer) is not kept at all; one that hides
// its referrer still waits for that yes.
async function keepShared(request) {
  try {
    await caches.delete(SHARE);
    if (request.referrer && new URL(request.referrer).origin !== self.location.origin) return Response.redirect("/", 303);
    const form = await request.formData();
    const cache = await caches.open(SHARE);
    const files = form.getAll("files").filter((file) => typeof file !== "string" && file.size);
    for (const [index, file] of files.entries()) {
      const headers = { "Content-Type": file.type || "application/octet-stream", "X-Name": encodeURIComponent(file.name || "file") };
      await cache.put(`/shared/${index}`, new Response(file, { headers }));
    }
    const words = Object.fromEntries(["title", "text", "url"].map((key) => [key, String(form.get(key) || "")]));
    await cache.put("/shared/meta", new Response(JSON.stringify({ ...words, files: files.length })));
  } catch {
    /* nothing kept: the app opens anyway */
  }
  return Response.redirect("/?share=1", 303);
}

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method === "POST" && url.origin === self.location.origin && url.pathname === "/share") {
    event.respondWith(keepShared(event.request));
    return;
  }
  if (event.request.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/v1/") || url.pathname.startsWith("/admin")) return;
  // Network first, so a new version shows up at once; the cache is the offline fallback.
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response.ok && SHELL.includes(url.pathname)) {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(event.request, copy));
        }
        return response;
      })
      .catch(() => caches.match(event.request).then((hit) => hit || caches.match("/"))),
  );
});
