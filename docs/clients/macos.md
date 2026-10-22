# Ira for Mac

**Ira for Mac** is a small app that lives in your menu bar. Press
**Option-Space** anywhere, and a window opens where you can type to Ira or
press the mic and talk. Ira can then find a file on your Mac, read it to you,
open it, and read the window in front of you, in any app:

> vo PDF kahan hai jo kal download kiya?
>
> padh kar sunao
>
> screen pe kya hai?

It needs no browser extension and no Terminal. It replaces the
[Mac companion](mac.md) for most people; the companion stays for Chrome tabs
and coding tasks.

Ira reads nothing until you ask, and only with the skills you switch on. See
[what Ira can and cannot see](#what-ira-can-and-cannot-see).

## Install

You need a Mac with macOS 14 (Sonoma) or newer, and your own Ira running
somewhere: on this Mac, on a server, or one your family or team shares (see
[the quick start](../personal-assistant.md)).

1. Download **Ira-0.1.0.dmg** from the project's GitHub page (Releases, or
   the latest build's artifacts) and open it.
2. Drag **Ira** onto **Applications**.
3. Open Applications and find Ira. The first time only, macOS will not open
   it straight away, because the app is not yet signed by a registered
   developer:
    - **macOS 14:** right-click (or Control-click) Ira, choose **Open**, then
      **Open** again.
    - **macOS 15 and later:** double-click Ira, choose **Done**, then open
      **System Settings → Privacy & Security**, scroll down to the message
      about Ira, and choose **Open Anyway**.

    After that, Ira opens like any other app. A small mark of four bars
    appears in the menu bar.

## Pair it with your Ira

Pairing tells this Mac which Ira is yours, once.

1. In the Ira app in your browser, open the menu and choose **Your devices**.
2. Under **Add a device**, choose **Mac**, give it a name, and tick what it
   may do: **Files** (find, read and open your files) and **Screen** (read
   the window in front). Type your PIN and press **Make a pairing code**.
3. Press **Copy the pairing link**.
4. On the Mac, press **Option-Space** (or click the four bars in the menu bar
   and choose **Open Ira**). Ira shows **Pair this Mac with your Ira** and
   usually fills in the link it finds on your clipboard. Press **Pair**.

    You can also type the code (`ABCD-EFGH`) and your Ira's address.

The code works once, for 10 minutes. This Mac gets its own key, which Ira
keeps in your Keychain, never in a file. You can switch Files or Screen on or
off later on **Your devices**; switching one on needs your PIN.

## Grant permissions

After pairing, Ira shows **What Ira may use on this Mac**. Each permission
has one plain sentence:

| Permission | Why | When macOS asks |
| --- | --- | --- |
| **Microphone** | So you can talk to Ira. It listens only after you press the mic, and stops when you press it again or stay quiet for a while. | when you press **Allow**, or the mic the first time |
| **Files and folders** | So Ira can find a file and read it to you. | the first time Ira opens something in Documents, Desktop or Downloads: choose **Allow** |
| **Screen Recording** | Only for "what is on my screen?". Ira takes a picture of the window in front, reads its words on this Mac, and sends only the words. | when you press **Allow**; macOS then sends you to System Settings to switch Ira on |

You can change any of these in **System Settings → Privacy & Security**.

!!! note "After an update"
    Until the app is signed by a registered developer, macOS treats each new
    version as a new app: it may ask for these permissions again, and ask
    once whether Ira may use its key in your Keychain (choose **Always
    Allow**).

## Talk to Ira

- **Type** in the window and press Return.
- **Talk:** press the green mic. Speak normally; Ira answers when you stop,
  and you can speak again without pressing anything. Start speaking while
  Ira talks and she stops at once and listens. Press the mic again to stop
  listening (Ira also stops by itself after 45 quiet seconds).
- **Hindi, English or Hinglish** all work; Ira answers in the language you
  used, or the one you chose under **Your assistant**.
- **When Ira proposes something** that changes the world (a message, an
  event), the window shows it with **Yes** and **No**; or just say "haan" or
  "nahi". Anything that needs your PIN is confirmed in the Ira app in your
  browser, never by voice.

Ira talks over a live connection when your Ira server offers live voice. If
it does not yet, the window asks you to **sign in** once with your Ira email
and password, and then uses the server's ordinary voice and chat instead.

**Settings…** (in the menu-bar menu, or the **⋯** button) changes the
shortcut, whether typed answers are spoken too, and which folders Ira may
use.

## What Ira can and cannot see

Ira **can**, only when you ask:

- **find files** with Spotlight, by name, by words inside them, by kind
  (PDF, Word, image...) and by date, in your home folder: up to 20, with
  their names, folders, sizes and dates;
- **read a file**: PDF, Word (.docx), RTF, text and Markdown, up to 20,000
  characters;
- **open a file** in its usual app, or open an app from Applications. Ira
  says when it did;
- **read the window in front**, in any app: Ira reads its words on this Mac
  and sends only them, with the app's name and the window's title. No
  picture ever leaves the Mac.

Ira **cannot**:

- read anything you did not ask about. Nothing runs in the background;
- read your **Library folder** (mail, messages, browser data, the Keychain),
  **hidden files and folders** (such as `.ssh` and `.aws`), or files that
  hold keys and passwords (`.env`, `.pem`, `.key`, `id_rsa`, password
  databases). These are refused even if you ask;
- read outside your home folder, unless you add a folder (a drive, say) in
  **Settings → Folders**. You can also narrow Ira to a few folders there;
- open scripts, installers, programs or web links: these could run
  something;
- see the screen at all unless the **Screen** skill is on and you allowed
  Screen Recording.

What Ira reads goes to your own Ira server, marked as data that can never
give Ira orders, and is kept only in that conversation (see
[Privacy](../privacy.md)).

**What I read** (the list button at the top of the window, and the
menu-bar menu) shows the last things Ira used on this Mac: what it did and
on which file or window, never what was in them. The app's own log, in
`~/Library/Logs/Ira/`, holds only tool names and timings.

## Remove Ira from this Mac

- **Settings → Remove this Mac** tells your Ira server to forget this Mac (its
  key stops working at once) and deletes the key from your Keychain.
- Or remove the Mac on **Your devices**: it disconnects at once.
- Then drag Ira from Applications to the Bin.

## If something does not work

| You see | Do this |
| --- | --- |
| "Not paired: that code is used, expired or mistyped" | Make a new code on **Your devices** and paste the new link |
| "use https:// for a server on another machine" | Your Ira's address must start with `https://`, unless it runs on this Mac |
| The menu says "This Mac was removed from Ira" | It was removed on **Your devices**: choose **Settings → Pair again** |
| Ira says Screen Recording is off | **System Settings → Privacy & Security → Screen & System Audio Recording**, switch Ira on, then quit and reopen Ira |
| Ira says macOS did not let it open a file | **System Settings → Privacy & Security → Files and Folders**, switch on Ira's folders |
| Option-Space does nothing | Another app took it: choose a new shortcut in **Settings → Shortcut** |

## For developers: building from source

The app is a Swift package in `clients/macos/`. It builds with the Command
Line Tools alone (`xcode-select --install`); Xcode is not needed.

```bash
cd clients/macos
swift build                  # debug build
scripts/test.sh              # the tests (Swift Testing)
scripts/make-app.sh          # dist/Ira.app, dist/Ira-<version>.zip and .dmg
UNIVERSAL=1 scripts/make-app.sh   # Apple silicon and Intel in one app
```

`make-app.sh` builds in release mode, draws the icon from
`src/ira/web/static/icon.svg` with `sips` and `iconutil`, writes
`Info.plist` (bundle id `in.ira.mac`, `LSUIElement`, the permission
sentences), signs ad hoc with `codesign --sign -`, and packs the zip and the
dmg with `ditto` and `hdiutil`. CI runs the same three commands on a macOS
runner and keeps the zip and dmg as the run's artifacts.

`scripts/test.sh` is `swift test`, plus the folder of the Swift Testing
macros when only the Command Line Tools are installed (the compiler is not
told where they are). For the same reason the views keep their state in
small observable objects rather than SwiftUI's `@State`, which the newest
SDKs make a macro whose plugin ships with Xcode only.

**Layout:**

| Where | What |
| --- | --- |
| `Sources/IraKit/Device/` | pairing (`POST /v1/devices/pair`, as the Python companion's `exchange()`), the device WebSocket's frames, and the client that holds it: hello, calls, ping and pong, 90-second silence, reconnect with backoff, `bye` when removed |
| `Sources/IraKit/Tools/` | the tools and their JSON Schemas, skills and tiers; the path policy and its deny list; Spotlight; PDF, Word, RTF and text reading; ScreenCaptureKit and Vision |
| `Sources/IraKit/Voice/`, `Talk/` | `VoiceTransport`: live voice over `/v1/voice/live` ([Real-time voice](../realtime.md), protocol 1) with the device token, or the HTTP API with a signed-in session; the energy voice detector; sentence splitting |
| `Sources/Ira/` | the app: menu bar, the global hotkey (Carbon, so no Accessibility permission), the floating window, microphone and speaker on one `AVAudioEngine` with echo cancellation |
| `Tests/IraKitTests/` | pairing against a URLProtocol stub, device and live-voice frames against a fake WebSocket, the deny list, a tiny `.docx` fixture, a PDF drawn in the test, tool schemas, and the voice detector on synthetic audio. No test opens a network connection |

The tools the app offers:

| Tool | Skill | Tier | What it does |
| --- | --- | --- | --- |
| `files_find {query?, kind?, modifiedWithinDays?, folder?}` | `files` | 0 | Spotlight, up to 20 results |
| `file_read {path, maxChars?}` | `files` | 0 | PDF, Word, RTF, text, Markdown; 20,000 characters at most |
| `file_open {path}` | `files` | 1 | `NSWorkspace.open`; never scripts, installers or links |
| `screen_read {}` | `screen` | 0 | the front window's text, read on the Mac |

There are no third-party dependencies: everything comes with macOS.
