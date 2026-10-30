# Ira on iPhone

An iPhone gets Ira three ways:

1. **Ira for iPhone**, the native app: type or talk, a live call with
   barge-in, "Hey Siri, Ask Ira" with nothing to build, and your contacts,
   calendar, reminders, location and calls as tools Ira may use when you
   ask. It is not in the App Store yet: the owner installs it through
   TestFlight ([below](#the-native-app-testflight)), or builds it with
   Xcode.
2. **The Ira web app on your Home Screen**: everything the web app does,
   with nothing to install from a store.
3. **"Hey Siri, Ask Ira" as a Shortcut** you build, for an iPhone without
   the app.

## Ira for iPhone

You need iOS 17 or later, and your own Ira at an `https://` address.

### Pair it

1. In the Ira web app, open the menu, **Your devices**. Under **Add a
   device** choose **iPhone (Ira for iPhone)**, give it a name, tick what it
   may do (Contacts, Calendar, Reminders, Location, Calls), type your PIN
   and press **Make a pairing code**.
2. On the iPhone, either:
    - scan the QR code with the **Camera**, open the page, and tap **Open in
      Ira for iPhone**; or
    - in Ira, on **Get Ira ready**, tap **Pair**, then paste the pairing
      link (**Paste** asks nothing), or type the code (`ABCD-EFGH`) and your
      Ira's address.

The code works once, within 10 minutes. The iPhone gets its own key, which
stays in its Keychain: readable only on this iPhone, after it has been
unlocked once since it started, never synced through iCloud and never in a
backup restored to another phone. If iOS will not hand the key over (the
iPhone restarted and is still locked), Ira says so and waits; it never
forgets the pairing on its own.

### Get Ira ready

The first time, Ira shows a checklist. Each line says why in one sentence
and has the button that does it: **Pair**, **Allow** (iOS's own question),
or **Open Settings** when iOS will not ask again (after a "Don't Allow").
Only **Pair** and **Microphone** are needed to talk; the rest are for the
skills you want. **Settings → Get Ira ready** shows it again later.

| Line | Why | When iOS asks |
| --- | --- | --- |
| **Pair with your Ira** | So this iPhone knows which Ira is yours. | (no iOS question) |
| **Microphone** | So you can talk to Ira. It listens only during a call you start. | **Allow**, or your first call |
| **Speech recognition** | So the iPhone can turn your words into text when your Ira has no live calls. | **Allow**, or the first call in phone mode |
| **Contacts** | So Ira can put a name to a number, or find the number to call. | **Allow**, or the first lookup while Ira is open |
| **Calendar** | So Ira can tell you what is on your day, and add an event after your yes. Needs **Full Access**. | **Allow**, or the first calendar question |
| **Reminders** | So Ira can list your reminders, add one, and tick one off. Needs **Full Access**. | **Allow**, or the first reminder |
| **Location** | So Ira can say where you are, when you ask. **While Using the App** only. | **Allow**, or the first "where am I?" |
| **Calls** | So Ira can start a call after your yes. iOS still asks you to tap **Call**. | (no iOS question) |

A skill also has to be switched on for this iPhone on **Your devices**, with
your PIN, as for any device. You can switch it off there at any time, without
a PIN.

### Talk to Ira

- **Type** in the box and press Send. Answers stream in as they are
  written. A conversation goes on until you tap **New conversation**; calls
  and Siri add to the same one, so "usko call karo" knows who "usko" is.
- **Tap the phone button** to start a call; tap it again to end it.
    - **Live call**, when your Ira has live voice (`GET /v1/info` says
      `live`): just talk. The iPhone hears when you start and stop, and
      sends your voice to your Ira only while you speak, from a moment
      before you started until you stop (protocol 1 of [real-time
      voice](../realtime.md)). Ira answers aloud, sentence by sentence,
      from the speaker unless headphones are in. **Speak over Ira** and she
      stops at once; or tap **Stop**. The iPhone's echo cancellation keeps
      her own voice from interrupting her.
    - **Phone mode**, when your Ira has no live voice: the iPhone's own
      speech recognition (in Hindi, then Indian English, or your own
      language first if your Ira says you speak English only) turns each
      turn into text, which goes to your Ira like typing. Ira answers in
      her own voice if your Ira has one, else in the iPhone's (Hindi or
      Indian English). Ira listens again when she has finished; speaking
      over her does not stop her, so tap **Stop**.
    - The line under the call says which mode is on, and why.
    - The screen stays on during a call. Locking the iPhone keeps the call
      going; another call, Siri or an alarm ends it. Two quiet minutes end
      it too.
- **Typing during a call** goes into the call.
- **Hindi, English and Hinglish** all work.
- **A yes**: when Ira proposes something that acts for you (a call, an
  event), she reads it back with its exact target, and a card shows it with
  **Yes** and **No**; in a live call you can also say "haan" or "nahi".
  Anything that needs your PIN shows a PIN box: type it there and press
  **Confirm**. It goes only to your Ira's confirm step, never into the
  conversation, and is never kept. Never say a PIN aloud.
- **While Ira works**, a line names the step ("Checking your calendar…")
  with the seconds after three; after 30 seconds it says your Ira is slow or
  unreachable. Every problem shows in plain words with what to do next.
- **Report an answer** that is wrong, harmful, offensive or shows something
  private: tap **⋯** beside it (or touch and hold it), **Report this
  answer…**, pick a reason, add a note if you like, and **Send**. The report
  goes to the person who runs your Ira, with that answer; nothing else.

### "Hey Siri, Ask Ira"

The app brings three Siri phrases with it, with nothing to build. They use
this iPhone's own key, so they are the same Ira, in the same conversation:

| Say | What happens |
| --- | --- |
| **"Hey Siri, Ask Ira"** | Siri asks what you want to ask, sends it to your Ira and says the answer. |
| **"Hey Siri, Tell Ira"** | For things you tell Ira ("Rahul is my CA", "remind me at 6 to call the bank"); Ira says what it saved. |
| **"Hey Siri, Talk to Ira"** | Opens Ira and starts a call. |

They also appear in the **Shortcuts** app and in Spotlight. When Ira
proposes something that needs your yes, Siri reads it back and asks; say
"yes" or "no". Something that needs your PIN cannot be done through Siri:
open Ira and type it there, within two minutes. Through Siri, Ira can use the
iPhone's own tools only while the app is open on the iPhone (see below).

### Drop: send anything to your other devices

**Drop** (the tray at the top) lists what you sent from any of your devices,
newest first: text and links with **Copy** first (and **Open** for a link),
files with **Get**, then **Save or open** through the share sheet. Type or
**Paste** and **Send**, or pick **Files**. Swipe left to delete an item from
every device. While Ira is open, something new from another device comes as
a notification with **Copy**. See [Privacy](../privacy.md#drop).

### What Ira can do on your iPhone

Each tool belongs to a skill you switch on for this iPhone, and each has a
tier, set by the app and never by the model: reading needs nothing more
(Tier 0); adding something small, Ira does and tells you (Tier 1); anything
that changes your calendar or reaches another person, Ira reads back exactly
and waits for your yes (Tier 2).

| Tool | Skill | Tier | What it does |
| --- | --- | --- | --- |
| `contacts_lookup` | contacts | 0 | people by name, number or email, with their numbers (with iOS 18's limited access, only the contacts you shared with Ira) |
| `calendar_read` | calendar | 0 | events in the calendars on the iPhone (iCloud, Google, Exchange) |
| `calendar_add` | calendar | 2 | adds an event, read back first |
| `reminders_list` | reminders | 0 | your Apple Reminders, open ones first |
| `reminders_add` | reminders | 1 | adds a reminder; with a time, the iPhone alerts then, even with Ira closed |
| `reminders_done` | reminders | 1 | marks one done |
| `location_now` | location | 0 | where the iPhone is, once, while Ira is open |
| `call_place` | calls | 2 | after your yes, opens the iPhone's own **Call** prompt for that number; you tap **Call** |

### What iOS does not allow

These are Apple's rules for every app, not choices Ira made:

- **No call log, no SMS, no other apps' notifications.** iOS lets no app
  read them, so Ira for iPhone has no such skills. (The Android app has.)
- **No call without your tap.** An app can only open the iPhone's "Call
  …?" prompt, and only while it is on screen. `call_place` digits only: no
  `*` or `#` codes.
- **No sending a message for you.** iOS shows a message for you to send
  yourself; Ira for iPhone does not offer it yet.
- **The iPhone's tools work while Ira is open, or during a call.** iOS
  suspends an app soon after it leaves the screen, which closes its
  connection to your Ira; the app reconnects when you open it. A call keeps
  the app running when the screen locks.
- **Location only while using the app**, never in the background.
- **No "Hey Ira" wake word.** iOS lets no app listen in the background for
  its own phrase; "Hey Siri, Ask Ira" is the iPhone's way.
- **No notifications from Ira** while the app is closed (Ira does not send
  push notifications yet). A reminder Ira adds with `reminders_add` is the
  iPhone's own and alerts on time.

### What stays on the iPhone

The key (in the Keychain), your Ira's address, this iPhone's name and the
conversation's id (in the app's settings). No audio, no transcript, no
answer, no contact, no place. What a tool reads goes only to your own Ira,
into your conversation, marked as data that can never give Ira orders. In
phone mode the iPhone recognises speech on the iPhone when it can; otherwise
iOS sends the audio to Apple to recognise, as dictation does. The app's log
(the system log, subsystem `io.github.helloupendra.ira`) holds tool names and
outcomes, never what was said or read. **Settings → What Ira used on this
iPhone** lists the last 50 tool calls since the app opened, without contents.

### Remove Ira from this iPhone

**Settings → Remove this iPhone from Ira**: your Ira forgets the iPhone at
once (its key stops working), and the app forgets the key and your Ira's
address. Or remove it on **Your devices**, from anywhere. Then delete the
app as usual.

### If something does not work

| You see | Do this |
| --- | --- |
| "That code is used, expired or mistyped" | Make a new code on **Your devices** and pair again |
| "Use your Ira's https:// address" | Your Ira's address must start with `https://` |
| "Your Ira no longer knows this iPhone" | It was removed on **Your devices**: **Settings → Get Ira ready → Pair** |
| "Ira can't read its key yet" | Unlock the iPhone, then open Ira again; you do not need to pair again |
| "This iPhone's tools are offline" | The iPhone is offline or your Ira is down; typing waits for it too |
| "Ira cannot hear you: the microphone is off" | **Settings → Ira → Microphone** on the iPhone |
| Phone mode, though your Ira should have live calls | Your Ira needs `voice.stt.type: transcribe` and a voice ([Real-time voice](../realtime.md)) |
| "The iPhone cannot recognise Hindi or English speech" | Check the iPhone is online, or add the language under **Settings → General → Keyboard → Dictation Languages**; or type |
| A tool says it is off for Ira | Open Ira's checklist and press **Allow**, or **Open Settings** |
| A call does not start after your yes | Keep Ira on screen: iOS shows the Call prompt only for the app in front |

## The native app: TestFlight

TestFlight is how the owner installs Ira for iPhone before it is in the App
Store, and how they invite family or staff. It needs a paid Apple Developer
Program membership. The facts below were read on Apple's own pages on
**23 October 2026**; Apple changes them, so check the linked pages before you
start.

### (a) Enroll in the Apple Developer Program as an individual

- **The fee**: "The Apple Developer Program is 99 USD per membership year
  … Prices may vary by region and are listed in local currency during the
  enrollment process" ([Enroll](https://developer.apple.com/programs/enroll/)).
  Apple's pages give no rupee price: the Apple Developer app shows it, in
  rupees, before you subscribe.
- **In India, only in the app**: "Enrollment in India is only available
  through the Apple Developer app"
  ([Purchase and activation](https://developer.apple.com/support/purchase-activation/)).
  Apple Account balance (from Apple Gift Cards) is accepted from developers
  based in India
  ([Enrolling with the Apple Developer app](https://developer.apple.com/support/app-account/)).
- **You need**: an Apple Account with two-factor authentication, in your
  legal name ("Using an alias, nickname, or company name … will cause a
  delay"); to be of age in your region; an iPhone with Face ID, Touch ID or
  a passcode, signed in to iCloud, used for the whole enrollment; and a
  government photo ID (passports in most regions).
- **Steps** (the Apple Developer app, from the App Store): **Account** tab →
  sign in → **Enroll Now** → **Continue** → enter your legal name and phone →
  photograph your ID → **Individual** as the entity type → agree to the
  license → **Subscribe**. Your legal name becomes the app's seller name on
  the App Store.
- It is a yearly subscription that renews until you cancel it; a
  confirmation email follows the purchase (write to Apple if none comes
  within 24 hours).

### (b) Make the App ID and the app

1. **The App ID**: in [Certificates, Identifiers &
   Profiles](https://developer.apple.com/account/resources) → **Identifiers**
   → **+** → **App IDs** → **Continue** → (the type, App, is selected) →
   **Continue**; a description (Ira for iPhone), **Explicit**, Bundle ID
   **`io.github.helloupendra.ira`** (the one in `clients/ios/project.yml`);
   tick no capabilities (the app uses none); **Continue** → **Register**
   ([Register an App ID](https://developer.apple.com/help/account/identifiers/register-an-app-id/)).
   With automatic signing, Xcode can also make it for you.
2. **The app in App Store Connect**: the Account Holder first signs the
   latest agreement under **Business**. Then [App Store
   Connect](https://appstoreconnect.apple.com) → **Apps** → **+** → **New
   App** → platform **iOS**, name (**Ira**, or another if it is taken), a
   primary language, bundle ID
   `io.github.helloupendra.ira`, a SKU of your choice (`ira-ios`), **Full
   Access** → **Create**
   ([Add a new app](https://developer.apple.com/help/app-store-connect/create-an-app-record/add-a-new-app)).

### (c) Sign and upload: on your Mac (recommended), or from CI

Apple accepts iOS builds made with **Xcode 26 or later**
([Upload builds](https://developer.apple.com/help/app-store-connect/manage-builds/upload-builds)).
CI builds this app for the simulator only and holds no Apple key; there are
two ways to sign one for TestFlight:

- **On your Mac (recommended).** Install Xcode from the Mac App Store, sign
  in under **Xcode → Settings → Accounts**, then:

    ```bash
    brew install xcodegen
    cd clients/ios && xcodegen generate && open Ira.xcodeproj
    ```

    In the **Ira** target, **Signing & Capabilities**: tick **Automatically
    manage signing** and choose your team. Xcode then uses Apple's
    cloud-managed signing certificates
    ([Distributing your app](https://developer.apple.com/documentation/xcode/distributing-your-app-for-beta-testing-and-releases)).
    No key or certificate ever leaves your Mac or reaches GitHub.

- **From CI, with an App Store Connect API key.** An Account Holder or Admin
  makes a team key under **Users and Access → Integrations → App Store
  Connect API → Team Keys → Generate API Key**, with the least role that
  may upload builds (Developer); its private key "can only be downloaded once"
  ([App Store Connect API](https://developer.apple.com/help/app-store-connect/get-started/app-store-connect-api),
  [Creating API keys](https://developer.apple.com/documentation/appstoreconnectapi/creating-api-keys-for-app-store-connect-api)).
  The key, its ID and the issuer ID would then be GitHub secrets, and a
  workflow would archive with them and upload. This repository does not do
  it: a key that uploads builds for the whole account would sit in GitHub,
  and the person who holds the account should keep it. Use it only if you
  must, with a key you revoke when you stop.

### (d) Archive, upload, test

1. In Xcode, choose the **Ira** scheme and **Any iOS Device (arm64)**, then
   **Product → Archive**. The Organizer opens with the archive.
2. **Distribute App** → **TestFlight Internal Only** ("restricts access to
   your team", so this build can never be sent for App Store review by
   mistake) → **Distribute**. Xcode signs, uploads, and links to the build
   in App Store Connect. The first build creates the beta; Apple emails when
   processing is done.
3. In App Store Connect: the app → **TestFlight** → **+** next to **Internal
   Testing** → a group (Family) → **Invite Testers**: up to 100 people with
   access to your App Store Connect team, you included → **Add Builds**
   ([Add internal testers](https://developer.apple.com/help/app-store-connect/test-a-beta-version/add-internal-testers)).
   The app's `Info.plist` says it uses no encryption of its own
   (`ITSAppUsesNonExemptEncryption` is false: it uses only iOS's HTTPS), which
   Apple asks for "so that you don't need to answer encryption questions with
   each app submission" ([Export
   compliance](https://developer.apple.com/help/app-store-connect/manage-app-information/overview-of-export-compliance)).
   If App Store Connect still asks for a build, answer that it uses no
   encryption beyond what iOS provides.
4. On the iPhone: install **TestFlight** from the App Store, open the
   invitation email, tap **View in TestFlight**, then **Accept** and
   **Install**. "Each build is available to test for up to 90 days"; TestFlight
   needs iOS 16 or later ([TestFlight](https://testflight.apple.com/)), and
   Ira for iPhone iOS 17.
5. For people outside your team (up to 10,000 external testers), a build
   goes to Beta App Review first ([Overview of
   TestFlight](https://developer.apple.com/help/app-store-connect/test-a-beta-version/overview-of-testflight)).
   App Review will need a pairing code that lasts: see [A code for app
   reviewers](../devices.md#a-code-for-app-reviewers) (`ira device code
   --kind ios`).

For each new build, raise `CURRENT_PROJECT_VERSION` in `project.yml` (or let
Xcode's **Manage version and build number** do it) and archive again.

### (e) Without paying: your own iPhone, for 7 days

With a free Apple Account, Xcode signs as a **Personal Team** and installs on
your own iPhone over a cable or Wi-Fi: "You can install up to 3 apps per
device. Provisioning profiles that enable apps to be installed on a device
will expire 7 days from issuance. You'll need to rebuild and reinstall your
app to your device after expiration"; up to 10 App IDs and 3 devices, each
expiring after 7 days ([Choosing a
membership](https://developer.apple.com/support/compare-memberships/)).

1. Install Xcode, sign in with your Apple Account (**Xcode → Settings →
   Accounts**), generate the project as in (c), and choose your **(Personal
   Team)** in **Signing & Capabilities**. If Xcode says the bundle id is
   taken, change `PRODUCT_BUNDLE_IDENTIFIER` in `project.yml` to one of your
   own and generate again.
2. Connect the iPhone, choose it as the run destination, and press **Run**.
3. On the iPhone, turn on **Settings → Privacy & Security → Developer Mode**
   and restart when asked
   ([Enabling Developer Mode](https://developer.apple.com/documentation/xcode/enabling-developer-mode-on-a-device)).
4. Every 7 days, run it from Xcode again. No TestFlight, no one else's iPhone.

## The Ira web app on your Home Screen

1. Open your Ira's address in **Safari** (it must be `https://`), and sign
   in.
2. Tap **Share**, then **Add to Home Screen**, then **Add**.
3. Open **Ira** from the Home Screen. The first time you talk, allow the
   microphone.

- **The call button** starts a live call: just talk, Ira answers aloud a
  moment after you stop, and stops when you speak over her. The screen
  stays on during a call.
- **The silent switch** does not mute Ira during a call (Safari 17 or
  later). Outside a call, spoken answers play like any media.
- **Typing** always works, in a call too: what you type goes into the call.
- **Lock the phone or leave the app, and the call ends.** iOS lets no web
  app use the microphone in the background.
- Safari may ask for the microphone again after the app has been closed for
  a while. That is iOS, not Ira.

## "Hey Siri, Ask Ira" with a Shortcut

For an iPhone without Ira for iPhone. The Shortcut takes your words with the
iPhone's own dictation, sends them to your Ira, and reads the answer aloud.
It uses a token that can only **ask**: it cannot say yes to an action, pair
a device or open the console. When Ira proposes something that needs your
yes, the Shortcut says so, and you confirm it in the Ira app.

### 1. Make the token

In the Ira app's menu, **Siri on iPhone**: type your PIN and tap **Make a
token**. Copy it; it is shown once. The same page lists your tokens, with
**Stop it** for a lost phone. (Owners and admins can also make one in the
console, **Tokens & security**, with the scope `ask` and nothing else.)

### 2. Build the Shortcut

In the **Shortcuts** app, tap **+**, name it **Ask Ira**, and add these
actions in this order:

| # | Action | Set it to |
| --- | --- | --- |
| 1 | **Dictate Text** | Language: **English (India)**, or **Hindi (India)** for Hindi and Hinglish. Stop Listening: **After Pause** |
| 2 | **Get Contents of URL** | URL: `https://<your Ira>/v1/ask`. Tap **Show More**. Method: **POST**. Headers: add `Authorization` = `Bearer <your token>` (the word Bearer, a space, then the token). Request Body: **JSON**, add a **Text** field `text` = the **Dictated Text** variable |
| 3 | **Get Dictionary Value** | Get **Value** for `text` in **Contents of URL** |
| 4 | **Speak Text** | **Dictionary Value**. Optional: Language **English (India)** or **Hindi (India)**, and a voice |

Then say **"Hey Siri, Ask Ira"**, wait for the listening sound, and talk:

> kal ka schedule kya hai?
>
> Sunrise ka invoice bhej diya tha?

Each run starts a new conversation, but Ira still knows your people, your
businesses and what you asked it to remember.

### "Tell Ira": notes and reminders

A second Shortcut for things you tell Ira rather than ask, which shows a
short note instead of talking back. Make it like **Ask Ira**, but:

- name it **Tell Ira**;
- replace step 4 with **Show Notification**: the **Dictionary Value**.

> Tell Ira: Rahul is my CA
>
> Tell Ira: Sunrise pays in 30 days
>
> Tell Ira: remind me at 6 to call the bank

Ira remembers people and businesses at once, and says what it saved. A
reminder goes off in the Ira app while it is open, on your Mac or Android
phone if one is paired, and in Telegram if you linked it.

### If the Shortcut fails

- **"invalid or revoked token"**: the token was stopped, or copied wrong.
  Make a new one.
- **An error page instead of an answer**: check the URL ends in `/v1/ask`
  and starts with `https://`.
- **It hears the wrong language**: set Dictate Text's language; Hindi
  (India) also understands Hinglish best.

## iPhone and Android, compared

| | Ira for iPhone | iPhone web app and Shortcut | [Android app](android.md) |
| --- | --- | --- | --- |
| Talk, type, live call, barge-in | yes | yes, while the app is open | yes |
| A call with the screen locked | yes | no | yes |
| Siri / assistant button | "Hey Siri, Ask Ira", "Tell Ira", "Talk to Ira" | a Shortcut you build | long-press the power button |
| Background wake word | no: iOS allows none | no | not yet |
| Your contacts, calendar, reminders, location | yes, while Ira is open | no (Ira reads a calendar through [Google](../connectors.md#google-gmail-and-calendar-read-only)) | yes |
| Call for you | the iPhone's Call prompt, after your yes; you tap Call | no | yes, after your yes |
| Read your calls, SMS, notifications | **no**: iOS lets no app read them | no | yes, with each skill switched on |
| Alarms, timers | reminders that alert on time; alarms through Siri | through Siri | yes |
| Drop | yes: the inbox, send text and files, Copy | yes, in the web app | yes, with Share → Ira Drop and a clipboard tile |

## What was tested where

**Ira for iPhone** was built and tested in CI on an iOS simulator (the
`ios-app` job), against a local Ira with the demo model and fake speech: its
95 unit tests (protocols, the voice detector, pairing, the Keychain rules,
the tools and their tiers), and a check that pairs as kind `ios`, offers the
iPhone's tools, answers a real tool call, says yes to a Tier 2 proposal and
holds a live call (a typed turn, a spoken one, a barge-in, a report). The UI
tests run the checklist, a bad code, pairing with a link, a typed question,
and a tool call answered from the simulator's contacts. These need a real
iPhone to confirm: the microphone, echo cancellation and barge-in with a
real voice; the speaker by default and the earpiece, AirPods and CarPlay;
the iPhone's speech recognition in Hindi and on the device; a call going on
with the screen locked; the Call prompt; location; Siri running "Ask Ira"
and asking yes or no; and the TestFlight install itself.

**The web app** was tested in WebKit (Safari's engine) as an iPhone 15:
install tags and icon, the tap that unlocks sound, typing, a live call with
a mock microphone (audio up, Ira's MP3 sentences decoded and played back),
the screen lock, the audio session, Report, and the Siri token page. These
need a real iPhone to confirm: the silent switch, whether a call's sound
comes from the speaker or the earpiece, the microphone prompt in a Home
Screen app, and Siri running the Shortcut.
