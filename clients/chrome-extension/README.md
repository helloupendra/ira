# Ira for Chrome

A Manifest V3 extension that lets your own Ira read and watch a Chrome tab
when you ask: "Chrome mein kaunse tabs khule hain?", "us upload tab mein kitna
hua?", "jab khatam ho jaaye, batana".

It works with the [Ira companion for Mac](../mac/README.md), which must be
installed first: the extension talks only to the companion, and the companion
talks to your IRA server.

## What it does, and what it never does

- It **lists your tabs** (id, title, and the address without its query or
  fragment) when the companion asks.
- It **reads one tab** when the companion asks: it injects `reader.js` into
  that tab, which returns the title, the address, up to 20,000 characters of
  visible text, and progress signals (`<progress>`, ARIA progress bars, and
  text such as "63%", "3 of 7", "Step 4/5", "ETA 4 min", "Completed",
  "Failed", "Done"). Then nothing of it stays in the page.
- It **never reads form fields**: no `input`, `textarea` or `select`, and so
  never a password, nor what you typed into a form.
- **No content script runs all the time.** Nothing is injected into any page
  until someone asks Ira about that page.
- **No network of its own.** The extension makes no requests; it speaks only
  to the native messaging host `in.ira.mac` on this Mac.
- Chrome's own pages (`chrome://`), the Chrome Web Store and PDF viewer tabs
  cannot be read by any extension; Ira says so plainly. It does not read
  `file://` pages.

## Permissions, one by one

| Permission | Why |
| --- | --- |
| `tabs` | to see each tab's title and address, so Ira can find "the upload tab" |
| `scripting` | to inject the reader into the one tab you asked about, at that moment |
| `nativeMessaging` | to talk to the Ira companion on this Mac (`in.ira.mac`), its only connection |
| `<all_urls>` (host permission) | Chrome lets an extension read a page only on sites it may access; reading "any tab you ask about" needs all of them. It is used only on request |

## Install (unpacked)

1. Install the Mac companion (`clients/mac/install.sh`). It copies this
   folder to `~/Library/Application Support/ira-mac/chrome-extension`.
2. Open `chrome://extensions`, switch on **Developer mode** (top right).
3. **Load unpacked**, and choose that folder.
4. Click the extension's icon: it says "Connected" when the companion runs.

The extension's id is fixed by the public `key` in `manifest.json`:
`lidenefpfghfkmlcddnbjmladjhobdhp`. The companion's native messaging manifest
allows only that id. No private key exists in this repository; the
extension is not signed or published to the Chrome Web Store.

## Develop

```bash
npm ci
npm test          # node --test, with jsdom fixture pages
```

`test/fixtures/` holds pages for the reader: an upload at 63%, a CI page at
Step 4/5, a page that says Completed, and a sign-in form whose values must
never be read.
