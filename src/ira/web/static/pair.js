// The page a pairing QR code opens: it shows the one-time code from the link's fragment,
// which the browser never sends to the server.
"use strict";

(() => {
  const match = /(?:^#|&)code=([A-Za-z0-9-]{8,20})/.exec(location.hash);
  if (!match) return;
  const code = match[1].replace(/-/g, "").toUpperCase();
  document.getElementById("pair-code").textContent = `${code.slice(0, 4)}-${code.slice(4)}`;
  // Ira for iPhone opens ira:// links; the code stays out of any request to a server.
  const open = document.getElementById("open-iphone");
  if (open && /iPhone|iPad/.test(navigator.userAgent)) {
    const query = new URLSearchParams({ server: location.origin, code });
    open.href = `ira://pair?${query}`;
    open.hidden = false;
  }
})();
