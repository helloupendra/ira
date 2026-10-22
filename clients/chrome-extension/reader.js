// The reader. Ira's extension injects this into one tab when someone asks Ira about
// that tab, and nothing of it stays behind. It returns the title, the address, the
// visible text (20,000 characters at most) and progress signals: <progress>, ARIA
// progress bars, and text such as "63%", "3 of 7", "Step 4/5", "ETA 4 min",
// "Completed", "Failed", "Done".
//
// It never reads a form: no input, textarea or select, and so never a password.
// The value of the last expression below is what Chrome hands back.
(function iraReadPage(doc, win, limit) {
  "use strict";

  const SKIP = new Set([
    "SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "HEAD", "META", "LINK", "TITLE",
    "SVG", "CANVAS", "IFRAME", "FRAME", "OBJECT", "EMBED", "AUDIO", "VIDEO",
    "INPUT", "TEXTAREA", "SELECT", "OPTION", "OPTGROUP", "DATALIST",
  ]);
  const BLOCK = new Set([
    "ADDRESS", "ARTICLE", "ASIDE", "BLOCKQUOTE", "BR", "DD", "DETAILS", "DIALOG", "DIV",
    "DL", "DT", "FIELDSET", "FIGCAPTION", "FIGURE", "FOOTER", "FORM", "H1", "H2", "H3",
    "H4", "H5", "H6", "HEADER", "HR", "LI", "MAIN", "NAV", "OL", "P", "PRE", "SECTION",
    "SUMMARY", "TABLE", "TBODY", "TD", "TH", "THEAD", "TR", "UL",
  ]);
  const UNITS = "(?:seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h)\\b"; // longest first

  function hidden(el) {
    if (el.hidden || el.getAttribute("aria-hidden") === "true") return true;
    if (el.getAttribute("type") === "password") return true;
    const style = win.getComputedStyle ? win.getComputedStyle(el) : null;
    return !!style && (style.display === "none" || style.visibility === "hidden");
  }

  function visibleText(root) {
    const parts = [];
    let size = 0;
    let truncated = false;
    const walker = doc.createTreeWalker(root, win.NodeFilter.SHOW_ELEMENT | win.NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        if (node.nodeType === win.Node.TEXT_NODE) return win.NodeFilter.FILTER_ACCEPT;
        if (SKIP.has(node.tagName.toUpperCase()) || hidden(node)) return win.NodeFilter.FILTER_REJECT;
        return win.NodeFilter.FILTER_ACCEPT;
      },
    });
    let node = walker.nextNode();
    while (node) {
      if (node.nodeType === win.Node.TEXT_NODE) {
        // Whitespace between inline elements still separates their words.
        const text = node.nodeValue.replace(/\s+/g, " ");
        if (text) {
          parts.push(text);
          size += text.length;
        }
      } else if (BLOCK.has(node.tagName.toUpperCase())) {
        parts.push("\n");
      }
      if (size > limit) {
        truncated = true;
        break;
      }
      node = walker.nextNode();
    }
    const text = parts
      .join("")
      .split("\n")
      .map((line) => line.replace(/ +/g, " ").trim())
      .filter(Boolean)
      .join("\n");
    return { text: text.slice(0, limit), truncated: truncated || text.length > limit };
  }

  function number(value) {
    const n = parseFloat(String(value).replace(",", "."));
    return Number.isFinite(n) ? n : null;
  }

  function bars() {
    const found = [];
    for (const el of doc.querySelectorAll("progress")) {
      if (hidden(el) || !el.hasAttribute("value")) continue;
      const value = number(el.getAttribute("value"));
      const max = number(el.getAttribute("max")) || 1;
      if (value !== null) found.push({ source: "progress", percent: Math.round((value / max) * 1000) / 10 });
    }
    for (const el of doc.querySelectorAll("[role=progressbar], [aria-valuenow]")) {
      if (hidden(el)) continue;
      const now = number(el.getAttribute("aria-valuenow"));
      if (now === null) continue;
      const min = number(el.getAttribute("aria-valuemin")) || 0;
      const max = number(el.getAttribute("aria-valuemax"));
      const top = max === null ? 100 : max;
      if (top <= min) continue;
      found.push({
        source: el.getAttribute("role") === "progressbar" ? "progressbar" : "aria",
        percent: Math.round(((now - min) / (top - min)) * 1000) / 10,
        label: (el.getAttribute("aria-valuetext") || el.getAttribute("aria-label") || "").slice(0, 80),
      });
    }
    return found.slice(0, 10);
  }

  function all(pattern, text, make) {
    const out = [];
    for (const match of text.matchAll(pattern)) {
      const item = make(match);
      if (item !== null && !out.some((seen) => JSON.stringify(seen) === JSON.stringify(item))) out.push(item);
      if (out.length >= 10) break;
    }
    return out;
  }

  function signals(text) {
    const percents = all(/(\d{1,3}(?:[.,]\d+)?)\s?%/g, text, (m) => {
      const n = number(m[1]);
      return n !== null && n <= 100 ? n : null;
    });
    const counts = [
      ...all(new RegExp("\\b(?:step|stage|part|task|job|file)\\s+(\\d{1,4})\\s*(?:/|of)\\s*(\\d{1,4})\\b", "gi"), text, (m) => {
        const done = Number(m[1]);
        const total = Number(m[2]);
        return total > 0 && done <= total ? { done, total, text: m[0] } : null;
      }),
      ...all(/\b(\d{1,4}) of (\d{1,4})\b/gi, text, (m) => {
        const done = Number(m[1]);
        const total = Number(m[2]);
        return total > 0 && done <= total ? { done, total, text: m[0] } : null;
      }),
    ].slice(0, 10);
    const eta = [
      ...all(new RegExp(`\\bETA:?\\s*(\\d[\\d:]*(?:\\s*${UNITS})?)`, "gi"), text, (m) => m[1].trim()),
      ...all(new RegExp(`\\b(\\d+\\s*${UNITS})\\s+(?:left|remaining)\\b`, "gi"), text, (m) => m[1].trim()),
    ].slice(0, 5);
    const status = all(
      /\b(completed|complete|done|finished|succeeded|success|uploaded|failed|failure|error|cancell?ed)\b/gi,
      text,
      (m) => m[1].toLowerCase(),
    );
    return { percents, counts, eta, status };
  }

  const body = doc.body || doc.documentElement;
  const { text, truncated } = visibleText(body);
  const title = (doc.title || "").trim();
  return {
    title,
    url: String(win.location.href),
    text,
    truncated,
    progress: { bars: bars(), ...signals(`${title}\n${text}`) },
  };
})(document, window, 20000);
