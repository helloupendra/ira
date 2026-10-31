# Ira for Mac

**Ira for Mac** is a small app that lives in your menu bar. Press
**Option-Space** anywhere, and a window opens where you can type to Ira or
press the mic and talk. Ira can then use what your Mac can do, for you, when
you ask: find a file and read it to you, read the window in front of you in
any app, look up who a number belongs to, check your calendar, draft an
email, send an iMessage, run one of your Shortcuts, or start a coding task:

> vo PDF kahan hai jo kal download kiya?
>
> padh kar sunao
>
> screen pe kya hai?
>
> 98765 43210 kiska number hai? usko message karo ki main 10 minute late hoon
>
> kal ka calendar batao

It needs no browser extension and no Terminal. It is the one Mac client: it
replaces the old Python companion and the Chrome extension, and takes over
from them by itself (see [Moving from the old companion](#moving-from-the-old-companion)).

Ira reads nothing until you ask, and only with the skills you switch on. See
[what Ira can and cannot see](#what-ira-can-and-cannot-see).

## Install

You need a Mac with macOS 14 (Sonoma) or newer, and your own Ira running
somewhere: on this Mac, on a server, or one your family or team shares (see
[the quick start](../personal-assistant.md)).

1. Download **Ira.dmg** (the link on **Your devices**, or the project's
   latest GitHub Release) and open it.
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
   may do. **Files** (find, read and open your files), **Screen** (read the
   window in front) and **Browser** (your open tabs) are ticked for you; tick
   Contacts, Calendar, Mail or the others too if you want them, or switch
   them on later on the Mac's card. Type your PIN and press **Make a pairing
   code**.
3. Press **Copy the pairing link**.
4. On the Mac, press **Option-Space** (or click the four bars in the menu bar
   and choose **Open Ira**). Ira shows **Pair this Mac with your Ira** and
   usually fills in the link it finds on your clipboard. Press **Pair**.

    You can also type the code (`ABCD-EFGH`) and your Ira's address.

The code works once, for 10 minutes. This Mac gets its own key, which Ira
keeps in your Keychain, never in a file. You can switch skills on or off
later on **Your devices**; switching one on needs your PIN.

### Moving from the old companion

If the Python companion (installed with `./install.sh`) is still on this
Mac, Ira for Mac says so on its first page and offers:

- **Use its pairing and remove it**: Ira for Mac takes over the companion's
  pairing (its server, key and network code, so named places keep their
  names) and needs no new code. It then stops the companion and removes it
  from this Mac, as its `uninstall.sh` did.
- **Remove it and pair with a new code**: the companion tells your Ira to
  forget it, is removed, and you pair Ira for Mac as above.

Remove the old Ira extension in `chrome://extensions` yourself: Ira for Mac
reads your tabs without it.

## Grant permissions

The first time, Ira walks you through three steps: **Pair**, **Allow** and
**Try it** (a test question that checks the whole way). On **Allow**, each
permission has one plain sentence, shows whether it is allowed, and has
**Allow** or **Open System Settings** beside it. **Settings → Permissions**
shows the same list later. While System Settings is open, Ira's window
steps aside, so nothing covers a password sheet there.

| Permission | Why | When macOS asks |
| --- | --- | --- |
| **Microphone** | So you can talk to Ira. It listens only after you press the mic, and stops when you press it again or stay quiet for a while. | when you press **Allow**, or the mic the first time |
| **Files and folders** | So Ira can find a file and read it to you. Until you allow a folder, Spotlight leaves it out of every search without a word, so Documents, Desktop and Downloads each have their own row. | when you press **Allow** on that row, or the first search that covers the folder: choose **Allow** |
| **Screen Recording** | Only for "what is on my screen?". Ira takes a picture of the window in front, reads its words on this Mac, and sends only the words. | when you press **Allow**; macOS then sends you to System Settings to switch Ira on. macOS applies it only after Ira restarts: Ira shows **Reopen Ira** (or **Restart Ira**) for that |
| **Contacts** | So Ira can put a name to a number, or find the number or email to write to. | when you press **Allow**, or the first lookup |
| **Calendars and Reminders** | So Ira can tell you what is on your day, and add an event or a reminder. A new event waits for your yes. | when you press **Allow** |
| **Automation: Mail, Notes, Messages** | So Ira can search your inbox and notes, draft an email, and send an iMessage. | the first time Ira uses each app ("Ira wants to control Mail") |
| **Automation: your browser** | So Ira can list your Chrome, Safari, Arc, Edge or Brave tabs and bring one to the front. Never page contents or passwords. | the first time Ira looks at that browser |
| **Speech Recognition** | Only for "Hey Ira", if you switch it on: the Mac listens for the phrase by itself. | when you switch "Hey Ira" on |
| **Accessibility** | Only for the control skill: typing, keys, clicks, scrolling and menus in other apps, after your PIN. | when you press **Allow**; macOS then sends you to System Settings to switch Ira on |
| **Documents** (coding tasks only) | Ira works in your repositories, which often live in Documents. | the first coding task |

You can change any of these in **System Settings → Privacy & Security**.

!!! note "After an update"
    Until the app is signed by a registered developer, macOS treats each new
    downloaded version as a new app: it may ask for these permissions again
    (in Privacy & Security, remove the old Ira with "−" and switch the new
    one on), and ask once whether Ira may use its key in your Keychain
    (choose **Always Allow**). You do not need to pair again. If you build
    Ira yourself, a signing identity made once keeps the permissions: see
    [building from source](#for-developers-building-from-source).

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
  "nahi". Anything that needs your PIN shows a PIN box: type it there (it
  goes only to your Ira's confirm step, never to the assistant). Never say a
  PIN aloud.
- **While Ira works**, the window shows moving dots and the step ("Finding
  files…", "Reading the screen…"), the seconds after 3, and after 30 seconds
  with nothing, "No answer yet" with **Try again**. Every problem shows in
  the window with what to do next. The dot next to Ira's name says, when you
  point at it, whether this Mac is connected.
- **The window** hides when you click another app, and comes back with
  Option-Space; a question still running carries on, and its answer arrives
  as a notification. Press the **pin** to keep it on top while you work in
  other apps. Esc closes it. It remembers where you put it and its size.
- **Copy and paste** work as everywhere (Cmd-C, Cmd-V, Cmd-X, Cmd-A, Cmd-Z),
  and you can select and copy any answer.

Ira talks over a live connection when your Ira server offers live voice, and
over its ordinary voice and chat when it does not, with this Mac's own key
either way: no email or password. When live voice fails to start, Ira carries
on over the ordinary voice and tries live again the next time you press the
mic, and when this Mac reconnects to your Ira.

**Settings…** (in the menu-bar menu, or the **⋯** button) changes the
shortcut, "Hey Ira", whether typed answers are spoken too, starting at
login, and which folders Ira may use, and shows each permission.

## "Hey Ira"

Off until you switch it on in **Settings**. Then the Mac listens for "Hey
Ira" (or the wake phrase you chose under **Your assistant**) by itself, with
macOS's speech recognition on this Mac: no sound and no words leave the Mac
until it hears the phrase. Then the window opens and Ira listens as if you
had pressed the mic. The menu-bar mark shows a dot while it listens. It
needs the Microphone and Speech Recognition permissions, and English speech
recognition on the Mac (Siri and Dictation languages, downloaded).

## Routine

If you switch on the **Routine** skill for this Mac, Ira for Mac tells your
Ira, every 30 seconds while something changed, when the Mac locks, unlocks,
sleeps and wakes, its first activity of the day, and which network it is
on, as a code made with a salt kept on this Mac. Never the network's name,
never what is on the screen or which apps run. See [What Ira
learns](../learning.md).

## Drop: send anything to your other devices

Drop is your own inbox, shared by your devices (see
[Privacy](../privacy.md#drop)). In the menu-bar menu, **Drop** lists the
newest five; each has **Copy** first for text and links (and **Open
Link**), and **Save to Downloads/Ira and Show** for a file.

- **Drag** files, a link or text onto Ira's menu-bar icon to send them.
- **⌃⌥⌘V** sends the clipboard (text, or files copied in the Finder);
  **⌃⌥⌘C** copies the newest item. Both are in the menu too, with **Send
  Files to Drop…**.
- Text from another device comes as a notification with **Copy**. A file
  is saved to `~/Downloads/Ira` at once (never over a file already there,
  checked against its fingerprint, and marked as downloaded, so macOS
  checks it before it opens), with **Show in Finder**.

## What Ira can do on your Mac

Each ability belongs to a **skill** you switch on for this Mac on **Your
devices**, with your PIN; nothing is on until you do. Each has a **tier**:
reading needs nothing more (Tier 0); opening or adding something small, Ira
does and tells you (Tier 1); anything that reaches another person or changes
your calendar, Ira reads back exactly ("Send *I am 10 minutes late* to Avery
Example, +91 98765 43210?") and waits for your yes (Tier 2); pushing code
and using the Mac for you need your PIN (Tier 3).

| Skill | What Ira can do | Tier |
| --- | --- | --- |
| **files** | find files (Spotlight), read one (PDF, Word, RTF, text), open one, or open a folder in VS Code | 0, 0, 1 |
| **screen** | read the text of the window in front | 0 |
| **browser** | list your tabs in Chrome, Safari, Arc, Edge or Brave (titles and addresses); bring one to the front, so Ira can read it from the screen | 0; 1 |
| **contacts** | look up a person by name, number or email | 0 |
| **calendar** | read your calendars (iCloud, Google, Exchange: all those added to the Mac); add an event | 0; 2 |
| **reminders** | list reminders; add one or mark one done | 0; 1 |
| **mail** | search the inbox and read an email (read only); draft an email, opened in Mail for you to send | 0; 2 |
| **notes** | search and read Apple Notes; add a note | 0; 1 |
| **messages** | send an iMessage to a number or email | 2 |
| **apps** | open an app; open a web page | 1; 2 |
| **clipboard** | read what you copied, when you ask | 0 |
| **shortcuts** | list your Shortcuts; run one (it can do whatever you built it to) | 0; 2 |
| **control** | use the Mac like a person: type, press keys, click, scroll, choose a menu item ([below](#using-the-mac-for-you)) | 3 |
| **tasks** | start, follow and stop a coding task; push its branch | 2, 0, 1; 3 |
| **routine** | lock, sleep, wake and the network's code, for learning your day | (no tool) |

Ira chains these by itself: "98765 43210 kiska number hai?" looks the number
up in Contacts; "usko message karo..." then proposes the message to that
person, and sends it on your "haan".

### Using the Mac for you

With the **control** skill on and **Accessibility** allowed for Ira (its
checklist has a row for it), Ira can do what you would do with the keyboard
and mouse:

| Tool | Does |
| --- | --- |
| `mac_click` | clicks a button, link, tab, checkbox or row by its label as shown ("Subscribe", "Downloads"); a field gets the cursor. If no control has that name, it clicks where the words are written (that needs Screen Recording) |
| `mac_type` | types into the field that has the cursor, and presses Return if asked |
| `mac_keys` | presses keys or a shortcut: `cmd+l`, `cmd+shift+t`, `return`, `esc`, `down down return` |
| `mac_scroll` | scrolls the front window up, down, left or right |
| `mac_menu` | chooses a menu item: `File > New Window`, `View > Show Sidebar` |

- **It prefers a direct way.** "Play lofi on YouTube" opens
  `https://www.youtube.com/results?search_query=lofi` with `url_open`;
  "open Notes" uses `app_open`. Clicking and typing are for what has no
  direct tool.
- **Your PIN, then an approval.** Each step is Tier 3. Confirming one with
  your PIN opens an **approval** for this Mac (15 minutes unless you chose
  otherwise on **Your assistant**): the next steps of the task run without
  asking. Meanwhile Ira's window shows "Ira can control this Mac for 12 more
  minutes" with **Stop**, the menu-bar mark turns orange, and its menu has
  **Stop It Now**. Sending, paying, deleting, pushing and new grants still
  ask every time ([Security](../security.md#approvals-fewer-pins-for-one-task)).
- **Touch ID instead of the PIN.** In **Settings → Using this Mac for you**,
  type your PIN once and press **Set Up Touch ID**: Ira makes a key in this
  Mac's Secure Enclave that signs only after your fingerprint (a fingerprint
  added later voids it), and a **Touch ID** button then shows next to the
  PIN box. What it signs is the action's id, what you were shown and when it
  expires. Pairing again or removing Ira removes the key.
- **Trusted apps.** Apps you trust on this Mac (for example Music or
  Chrome) let Ira act without asking, outside an approval too, as long as
  the app is in front. Settings lists them; **Change on the Web…** opens
  **Your assistant → Trusted apps** in your Ira, where adding one needs
  your PIN. Each step's answer names the app in front by its bundle id
  (`"app": "com.google.Chrome"`), and the trust holds only while it is a
  trusted one.
- **It says what it did, never what it saw**: "Clicked the Subscribe button
  in Safari. Safari is in front now.", with the app in front's bundle id.
  Ira looks with `screen_read` before the next step.
- **Never**: in a password field (or while macOS's secure typing is on),
  in a password manager or Keychain Access, in System Settings except
  everyday pages (Appearance, Displays, Sound, Notifications, Focus and the
  like), or in the Apple menu (shut down, restart, log out).
- While Ira types or clicks, its window steps below the app it works in and
  lets go of the keyboard. Press Option-Space to bring it back.

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
  picture ever leaves the Mac;
- **list your browser tabs**: their titles and addresses (without the part
  after `?` or `#`), and bring one to the front so it can read it from the
  screen, as you would look at it.

Ira **cannot**:

- read anything you did not ask about. Nothing runs in the background,
  except "Hey Ira" if you switch it on, which listens on the Mac itself;
- read a web page through the browser, form fields or passwords; or the
  windows of System Settings, the password prompt, Keychain Access and
  password managers (it says so by name);
- read your **Library folder** (mail, messages, browser data, the Keychain;
  however its name is written, `~/LIBRARY` too),
  **hidden files and folders** (such as `.ssh` and `.aws`), or files that
  hold keys and passwords (`.env`, `.pem`, `.key`, `id_rsa`, password
  databases). These are refused even if you ask;
- read outside your home folder, unless you add a folder (a drive, say) in
  **Settings → Folders**. You can also narrow Ira to a few folders there;
- open scripts, installers, programs or web links: these could run
  something; nor open or act in Terminal, Script Editor, Automator,
  Shortcuts or the like, where whatever is typed runs as a command;
- see the screen at all unless the **Screen** skill is on and you allowed
  Screen Recording;
- type, press keys or click in any app unless the **control** skill is on,
  you allowed Accessibility, and you gave your PIN for that task;
- send an email. It writes a draft and opens it in Mail; you press Send;
- read your clipboard when a password manager marked what you copied as
  private;
- use any ability whose skill is off, or whose permission macOS has not
  given. The Mac checks the skill itself, so not even a server that asks
  can use one that is off.

What Ira reads goes to your own Ira server, marked as data that can never
give Ira orders, and is kept only in that conversation (see
[Privacy](../privacy.md)).

**What I read** (the list button at the top of the window, and the
menu-bar menu) shows the last things Ira used on this Mac: what it did and
on which file or window, never what was in them. The app's own log, in
`~/Library/Logs/Ira/`, holds only tool names, timings and outcomes.

## Coding tasks (optional)

Ira can hand a coding job to a coding agent on this Mac, for example "open
the shop repository in VS Code and add a test for the invoice total". Ira
makes a **new git worktree** of the repository on its own branch
(`ira/task-...`), opens VS Code on it so you can watch the changes as they
happen, runs the agent there, then tells you which files changed and whether
the tests passed.

It is off until you set it up, in
`~/Library/Application Support/Ira/tasks.json` on this Mac (never in a
repository, never on the server):

```json
{
  "command": ["/path/to/agent", "-p", "{prompt}", "--output-format", "stream-json"],
  "repos": {
    "shop": {"path": "~/code/shop", "test": "pytest -q"},
    "site": {"path": "~/code/site", "protected": true}
  },
  "worktrees": "~/ira-tasks",
  "minutes": 60,
  "vscode": {"open": true}
}
```

- `command` is your coding agent's command line; `{prompt}` is replaced by
  the task. Its output may be plain lines or stream-json.
- `repos` are the only repositories tasks may use. `test` runs after the
  agent finishes.
- `protected: true` is for a repository that deploys when its main branch
  moves. Ira then pushes only its own `ira/task-...` branches there.
- Then choose **Settings → Reload tools** so Ira learns about the tasks.

The safety rules:

- The agent runs in macOS's sandbox: it can write only in its worktree, the
  repository's `.git` and temporary folders, and its git cannot push.
- Starting a task needs your yes. Pushing needs your PIN, and pushes only the
  task's own branch: never `main`, `master` or the repository's default
  branch, never forced, nothing merged.
- These stop accidents and a confused agent; they are not a wall against
  hostile code. Give tasks only repositories you trust.

**VS Code's assistant.** Ira opens VS Code on the worktree; it does not click
in VS Code. If your editor extension documents a link that opens it with a
request filled in (some do: a `vscode://...` link with a `prompt`), put that
link in `tasks.json` as `"vscode": {"promptURI": "vscode://.../open?prompt={prompt}"}`,
and `file_open` with `app: vscode` and a prompt fills the request in for you. Such links fill
the request in but do not send it: you press Return.

## Remove Ira from this Mac

Choose **Remove Ira from this Mac…** in the menu-bar menu (or **Settings**).
Your Ira forgets this Mac at once (its key stops working), and the app
deletes its key, settings, logs and login item here, and the old companion
if it is still around; your files are not touched. Then drag Ira from
Applications to the Bin. You can also remove the Mac on **Your devices**: it
disconnects at once.

## If something does not work

| You see | Do this |
| --- | --- |
| "Not paired: that code is used, expired or mistyped" | Make a new code on **Your devices** and paste the new link |
| "use https:// for a server on another machine" | Your Ira's address must start with `https://`, unless it runs on this Mac |
| The menu says "This Mac was removed from Ira" | It was removed on **Your devices**: choose **Settings → Pair again** |
| Ira says Screen Recording is off | **System Settings → Privacy & Security → Screen & System Audio Recording**, switch Ira on, then press **Restart Ira** |
| The checklist says "Ira was rebuilt" | The Ira switched on under Screen Recording is an older build, which no longer counts. Select it, press **−**, press **+** and choose Ira in Applications, then **Reopen Ira** |
| A search says it can't search Documents, Desktop or Downloads yet | Press **Allow** on that folder's row in Ira's checklist (**Settings → Permissions**) and answer macOS with **Allow** |
| A search says macOS keeps Ira out of a folder | **System Settings → Privacy & Security → Files and Folders → Ira**, switch on that folder (for example "Documents Folder") |
| Ira says macOS needs it restarted | Screen Recording was switched on while Ira ran: press **Restart Ira** in its window |
| "No answer yet. The server is slow or unreachable." | Check that this Mac is online and your Ira is running, then press **Try again** |
| Ira says macOS did not let it open a file | **System Settings → Privacy & Security → Files and Folders**, switch on Ira's folders |
| Option-Space does nothing | Another app took it: choose a new shortcut in **Settings → Shortcut** |
| Ira says it may not use Mail, Notes or Messages | **System Settings → Privacy & Security → Automation**, switch on Ira's apps |
| Ira says Contacts, Calendars or Reminders are off | **System Settings → Privacy & Security**, the matching page, switch Ira on |
| Ira does not offer coding tasks | Check `tasks.json` lists a `command` and at least one repository, then **Settings → Reload tools** |
| macOS asks for every permission again after an update | See the note under [Grant permissions](#grant-permissions) |

## For developers: building from source

The app is a Swift package in `clients/macos/`. It builds with the Command
Line Tools alone (`xcode-select --install`); Xcode is not needed.

```bash
cd clients/macos
swift build                  # debug build
scripts/test.sh              # the tests (Swift Testing)
scripts/make-app.sh          # dist/Ira.app, dist/Ira-<version>.zip and .dmg
UNIVERSAL=1 scripts/make-app.sh   # Apple silicon and Intel in one app
scripts/make-signing-identity.sh  # once: keep permissions between your builds
```

**Signing.** Without a paid Apple Developer account, the app is signed ad
hoc, and macOS sees each build as a new app: it asks again for every
permission, and for the Keychain item. `make-signing-identity.sh` makes a
self-signed code-signing certificate ("Ira Local Signing", ten years) in
your login keychain, once; `make-app.sh` signs with it whenever it is there,
so builds made on that Mac keep their permissions and Keychain access.
Nothing is sent anywhere. (`--remove` deletes it.)

**Notarization** is the owner's decision: a Developer ID certificate and
Apple's notary service need the Apple Developer Program ($99 a year). With
them, `make-app.sh` would sign with the Developer ID and the hardened
runtime, `xcrun notarytool submit` would send the dmg to Apple, and
`xcrun stapler staple` would attach the ticket; people could then open the
downloaded app with a double-click, and permissions would carry over between
releases. Until then, the first open is right-click, Open (or Open Anyway).

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
| `Sources/IraKit/Tools/` | `ToolCatalog` (every tool's JSON Schema, skill and tier) and `Toolbox` (calls and "What I read"); the path policy and its deny list; Spotlight; PDF, Word, RTF and text reading; ScreenCaptureKit and Vision; Contacts; EventKit; Mail, Notes and Messages through fixed AppleScripts that take the model's words only as arguments; apps, the clipboard and Shortcuts; coding tasks and the push guard |
| `Sources/IraKit/Voice/`, `Talk/` | `VoiceTransport`: live voice over `/v1/voice/live` ([Real-time voice](../realtime.md), protocol 1) with the device token, or the HTTP API with the same token (tried again on the next mic press); the energy voice detector; sentence splitting |
| `Sources/Ira/` | the app: menu bar, the global hotkey (Carbon, so no Accessibility permission), the floating window, microphone and speaker on one `AVAudioEngine` with echo cancellation |
| `Tests/IraKitTests/` | pairing against a URLProtocol stub, device and live-voice frames against a fake WebSocket, the deny list, a tiny `.docx` fixture, a PDF drawn in the test, tool schemas and deadlines, the browser scripts, the routine readings, taking over the companion, the wake phrase, and the voice detector on synthetic audio. No test opens a network connection |
| `Tests/IraAppTests/` | the window: Cmd-V pastes into the Ask field (with the pasteboard put back after), the editing keys, and letting go of the keyboard. They need a desktop session |

The tools the app offers (30 with coding tasks set up, the server's most per
device):

| Tool | Skill | Tier |
| --- | --- | --- |
| `files_find {query?, kind?, modifiedWithinDays?, folder?}`, `file_read {path, maxChars?}`, `file_open {path, app?, prompt?}` (app `vscode` opens a folder too) | `files` | 0, 0, 1 |
| `screen_read {}` | `screen` | 0 |
| `browser_tabs {browser?}`, `browser_show_tab {match?, id?, browser?}` | `browser` | 0, 1 |
| `contacts_lookup {query}` | `contacts` | 0 |
| `calendar_read {from?, days?, query?, calendar?}`, `calendar_add {title, start, end?, durationMinutes?, allDay?, location?, notes?, calendar?}` | `calendar` | 0, 2 |
| `reminders_list {list?, includeDone?, query?}`, `reminders_set {title?, due?, list?, notes?, done?, id?}` (adds one, or with `done` marks one done) | `reminders` | 0, 1 |
| `mail_search {query?, days?, limit?, id?, maxChars?}` (with `id`, reads that email), `mail_draft {to, cc?, subject?, body?}` | `mail` | 0, 2 |
| `messages_send {to, name?, text}` | `messages` | 2 |
| `notes_search {query?, limit?, id?, maxChars?}` (with `id`, reads that note), `notes_add {title, body?, folder?}` | `notes` | 0, 1 |
| `app_open {name}`, `url_open {url}` | `apps` | 1, 2 |
| `clipboard_read {}` | `clipboard` | 0 |
| `shortcuts_list {}`, `shortcuts_run {name, input?}` | `shortcuts` | 0, 2 |
| `mac_type {text, pressReturn?}`, `mac_keys {keys}`, `mac_click {label, role?, index?}`, `mac_scroll {direction, amount?}`, `mac_menu {path}`, each also `{app?, task?}` | `control` | 3 |
| `code_task_start {repo, instruction, openInVSCode?}`, `code_task_status {id?}` (without `id`, lists them), `code_task_stop {id}`, `code_task_push {id}` | `tasks` | 2, 0, 1, 3 |

The coding-task tools are in the hello only when `tasks.json` is set up.
A long task says how it is going with `task_progress` (after 5 minutes, then
every 10), and ends with `task_done` or `task_failed`. Each tool has a
deadline under the server's 25 seconds (15 for `screen_read`, 20 for the
control tools, 22 for the scripted apps, 10 for most), and every call is logged with its tool, time
and outcome. The routine skill sends `observe` frames, not tool calls.

There are no third-party dependencies: everything comes with macOS.
