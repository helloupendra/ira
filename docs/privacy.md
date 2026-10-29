# Privacy

Ira is software you run yourself. Your conversations, your devices and what
they read stay on the computer or server that runs it, and you decide which
outside services, if any, it talks to. This page says, in plain words, what
Ira keeps, who can see it, and how to take it away.

## Delete your data

Ira, by Upendra Singh Chauhan. To delete what Ira keeps about you:

1. Open the Ira web app on your Ira server and sign in.
2. Open the menu, choose **Your data**, then **Delete my data**, and type
   your password. In the Android app, **Settings → Export or delete your
   data** opens this page.
3. To stop a single phone or Mac at once, open **Your devices** and choose
   **Remove** on it. Its key stops working immediately.
4. If you can no longer sign in, ask your Ira server's owner, or open an
   issue marked *privacy* on the project's GitHub page.

**Deleted at once:** your conversations and their messages, your devices,
their pairing codes and their events, **What Ira did**, your settings, what
Ira noticed and learned about you, your reminders, the people you told Ira
about, your reported answers, your business profiles, your connections
to other services with their tokens, the actions Ira proposed on your
devices or through your connections, with their entries in the audit log,
and your approvals: open approval windows, fingerprint approval keys and
trusted apps. (The audit log never held what those actions said: only the
tool and its outcome.)

**Kept:** your account (email and password) until the server's owner
removes it; personal access keys you made (for example **Siri on iPhone**),
which keep working until you stop them there or under **Tokens and
security**; the server's security log of account changes; and, on a
business's server, the actions you asked its tools to take, which are that
business's records. Copies in the server owner's own backups last as long
as that owner keeps backups. Ira sends nothing to its developer.

## What Ira keeps

