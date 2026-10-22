# The Ira companion for Mac

The companion lets your own Ira read and watch your Chrome tabs when you
ask. It has two parts: a small program that runs in the background on your
Mac (the companion), and the **Ira for Chrome** extension. The
[quick start](../personal-assistant.md) walks through setting both up.

## Install

1. On **Your devices** in the Ira app (or **Devices** in the console), add a
   Mac and make a pairing code. It needs your PIN, and works once for 10
   minutes.
2. Download `ira-mac.zip` from that page (or from the project's GitHub
   Releases), and open it.
3. In Terminal: `cd ~/Downloads/ira-mac && ./install.sh`. Paste the pairing
   link when it asks.
4. In Chrome: `chrome://extensions`, Developer mode on, **Load unpacked**,
   and choose `~/Library/Application Support/ira-mac/chrome-extension`.

Running `./install.sh` again updates the companion and keeps its pairing.
`./install.sh --pair` pairs it again with a new code.

A typed code goes to the server named by `--server`, else to the server the
zip came from (a zip from `/v1/downloads` carries its address in
`server.txt`), else to the one this Mac paired with before. With none of
these (the zip from GitHub Releases), the companion asks for the address; it
never guesses. A pasted link always names its own server.

The installer needs Python 3.9 or newer, which macOS offers to install with
its Command Line Tools (`xcode-select --install`). It downloads one library
(`websockets`) from the Python Package Index. It never asks for your
administrator password.

## What it sets up

| Where | What |
| --- | --- |
| `~/Library/Application Support/ira-mac/` | the companion, its Python environment, its logs, and a socket only you can open |
| `~/Library/LaunchAgents/in.ira.mac.plist` | starts the companion when you log in, and again if it stops |
| `~/Library/Application Support/Google/Chrome/NativeMessagingHosts/in.ira.mac.json` | lets only the Ira extension (id `lidenefpfghfkmlcddnbjmladjhobdhp`) talk to the companion |
| Your login Keychain, item `ira-mac` | this Mac's own key for your IRA server. Never in a file or a log |

## Permissions

- **The extension** asks Chrome for: `tabs` (to see tab titles and
  addresses, so Ira can find "the upload tab"), `scripting` (to read the one
  tab you asked about, at that moment), `nativeMessaging` (to talk to the
  companion, its only connection), and access to all sites (Chrome lets an
  extension read a page only on sites it may access). It has no network
  access of its own.
- **The companion** needs no special macOS permission. It is installed in
  `~/Library/Application Support` on purpose: macOS does not let background
  programs read your Documents folder, and this version of the companion
  reads nothing there.
- **On your IRA server**, the Mac may only do what its **skills** allow. In
  this version that is **Chrome**, which you switch on (with your PIN) or
  off on **Your devices**.

## What Ira can see, and what it cannot

Ira **can**, when you ask:

- list your open tabs: their titles and addresses, without the part after
  `?` or `#` (which can hold private codes);
- read one tab: its title, address, up to 20,000 characters of the text on
  screen, and its progress ("63%", "Step 4/5", "ETA 4 min", "Completed");
- watch one tab until it finishes, closes, goes quiet, or an hour passes,
  and tell you. At most 5 at a time.

Ira **cannot**:

- read anything you did not ask about. No part of the extension runs in a
  page until you ask;
- read form fields: not what you typed, and never a password;
- read Chrome's own pages (`chrome://`), the Chrome Web Store, PDFs, or files
  on your Mac;
- click, type, open pages or change anything in Chrome in this version;
- read your Documents folder, or any file.

What a tab said goes into your conversation with Ira, and only you see it:
an owner or admin reading the conversation sees "private" in its place.
"What Ira did" in the app shows that a tab was read, and when; never its
text. The companion's own logs (`~/Library/Application Support/ira-mac/logs`)
hold tool names, tab numbers and timings, never page text or full addresses.

## Its routine

Only if you switch the **routine** skill on for this Mac (under **Your
devices**, with your PIN), and only while learning is on for you, the
companion tells Ira, every 30 seconds at most:

- when the screen **locks** and **unlocks**;
- when the Mac **sleeps** and **wakes** (a gap between the wall clock and
  the Mac's own uptime clock is a sleep);
- the first keyboard or mouse use of the day;
- **which network** it is on, as a code: a hash of the router's hardware
  address with a salt that never leaves this Mac. Neither the network's
  name nor any address leaves the Mac; you name the network (Office, Home)
  on your Ira page.

It never reads what is on the screen, which apps run, your location or any
file. What Ira does with this is in [What Ira learns](../learning.md).

## Remove it

- **Stop Ira using it now:** remove the Mac on **Your devices** (or switch
  Chrome off there). Its key stops working at once and it disconnects.
- **Remove it from the Mac:** `./uninstall.sh` in the `ira-mac` folder. It
  tells your IRA server to forget this Mac, stops the companion, and removes
  its files, its Keychain item and Chrome's link to it. Then remove **Ira
  for Chrome** in `chrome://extensions`.

## Check on it

```bash
PYTHONPATH="$HOME/Library/Application Support/ira-mac/app" \
  "$HOME/Library/Application Support/ira-mac/venv/bin/python" -m ira_mac status
```

prints the server it pairs with, the device number, whether the key is in
the Keychain (never the key), and whether the companion is running. Its log
is `~/Library/Application Support/ira-mac/logs/ira-mac.log`.

For developers: the protocol and limits are in [Devices](../devices.md), and
the code in `clients/mac/` and `clients/chrome-extension/`.
