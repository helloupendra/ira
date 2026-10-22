# Ira on iPhone

There is no Ira app in the App Store yet. An iPhone still gets most of Ira
two ways, with nothing to install from a store:

1. **The Ira web app on your Home Screen.** It opens like an app, without
   Safari's bars, and does everything the web app does: typing, the mic, the
   live call, actions with your yes or PIN, your devices, connections and
   businesses.
2. **"Hey Siri, Ask Ira"**, a Shortcut that sends what you say to your Ira
   and speaks the answer, from the lock screen, AirPods or CarPlay.

## Put Ira on your Home Screen

1. Open your Ira's address in **Safari** (it must be `https://`), and sign
   in.
2. Tap **Share**, then **Add to Home Screen**, then **Add**.
3. Open **Ira** from the Home Screen. The first time you talk, allow the
   microphone.

### Talking

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

## "Hey Siri, Ask Ira"

The Shortcut takes your words with the iPhone's own dictation, sends them
to your Ira, and reads the answer aloud. It uses a token that can only
**ask**: it cannot say yes to an action, pair a device or open the console.
When Ira proposes something that needs your yes, the Shortcut says so, and
you confirm it in the Ira app.

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
phone if one is paired, and in Telegram if you linked it. **An iPhone gets
no notification from Ira while the app is closed** (Ira does not send web
push notifications yet): for an alarm on the iPhone itself, ask Siri
directly.

### If the Shortcut fails

- **"invalid or revoked token"**: the token was stopped, or copied wrong.
  Make a new one.
- **An error page instead of an answer**: check the URL ends in `/v1/ask`
  and starts with `https://`.
- **It hears the wrong language**: set Dictate Text's language; Hindi
  (India) also understands Hinglish best.

## iPhone and Android, compared

| | iPhone (web app and Shortcuts) | [Android app](android.md) |
| --- | --- | --- |
| Talk, type, live call, barge-in | yes, while the app is open | yes |
| "Hey Siri" / assistant button | "Hey Siri, Ask Ira" (one question at a time) | long-press the power button |
| Background mic, wake word | no: iOS allows none | no wake word yet; no background mic |
| Read your calls, SMS, notifications | **no**: iOS lets no app read them | yes, with each skill switched on |
| Call or text for you | no | yes, after your yes |
| Alarms, timers | through Siri itself | yes |
| Reminders from Ira | in the app while open, or on another device | yes, a notification |
| Your contacts, calendar | no (Ira reads a calendar through [Google](../connectors.md#google-gmail-and-calendar-read-only)) | yes |

The iPhone's limits are Apple's: no app, native or web, may read your SMS,
call log or other apps' notifications.

## A native iPhone app, later

A native app could add a better Siri integration (App Intents), a widget,
and notifications. Building one needs a Mac with **Xcode** (the full app,
not only the Command Line Tools) for the iOS SDK, and the paid **Apple
Developer Program** to install it through TestFlight or the App Store. It
would use the same server routes as the Android app.

## What could only be tested on a real iPhone

The web app was tested in WebKit (Safari's engine) as an iPhone 15: install
tags and icon, the tap that unlocks sound, typing, a live call with a mock
microphone (audio up, Ira's MP3 sentences decoded and played back), the
screen lock, the audio session, Report, and the Siri token page. These need
a real iPhone to confirm: the silent switch, whether a call's sound comes
from the speaker or the earpiece, the microphone prompt in a Home Screen
app, and Siri running the Shortcut.
