# Ira for Android

**Ira for Android** puts your own Ira on your phone. Tap the microphone, or
long-press the power button once Ira is your digital assistant, and talk:
Ira hears you, answers aloud a moment after you stop, and stops the moment
you speak over her. You can type too. And Ira can use what your phone can
do, for you, when you ask:

> kiska call aaya tha?
>
> 98100 00000 kiska number hai?
>
> usko call karo
>
> WhatsApp pe kya aaya hai? Rahul ko bolo main 10 minute mein pahunch raha hoon
>
> kal subah 7 baje ka alarm laga do

Ira finds the missed call in your call log, looks the number up in your
contacts ("Rahul Sharma"), and for "usko call karo" reads the call back
("Call Rahul Sharma, +91 98100 00000?") and dials on your "haan". Ira chains
the phone's tools the way it plans any task: there is no fixed list of
commands.

Ira reads nothing until you ask, and only with the skills you switch on. See
[what Ira can and cannot see](#what-ira-can-and-cannot-see).

## Two builds

| | Google Play build | Personal build |
| --- | --- | --- |
| Where it comes from | Google Play (internal testing for now), or the debug APK `ira-play-debug.apk` | the APK you install yourself: `ira-personal-debug.apk` |
| Calls, contacts, SMS, notifications, calendar, alarms, apps, media, settings | yes; call log and SMS only while Ira is your digital assistant and you are talking to Ira on the phone ([why](#the-permission-and-policy-matrix)) | yes |
| Location | approximate (about a neighbourhood) | precise |
| Use the phone like a person (read the screen, tap, type) | no: Google Play does not allow it for an assistant | yes, off until you switch it on, after a warning, and each use needs your PIN |
| App name on the phone | Ira | Ira (personal) |

Both can be installed side by side; each is paired on its own.

## Install

You need an Android phone with Android 10 or newer (a Pixel 7 is fine), and
your own Ira running somewhere: on your computer, on a server, or one your
family or team shares (see [the quick start](../personal-assistant.md)). The
phone talks to it over HTTPS, so a server on another machine needs an
`https://` address ([Deployment](../deployment.md)).

### From Google Play (internal testing)

Once the app's owner has added you as a tester, open the opt-in link they
send, tap **Become a tester**, then **Download it on Google Play**. Updates
come through Play like any app's.

### The debug APK, today

Get the APK: from the project's GitHub page, **Actions**, the latest **CI**
run on `main`, artifact **ira-android-debug** (a zip with both APKs); or
build it yourself ([below](#for-developers-building-from-source)), which
leaves it in `clients/android/build/`. Then either:

**With a USB cable (adb)**, the most reliable way:

1. On the phone: **Settings → About phone**, tap **Build number** seven
   times. Then **Settings → System → Developer options**, switch on **USB
   debugging**.
2. On your computer, install Android's `adb` (on a Mac:
   `brew install --cask android-platform-tools`), and plug the phone in.
   On the phone, allow **USB debugging** for this computer.
3. `adb devices` lists the phone. Then:

    ```bash
    adb install -r ira-personal-debug.apk    # or ira-play-debug.apk
    ```

    `adb` installs also let Android grant the SMS and call-log permissions,
    which it can hold back from an app installed from a file.

**Or by sending the file to the phone**:

1. Send `ira-personal-debug.apk` to the phone (USB file transfer, Google
   Drive, or a chat with yourself), and tap it in the **Files** app.
2. Android asks to allow installs from that app (Files, Drive or Chrome):
   **Settings → Allow from this source**, then back, and **Install**.
3. If Play Protect warns about an unknown app, choose **More details →
   Install anyway**. The debug build is signed with a development key.

Apps installed through `adb` never need developer verification. Google's
developer verification began on 30 September 2026 in Brazil, Indonesia,
Singapore and Thailand for apps from participating stores, does not cover
sideloaded apps yet, and widens to other countries in 2027
([Android developer verification](https://developer.android.com/developer-verification)).

## Pair it with your Ira

Pairing tells the phone which Ira is yours, once.

1. In the Ira app in your browser, open the menu and choose **Your devices**.
2. Under **Add a device**, choose **Android phone**, give it a name, type
   your PIN and press **Make a pairing code**.
3. Press **Copy the pairing link**, and get it to the phone (or keep the
   page open and read the 8-character code).
4. Open Ira on the phone. It shows **Pair this phone with your Ira**. Paste
   the link (**Paste** fills it from the clipboard), or type the code and
   your Ira's address (`https://ira.example.com`), and press **Pair**.

The code works once, within 10 minutes. The phone trades it for its own
device key (`irad_...`), which it keeps encrypted with a key in the Android
Keystore, never in a file or a log. It is not backed up and does not move to
a new phone: pair the new phone instead.

## The setup checklist

After pairing, the talk screen shows **Get Ira ready**: the steps left, each
with one button. Let Ira hear you (the microphone), let it show
notifications, make it your digital assistant, choose what it may do on
your Ira, and allow those skills on the phone. If you once said No to a
permission, Android stops asking; the button then reads **Open settings**
and takes you to Ira's page in Android's settings. **Hide** puts the list
away; **Settings → Show the setup checklist** brings it back.

## Switch on skills

Ira uses a phone tool only when two things are true:

1. **On your Ira**: on **Your devices**, the phone's card lists the skills it
   offers (Calls, Contacts, Messages, Notifications, Reminders, Calendar,
   Apps, Media, Location, Settings, and Screen in the personal build). Switch
   on the ones you want; each needs your PIN. You can switch any off without
   a PIN.
2. **On the phone**: in Ira, **Skills** shows each skill with what Android
   has allowed. **Allow** first explains, in plain words, what Ira reads and
   where it goes, then shows Android's own prompt. Some need a switch in
   Android's settings, which Ira opens for you:
    - **Notification access** (read and answer notifications);
    - **Alarms and reminders** (reminders exactly on time; without it
      Android may show one a few minutes late);
    - **Do Not Disturb access** (switching Do Not Disturb, or the ringer to
      silent);
    - **Accessibility**, personal build only (the screen).

If Android says **Restricted setting** when you switch on notification
access or Accessibility (it can, for an app installed from a file), open
**Settings → Apps → Ira**, tap **⋮**, choose **Allow restricted settings**,
and try again.

## Make Ira your digital assistant

**Settings → Apps → Default apps → Digital assistant app** (Ira's
**Skills** screen has a button that opens it), and choose **Ira**. Then:

- a long press of the power button (or the assistant gesture) opens Ira,
  already listening;
- Ira may start a call, an alarm or an app for you while it is in the
  background; otherwise the phone shows a notification to tap;
- in the Google Play build, the call log and SMS skills work (Google Play
  allows them only to the default assistant).

Ira does not offer speech recognition to other apps, and asks Android never
to make it the phone's default recognizer, so voice typing in other apps
keeps working as before.

## Talk to Ira

- **Tap the microphone** to start a call. The first time, Ira explains what
  the microphone is used for and asks you to agree; then Android asks for
  the microphone permission.
- **Speak** when you like. The phone notices speech itself, and sends only
  what you say (from about 0.3 s before you started) to your Ira. About 0.6
  s after you stop, Ira answers, sentence by sentence.
- **Speak over Ira** to interrupt her: she stops at once. Or tap **Stop**.
- **Type** in the box at the bottom; typing alone does not turn the
  microphone on. A typed message stays in the box until your Ira has it; if
  it cannot get there, the app says why and offers **Retry**.

**Live call, or the phone's own speech.** When your Ira has live voice
(streaming speech-to-text and a voice, `GET /v1/info` says `live`), the
microphone starts a **Live call**. When it has not, Ira says so and uses
**Talk (phone recognition)** instead: Android's own speech recognition
turns what you say into text (on the phone when the language pack is
installed, otherwise online through Google's service), the text goes to
your Ira like typing (`/v1/ask/stream`), and the answer is spoken by your
Ira's voice if it has one, else by the phone's (Android's text-to-speech,
in Hindi or Indian English). In this mode Ira listens again after she
finishes speaking; speaking over her does not stop her, so tap the button
to stop. Typed messages always go over HTTP unless a live call is on.
- **A yes**: when Ira proposes something that acts for you (a call, an SMS,
  a reply, a calendar event), she reads it back with its exact target and
  waits. Say "haan" or "yes", or tap **Yes**. Anything that needs your PIN
  (money, deleting, the screen tools) shows a card: type your action PIN
  there and press **Confirm**. A PIN is never spoken; three wrong PINs lock
  actions for 15 minutes, as everywhere in Ira.
- **Report an answer** that is wrong, harmful, offensive or shows something
  private: long-press it, or tap **⋮** beside it, pick a reason, add a note
  if you like, and **Send**. The report goes to your Ira's owner with that
  answer; nothing else is sent.
- **End** the call with the button, or the notification's **End**. Two
  quiet minutes end it too.

While a call is on, a notification **Talking with Ira** shows that the
microphone may listen. The call uses [real-time voice](../realtime.md),
protocol 1, the same as the web app and the Mac app.

## What Ira can do on your phone

| Tool | Skill | Tier | What it does |
| --- | --- | --- | --- |
| `calls_recent` | calls | 0 | recent calls: name (from contacts), number, missed or answered, when, how long |
| `contacts_lookup` | contacts | 0 | people by name or number, with their numbers |
| `call_place` | calls | 2 | starts a call to an exact number, read back first |
| `sms_read` | messages | 0 | SMS in the inbox, from someone or with some words |
| `sms_send` | messages | 2 | sends an SMS, number and words read back first |
| `notifications_read` | notifications | 0 | the notifications showing now: app, sender, text |
| `notification_reply` | notifications | 2 | answers a message through the notification's own reply button (how WhatsApp and Telegram replies work) |
| `alarm_set` | reminders | 1 | an alarm in the clock app |
| `timer_set` | reminders | 1 | a timer in the clock app |
| `reminder_set` | reminders | 1 | a reminder notification at a time |
| `calendar_read` | calendar | 0 | events in the calendars synced to the phone |
| `calendar_add` | calendar | 2 | adds an event, read back first |
| `app_open` | apps | 1 | opens an app by name or package |
| `url_open` | apps | 1 | opens a web address, in the app that handles it (a YouTube link in YouTube) |
| `maps_navigate` | apps | 1 | directions in the maps app |
| `media_control` | media | 1 | play, pause, next, previous, volume |
| `media_play` | media | 1 | plays music by name in the music app, or videos as a YouTube search |
| `location_now` | location | 0 | where the phone is, once, while Ira is on screen |
| `settings_toggle` | settings | 1 | flashlight, ringer, media volume, Do Not Disturb; Wi-Fi, Bluetooth, mobile data and NFC open their switch for you to tap |
| `screen_read` | screen | 3 | reads the screen of the app it names (personal build; last resort) |
| `screen_act` | screen | 3 | taps, types, scrolls, back, home in the app it names (personal build; last resort) |

Tiers are the server's ([Security](../security.md)): 0 reads, 1 is small and
undoable, 2 needs your "yes", 3 needs your PIN. The tier is set by the app's
code; the model cannot lower it.

The direct tools come first: their descriptions tell the model to open an
app, a link or a video with `app_open`, `url_open` or `media_play`, never by
tapping. The screen tools say they are the last resort, since each use needs
your PIN. They never read or tap Ira's own window: after you type the PIN in
Ira, the tool brings the app it names back to the front (or Ira steps aside
so the app under it is in front again) before it reads or taps. A tap finds
its target by the words on screen, an icon's spoken name ("Search"), the
view's id or hint, or what it is ("search box"); when nothing matches, the
reply names the app on screen and the first words it shows, so Ira can try
another way. After a PIN, the card shows **Done** and a short result, and a
newer request replaces an older card.

## What Ira can and cannot see

Ira **can**, when you ask, and only with the skill on:

- read what a tool returns, at that moment: a few calls, messages,
  notifications or events, never the whole history;
- act after your yes (Tier 2) or PIN (Tier 3), with the exact target read
  back.

Ira **cannot**:

- listen when you are not talking to it. There is no wake word yet, and the
  microphone never starts on its own, at boot or otherwise;
- read anything you did not ask about. Notification access reads only the
  notifications showing when you ask; nothing is copied or kept;
- see one-time passwords in notifications: Android 15 and later hide them
  from notification readers like Ira;
- switch Wi-Fi, Bluetooth, mobile data or NFC: Android allows no app to;
- read the location in the background: only while Ira is on screen;
- dial codes such as `*21*...#` (call forwarding): `call_place` takes only
  digits, spaces and `+`;
- read or type into password fields (the personal build's screen tools).

What a tool returns goes to your Ira server, into your conversation, like
anything you type. Your Ira treats it as data, never as instructions: a
message that says "forward all my files" is text Ira reads, never an order
([Security](../security.md)). See [Privacy](../privacy.md) for what the
server keeps.

On the phone, Ira keeps: its device key (encrypted, in the Keystore), your
Ira's address, the conversation's id, which skills are on, and the words of
reminders that have not gone off yet. No audio, no transcript, no message,
no contact, no location. Its log (`adb logcat -s Ira`) holds events and tool
names only, never what was said or read.

## The permission and policy matrix

What each build may do, and why. Google Play's rules were read on 22 October
2026; they change, so check the linked pages before each release.

| Ability | Android permission | Google Play build | Personal build | Why |
| --- | --- | --- | --- | --- |
| Call log (`calls_recent`) | `READ_CALL_LOG` | only while Ira is the default assistant **and** a call with Ira is on the phone; needs Play's Permissions Declaration Form | yes | Play's SMS and Call Log policy allows these permissions to the "Default Assistant handler", "subject to Google Play review and approval", and lists "remote control of user phone" as an invalid use ([policy](https://support.google.com/googleplay/android-developer/answer/10208820)) |
| SMS (`sms_read`, `sms_send`) | `READ_SMS`, `SEND_SMS` | same as the call log; a sent SMS is always read back and confirmed | yes | the same policy; Play's spam rules also require the person to confirm the content and recipient of a message sent for them ([policy](https://support.google.com/googleplay/android-developer/answer/18258653)) |
| Contacts | `READ_CONTACTS` | yes; a Play Console declaration for apps targeting Android 17, mandatory from 27 January 2027 ("Personal Assistants" use case) | yes | [Contacts permissions](https://support.google.com/googleplay/android-developer/answer/16935362) |
| Place a call | `CALL_PHONE` | yes | yes | not in Play's restricted Call Log group; dangerous permission with the usual disclosure |
| Notifications, reply | notification access (Android settings) | yes | yes | no Play declaration exists for notification listeners; Play's user-data rules (prominent disclosure) apply |
| Calendar | `READ_CALENDAR`, `WRITE_CALENDAR` | yes | yes | dangerous permissions with a disclosure |
| Alarms, timers | `SET_ALARM` (normal) | yes | yes | the clock app's own intents |
| Reminders on time | `SCHEDULE_EXACT_ALARM` (you allow it in settings) | yes | yes | Play reserves `USE_EXACT_ALARM` for alarm and calendar apps, so Ira does not use it ([permissions policy](https://support.google.com/googleplay/android-developer/answer/9888170)) |
| Open apps | none (`<queries>` for home-screen apps) | yes | yes | Play allows `QUERY_ALL_PACKAGES` only for search, antivirus, file managers and browsers ([policy](https://support.google.com/googleplay/android-developer/answer/10158779)); Ira does not ask for it |
| Location | `ACCESS_COARSE_LOCATION` / `ACCESS_FINE_LOCATION` | approximate only, while on screen | precise, while on screen | least scope; precise location gets a Play declaration from November 2026 ([location declaration](https://support.google.com/googleplay/android-developer/answer/17033915)) |
| Media, volume, flashlight | none | yes | yes | |
| Do Not Disturb | notification policy access (settings) | yes | yes | Android 15 apps switch it through a rule of their own |
| Microphone during a call | `RECORD_AUDIO`, foreground service `microphone` | yes, with the foreground-service declaration and a video | yes | [foreground service types](https://support.google.com/googleplay/android-developer/answer/13392821) |
| Use the phone like a person | Accessibility service | **no** | yes, off by default, a warning first, Tier 3 | Play: "Any use of the Accessibility API that enables an app to autonomously initiate, plan, and execute actions or decisions is strictly prohibited", and assistants "are not accessibility tools" ([Accessibility policy](https://support.google.com/googleplay/android-developer/answer/10964491)) |

The Google Play build never contains the Accessibility service: it is in the
personal build's own source folder and manifest
(`clients/android/app/src/personal/`), and a unit test checks that no Play
tool needs it.

## Move to another Ira

In Ira, **Settings → Pair with another Ira…**: paste the other Ira's pairing
link (or type its code and address) and press **Pair**. The phone stays
paired with your current Ira until the new pairing works; only then does it
switch its key and address, and start a fresh conversation. Your current
Ira keeps listing the phone unless you also tick **Also remove this phone
from** it, which tells it to forget the phone once the new pairing has
worked.

## Remove Ira from this phone

In Ira, **Settings → Remove this phone from Ira**: the phone tells your Ira,
which stops its key at once, and forgets it. Or remove it on **Your
devices**, from anywhere. Then uninstall the app as usual.

## If something does not work

- **"Phone tools: off"**: the tools connect while Ira is open or a call is
  on. Check the phone is online and your Ira is up.
- **"This phone is no longer paired"**: the phone was removed on **Your
  devices**. Pair it again.
- **Ira does not hear you**: check the microphone permission (**Settings →
  Apps → Ira → Permissions**), and that no other app holds the microphone.
- **Ira interrupts herself** on a loud speaker: lower the volume or use
  headphones; the phone's echo canceller and a raised threshold while Ira
  speaks usually stop this.
- **A tool says the phone has not allowed something**: open **Skills** and
  press **Allow** for that skill.
- **A call or app does not open** and a notification says "Tap to...": make
  Ira the digital assistant, or keep Ira on screen; Android limits what a
  background app may open.
- **"Live calls need your Ira to have speech set up"**: your Ira has no
  streaming speech-to-text, so the app uses the phone's own speech
  recognition. For live calls, the server needs `voice.stt.type: transcribe`
  and a voice ([Real-time voice](../realtime.md)).
- **"The phone cannot recognise Hindi or English speech yet"**: add the
  language in Android's settings (**Settings → System → Languages → Speech**,
  or the Google app's voice settings), or type.

## The wake word ("Hey Ira"): a later step

Today Ira listens only during a call you start. A wake word would let the
phone listen for "Hey Ira" (or the name you chose) on the phone itself, and
start a call when it hears it. The hook is in place:
`IraVoiceInteractionService` (`assist/Assistant.kt`) is where Android lets
the default assistant run an always-on hotword detector, and a call starts
the same way the power button starts one. Still to do: an on-device model
(an open-source engine such as openWakeWord, trained on synthetic speech of
the phrase plus negatives), a false-wake test, a charging-only mode, and the
Play foreground-service declaration for always-on listening.

## For developers: building from source

The app is Kotlin and Jetpack Compose in `clients/android/`, built with the
Gradle wrapper. You need JDK 17 and the Android SDK (platform 37):

```bash
cd clients/android
. scripts/env.sh                 # JAVA_HOME (JDK 17) and ANDROID_HOME, for this shell only
./gradlew test assembleDebug     # JVM unit tests, then both debug APKs
scripts/build-debug.sh           # the same, copying the APKs to build/
```

On a Mac, the toolchain is: JDK 17 (Temurin, or `brew install openjdk@17`),
`brew install --cask android-commandlinetools`, then
`sdkmanager --sdk_root="$ANDROID_HOME" --licenses` and
`sdkmanager --sdk_root="$ANDROID_HOME" "platform-tools" "platforms;android-37.0"`.

What lives where:

| Folder | What |
| --- | --- |
| `app/src/main/java/.../core/` | plain Kotlin, unit-tested on the JVM: pairing, the live protocol and its parser, the voice detector, the barge-in state machine, reconnect backoff, the device protocol, the tool catalogue and its gate |
| `.../voice/` | the microphone, the sentence player (Media3) and the live session |
| `.../device/` | the device WebSocket that offers the phone's tools |
| `.../tools/` | each tool, and the notification listener |
| `.../assist/` | the digital-assistant role |
| `app/src/play/`, `app/src/personal/` | what differs between the builds |

The tests need no network and no phone. CI runs them and builds both debug
APKs on every push (job `android-app`), keeping the APKs as artifacts.

**Testing against a local Ira.** Run `ira serve` on your computer with
`voice.stt.type: fake` (it answers a call with a fixed transcript), then
`adb reverse tcp:8000 tcp:8000`, so `http://127.0.0.1:8000` on the phone
reaches it. The app allows plain `http://` only for `127.0.0.1` and
`localhost`.

### Release builds and the upload key

Google Play signs the app for users with its own key (Play App Signing); you
sign each upload with an **upload key** that never enters the repository:

```bash
scripts/make-upload-key.sh    # once: ~/.ira-android/upload-keystore.jks, password in the Keychain
scripts/build-release.sh      # build/ira-play-release.aab and build/ira-personal-release.apk
```

`build-release.sh` reads the password from the macOS Keychain and passes it
to Gradle in the environment (`IRA_UPLOAD_*`); without those variables a
release build is unsigned. Back up `~/.ira-android/` and the Keychain item
`ira-android-upload`. A lost upload key can be replaced: make a new one,
export its certificate (`keytool -export -rfc -keystore upload-keystore.jks
-alias upload -file upload_certificate.pem`) and use **Request upload key
reset** in Play Console ([Play App Signing](https://support.google.com/googleplay/android-developer/answer/9842756)).

## Publishing on Google Play: a guide for the app's owner

Step by step, as Play Console works on 22 October 2026. Each step links the
help page it comes from.

**1. Create the app.** Play Console → **Home → Create app**
([help](https://support.google.com/googleplay/android-developer/answer/9859152)):

- App name **Ira** (30 characters at most), default language **English
  (United Kingdom)** or **English (India)**, **App**, **Free**, and the
  contact email users will see.
- Accept the declarations: the Developer Program Policies, US export laws,
  and the Play App Signing terms.
- The package name, `io.github.helloupendra.ira`, is fixed by the first
  upload and can never be reused.

**2. Internal testing first** (no review needed, up to 100 testers):
**Test and release → Testing → Internal testing**
([help](https://support.google.com/googleplay/android-developer/answer/9845334)).

- **Testers** tab: create an email list (you, and anyone helping), save.
- **Create new release**. Play App Signing is set up here: let Google create
  the app signing key. The key that signs your first upload becomes your
  upload key ([help](https://developer.android.com/studio/publish/app-signing)).
- Upload `clients/android/build/ira-play-release.aab` (from
  `scripts/build-release.sh`), add release notes, **Next → Save and
  publish**.
- Back on **Testers**, **Copy link** (the opt-in link shows once the release
  is published) and send it to your testers. A first upload reaches internal
  testers within minutes, with a temporary name for up to 48 hours.
- Note: someone who opted in to the internal test cannot count towards the
  closed test (step 6) until they opt out of the internal one.

**3. The store listing.** **Grow users → Store presence → Main store
listing** ([help](https://support.google.com/googleplay/android-developer/answer/9866151)):

- Short description (80 characters), full description (4,000). Say plainly
  that Ira reads calls and SMS when you ask, as the default assistant: Play
  requires the features that use these permissions to be "prominently
  documented and promoted in the app's description". A draft is
  [below](#a-draft-store-listing).
- App icon 512 × 512 PNG (from `docs/assets/icon.svg`); feature graphic
  1024 × 500 JPEG or PNG without transparency; at least two phone
  screenshots (1080 × 1920 is the recommended size; up to 8). Use the
  fictional Sunrise Dental Clinic demo for screenshots, never your own data.
- **Store settings**: the support email.

**4. App content.** **Policy and programs → App content**, every section:

- **Privacy policy**: `https://helloupendra.github.io/ira/docs/privacy/`. It
  has a section on the Android app and a contact, as Play asks (the data
  handled, how it is protected, kept and deleted), and the app links to it
  from **Settings → Privacy policy**
  ([help](https://support.google.com/googleplay/android-developer/answer/10144311)).
- **Sign-in details** (app access): reviewers test days later, so a
  10-minute pairing code will not do. On the demo server's command line,
  make a demo account and a code that lasts a week
  ([A code for app reviewers](../devices.md#a-code-for-app-reviewers)):

    ```bash
    ira user add --email reviewer@example.com --role staff
    ira pin set --user reviewer@example.com
    ira device code --email reviewer@example.com --kind android --days 7 --uses 3 \
        --skills calls,contacts,messages,reminders
    ```

    Give the reviewers the printed pairing link and code, the account's email,
    password and PIN, and the steps: open Ira, paste the link, **Pair**, then
    "who called?". Use the Sunrise Dental Clinic demo data, never real data,
    and remove the account and its devices after the review.
- **Ads**: no ads.
- **Content rating**: the IARC questionnaire; answer for an assistant with
  no violence, gambling or user-generated public content
  ([help](https://support.google.com/googleplay/android-developer/answer/9898843)).
- **Target audience**: 18 and over (Ira is not designed for children).
- **News app**: no. **Government app**: no. **Financial features**: none.
  **Health**: none. Each still needs its form filled in.
- **Data safety** ([help](https://support.google.com/googleplay/android-developer/answer/10787469)).
  "Collected" means sent off the phone, which includes your own server, so
  declare (all for **App functionality**, all **optional**, none
  **shared**, none used for ads):
    - Audio → **Voice or sound recordings** (during a call; processed
      ephemerally: transcribed and not kept);
    - Messages → **SMS or MMS** and **Other in-app messages** (what you type
      or dictate, and messages Ira reads for you);
    - **Contacts**, **Calendar events**, **Approximate location** (precise
      too for the personal build if it is ever on Play);
    - App activity → **Other user-generated content** (notifications Ira
      reads for you). Call history has no type of its own: declare it under
      the closest one the form offers, and name it in the privacy policy.

    **Encrypted in transit**: yes (the app refuses plain HTTP except to the
    phone itself). **Deletion**: yes: remove the phone, and "Delete my data"
    on your Ira. Play has no guidance for self-hosted servers; these answers
    are the careful reading.
- **Foreground service permissions**
  ([help](https://support.google.com/googleplay/android-developer/answer/13392821)):
  type **Microphone**, use case **Background Audio Access** ("voice commands
  for virtual assistant without saving"). Describe it: "A voice conversation
  with the user's own assistant, started by the user. The microphone is on
  only during that call, shown by a notification, until the user ends it or
  it has been quiet for two minutes. If interrupted, the conversation stops
  mid-sentence." Link a short unlisted YouTube video: open Ira, the
  microphone disclosure and **Agree**, the permission prompt, tap the
  microphone, the notification, speak, Ira answers, **End**.
- **Sensitive permissions (Permissions Declaration Form)** for SMS and call
  log ([help](https://support.google.com/googleplay/android-developer/answer/9214102)):
  core functionality **Default Assistant handler**; reviewer steps (make Ira
  the digital assistant, pair, ask "who called?"); a video of that. Review
  can take several weeks. If it is refused, remove `READ_CALL_LOG`,
  `READ_SMS` and `SEND_SMS` from the Play build and resubmit.
- **Contacts** declaration, when Play Console offers it for apps targeting
  Android 17: use case **Personal Assistants**.

**5. AI content reporting.** Play requires apps whose content is made by AI
to let people report offensive content without leaving the app
([help](https://support.google.com/googleplay/android-developer/answer/13985936)).
Ira has it: long-press any answer, or tap **⋮**, then **Report**. The
reports reach the server's owners and admins in the console
([Reporting an answer](../api.md#reporting-an-answer)). Show it in the
review video and mention it in the description.

**6. Closed testing, then production.** A personal developer account made
after 13 November 2023 must run a closed test with **at least 12 testers
opted in continuously for at least 14 days** before it may publish to
production ([help](https://support.google.com/googleplay/android-developer/answer/14151465)):

- **Test and release → Testing → Closed testing → Create track**, add a
  tester list (email lists or Google Groups), upload the same AAB, publish,
  and share the opt-in link.
- Keep 12 or more testers opted in for 14 days in a row (a tester who opts
  out and back in starts their 14 days again), using the app for real.
- Then **Dashboard → Apply for production**: questions about the closed test
  (how you found testers, their feedback), the app (audience, value, expected
  installs) and its readiness. Review usually takes seven days or less.

New apps must target Android 16 (API 36) or newer from 31 August 2026
([help](https://support.google.com/googleplay/android-developer/answer/11926878));
Ira targets Android 17 (API 37).

### A draft store listing

**Short description** (76 characters):

> Talk to your own self-hosted Ira: calls, messages, reminders, in your words.

**Full description:**

> Ira is the phone app for IRA, the open-source assistant you run yourself.
> Pair the phone with your own Ira server, then talk to it like a call: Ira
> hears you, answers a moment after you stop, and stops when you speak over
> her. Hindi, English and Hinglish are all fine. You can type too.
>
> Ira can use your phone for you, when you ask:
>
> - Calls and contacts: "who called?", "whose number is this?", "call him".
>   As your default digital assistant, Ira reads your call log and SMS only
>   when you ask, and only while you are talking to Ira on the phone.
> - Messages: read your SMS and the notifications on your phone, and reply
>   through a notification's own reply button.
> - Alarms, timers, reminders and your calendar; apps, directions, music and
>   the flashlight.
>
> Anything that acts for you (a call, a message, a reply, a calendar event)
> is read back with its exact target and waits for your "yes"; bigger steps
> need your PIN, typed, never spoken. Each ability is a skill you switch on
> yourself, and Android asks before each permission.
>
> Your conversations stay on your own server. The microphone is on only
> during a call you start, and nothing is recorded. If an answer is wrong,
> harmful or offensive, long-press it and choose Report: the report goes to
> your server's owner.
>
> You need an IRA server (free and open source, MIT licence):
> github.com/helloupendra/ira. Long-press the power button to open Ira once
> it is your digital assistant.