| What | Where | For how long |
| --- | --- | --- |
| Your conversations, including what tools and devices returned | the server's database | until you delete them |
| Your devices: name, kind, the tools they offer, the skills you switched on, when they were last seen | the server's database | until you remove the device |
| Your devices' events ("the upload finished") | the server's database | 7 days, at most 200 |
| **What Ira did**: which tool, which device, when, how long, and whether it worked | the server's database | until you delete your data (or fewer days, if the server's owner set `retention.tool_log_days`) |
| Each call to a language model: when, which model, its tokens and cost, never what was said | the server's database, seen by its owners and admins | until the server's owner sets days (`retention.calls_days`) |
| A live call's timings (how long until you heard Ira), never its words | the server's database | 30 days (`retention.voice_days`) |
| Your sign-ins (sessions): when, and the browser's name | the server's database | until 30 days after they end |
| Your settings: the assistant's name, wake phrase, languages, web search on or off | the server's database | until you change or delete them |
| A device's own key | the Mac's Keychain (later, the phone's Keystore) | until you remove the device |
| If you switched learning on: what Ira noticed (left, reached, locked..., the time, a place name you gave, the device), and your thumbs on answers | the server's database | as long as you chose: 30 to 365 days (90 by default) |
| Routines you said yes to, and your reminders | the server's database | until you forget them, they go off, or you delete your data |
| Drop: the text, links and files you send to your own devices | the server's data folder; files encrypted at rest with the server's key | 30 days, or until you delete them or your data |
| Your business profiles: what each is, its people, terms, what Ira may do | the server's database | until you remove them or delete your data |
| Answers you reported: why, your note, and which answer | the server's database, seen by its owners and admins | until you delete your data |

Ira never keeps:

- **what your Mac read outside your conversation.** What a file, a window or
  a tab said is part of the answer you asked for, and nothing else;
- **the contents of "What Ira did"**: not what was asked of a tool, not what
  it returned;
- **pictures of your screen**: Ira for Mac reads the window's words on the
  Mac and sends only the words; it never reads a page's contents through
  the browser, form fields or passwords, nor password managers' windows;
- **your password, PIN or keys in readable form**: only salted hashes or
  one-way fingerprints;
- **your IP address** with your account, sessions or logs.

Ira for Mac's own log (`~/Library/Logs/Ira`) holds tool names, timings and
outcomes, never what it read or heard, never a full address and never its
key.

## Who can see what

- **You** see your own conversations, devices, events, settings and "What
  Ira did".
- **An owner or admin** of a shared server manages accounts. They can see
  that your devices exist and which skills are on, switch a skill off,
  revoke a device, and read conversations for support. They **cannot** see
  what your devices returned: in your conversations, that text shows as
  "private". They cannot see your settings or "What Ira did", and they can
  never switch a skill on for you.
- **Nobody else.** Ira has no telemetry and sends nothing to its authors.

## What leaves your server, and only if you set it up

Ira talks to an outside service only when its owner configures one, and
each person switches web search on for themselves.

| Service | What it receives | Their terms |
| --- | --- | --- |
| A language model (OpenAI, Anthropic, Amazon Bedrock, or one you run yourself) | each conversation turn, with tool results | [OpenAI: business data](https://openai.com/business-data/) (API data is not used for training by default); [Anthropic: commercial terms](https://www.anthropic.com/legal/commercial-terms) (no training on customer content); [Amazon Bedrock: data protection](https://docs.aws.amazon.com/bedrock/latest/userguide/data-protection.html) (prompts are not stored, used for training or shared with model providers) |
| Speech-to-text and text-to-speech (Amazon Transcribe, Polly, Bedrock, OpenAI) | your voice clips, and the text Ira speaks | as above, and the [AWS data privacy FAQ](https://aws.amazon.com/compliance/data-privacy-faq/). Amazon Transcribe and Polly may keep and use what they process to improve their services unless the server's AWS account opts out with an [AI services opt-out policy](https://docs.aws.amazon.com/accounts/latest/reference/opt-out-ai-data-use.html) |
| Your browser's speech recognition (the Ira app's mic when the server has no speech-to-text, or always if the owner set `voice.browser_stt: prefer`) | your voice, sent by the browser itself to its maker; Ira's server receives only the text | Chrome sends the audio to Google ([Chrome's guide to the Web Speech API](https://developer.chrome.com/blog/voice-driven-web-apps-introduction-to-the-web-speech-api)); Safari to Apple ([Siri and Dictation privacy](https://www.apple.com/legal/privacy/data/en/ask-siri-dictation/)). The owner can switch it off: `voice.browser_stt: off` |
| A service you connected (GitHub, any MCP server) | what Ira asks of it for you (a repository's name, an issue's title) and your token | that service's own terms |
| YouTube Data API (`video_find`, if you switched search on and the owner set a key) | your words for the video | [Google privacy policy](https://policies.google.com/privacy) |
| Brave Search (web search, if you switched it on) | your search words only | [Brave Search API privacy notice](https://api-dashboard.search.brave.com/privacy-policy) (queries kept up to 90 days for billing, not linked to a person) |
| News feeds listed by the owner | nothing about you: Ira fetches the feeds and searches them on the server | the feeds' own sites |
| Telegram, if you paired a chat | the messages of that chat, your device's event notes, and new Drop items unless you switched that off | [Telegram privacy policy](https://telegram.org/privacy) |

With the demo provider and no keys, nothing leaves your computer at all.
The providers above were chosen because their business terms say they do
not train on what you send. Check their pages yourself: terms change.

## What you control

- **Grants.** Ira uses a device's skill, or web search, only after you switch
  it on with your PIN. **Your assistant** lists everything you allowed, each
  with **Turn off**.
- **Reading is on request.** Ira for Mac reads a file, a window, your tabs
  or your clipboard only when you ask; nothing runs in the background except
  "Hey Ira", if you switch it on, which listens on the Mac itself.
- **Actions need you.** Anything that sends, spends or deletes waits for your
  "yes" or your PIN. A page, an email or a device's output can never start
  one on its own.
- **Remove a device** on **Your devices**: its key stops working at once.
- **Export my data** (**Your data** in the menu): a file with your
  conversations, devices, events, settings and "What Ira did".
- **Delete my data**: removes your conversations, devices, events, "What Ira
  did" and settings, after your password. Your account remains, and so do
  the records a business keeps (the actions you asked its tools to take, and
  its audit log); the owner can remove the account.

## Drop

Drop is your own inbox, shared by your own devices: what you send from one
(text, a link, a file) is on the others. It is kept on your Ira server for
30 days, or until you delete it; a file is encrypted there with the
server's own key. That protects a stolen disk or backup, not the server
itself: whoever runs the server can read it, so this is **not end-to-end
encryption**. Nobody but you sees your items in Ira, not even its owner or
admins; logs keep only an item's number, kind and size, never its words
or file name. **Delete my data** removes every item and file. A file is
limited to 95 MB, and the key a Siri Shortcut uses cannot read your Drop.
Ira for Mac saves a file that arrives from another device to
`~/Downloads/Ira` at once; the Android app saves one only when you tap
**Save**.
When you share to the installed app on Android, the phone's browser keeps
the shared text and files only until the app opens; it shows them, and
sends them to your Drop only when you tap **Send to Drop**. If you paired a Telegram chat, what you send from your
other devices is also sent there, through Telegram's servers; switch that
off in the app's Drop, or with `PATCH /v1/me/drop/settings`.

## The Ira app for Android

The Android app is a window onto your own Ira server. It sends that server,
and nothing else:

- **your voice, only during a call** that you started: the audio of what you
  say, while you speak, streamed to your server and from there to its
  speech-to-text (Amazon Transcribe on most servers: see
  [what leaves your server](#what-leaves-your-server-and-only-if-you-set-it-up)).
  There is no wake word yet; the microphone never starts on its own;
- **in phone mode** (when your server has no live voice), the mic uses the
  phone's own speech recognizer instead: on the phone first, else online
  (Google's, on most phones). Your audio goes to it, never to your Ira
  server, which receives only the text;
- **what a phone tool returns, only when Ira uses it for you** and only
  with that tool's skill switched on, with your PIN: a few recent calls, a
  contact, some text messages, the notifications showing at that moment, a
  calendar event, or the phone's location once. Nothing is read in the
  background, and none of it is copied anywhere but your conversation;
- **what you type**, and your taps on Yes, No and the PIN card;
- **what you send to your Drop**: text, a link, a file you picked, shared
  to Ira (only after you tap **Send to Drop**) or copied before you tapped
  the **Send clipboard** tile. A file you save goes to Downloads/Ira on
  the phone; nothing else from Drop stays there;
- **a report, when you make one** with **Report this answer**: the
  answer's id, the reason you picked and your note, if any. The server's
  owners and admins read it.

On the phone, it keeps its own device key (encrypted, in the Android
Keystore), your server's address, which skills are on, and reminders that
have not gone off. No audio, transcript, message, contact or location stays
on the phone. Every phone tool and its permission is listed in
[the Android app](clients/android.md#what-ira-can-do-on-your-phone).

**To delete your data**: **Delete my data**, in the Ira web app's **Your
data** (the Android app's **Export or delete your data** opens it; it asks
your password), removes your conversations and what Ira did; removing the
phone under **Your devices** stops its key at once; uninstalling the app
removes everything it kept on the phone.

## On a shared server

The person who runs the server can read its database and its backups, as
with any self-hosted software. Use a server run by someone you trust, or run
your own: the [quick start](personal-assistant.md) does it in 15 minutes.

## Contact

Questions about privacy, or a problem to report: open an issue at
[github.com/helloupendra/ira/issues](https://github.com/helloupendra/ira/issues)
(mark it **privacy**; leave out anything personal, and we will ask how to
reach you privately if needed). The people who run your Ira server are the
ones who hold your data: ask them first about anything stored there.
