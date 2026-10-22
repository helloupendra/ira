# Ira for iPhone

A native iPhone app for your own Ira: type or talk, a live call with
barge-in, "Hey Siri, Ask Ira" with no Shortcut to build, and the iPhone's
contacts, calendar, reminders, location and calls as tools Ira may use when
you ask. iOS 17 or later. What it does, for people, is in
[docs/clients/iphone.md](../../docs/clients/iphone.md); this file is for
building it.

## Layout

| Where | What |
| --- | --- |
| `IraPhoneKit/` | a Swift package with everything that needs no screen: pairing (`POST /v1/devices/pair`, kind `ios`), the Keychain rules, the device WebSocket, live voice protocol 1, `/v1/ask/stream` and `/v1/ask`, actions and reports, the voice detector, the audio engine, the iPhone's speech recognition, the tools and their tiers, and the first-run checklist. It builds for iOS 17 and macOS 14 |
| `IraPhoneKit/Tests/` | 95 tests (Swift Testing): pairing links and the exchange against a URLProtocol stub, both protocols against a fake WebSocket, the voice detector on synthetic audio, sentences in order, the stream, proposals and outcomes, the tool catalog and its tiers, the toolbox's permission gates and deadlines, calls, the Keychain rules, the checklist and the transcript. `LocalServerCheck` runs only against a real Ira (below) |
| `Ira/` | the app: SwiftUI views, the conversation and call controller, the App Intents ("Ask Ira", "Tell Ira", "Talk to Ira"), `Info.plist`, the icon |
| `IraUITests/` | the app on a simulator: the checklist, a bad code, and with a local Ira, pairing, asking, and a tool call answered from the simulator's contacts |
| `project.yml` | the Xcode project, for [XcodeGen](https://github.com/yonaskolb/XcodeGen) |
| `scripts/` | `test-kit.sh` (the kit's tests on a Mac), `local-ira.sh` (a local Ira for the tests), `ci.sh` (what CI runs), `make-icon.swift` (draws the icon) |

**Why XcodeGen.** The project is generated from `project.yml`, never
committed: a change to a setting reviews as one line, nothing merges a
`project.pbxproj`, and CI and a person's Mac make the same project. XcodeGen
is one small Homebrew tool that writes a plain Xcode project and then gets
out of the way. Tuist does more (caching, its own Swift manifests and a
runtime of its own), which this app does not need.

**Why a package.** Most of the app is in IraPhoneKit, which also builds for
macOS, so its tests run with `swift test` on a Mac with only the Command
Line Tools, in a second, and the same tests run on an iOS simulator in CI.

## Build and test

On a Mac with only the Command Line Tools (no iOS SDK), the kit and its tests:

```bash
cd clients/ios
scripts/test-kit.sh
```

On a Mac with Xcode 16 or later (26 or later to upload to App Store Connect), everything, as CI does:

```bash
brew install xcodegen
cd clients/ios
xcodegen generate            # writes Ira.xcodeproj
open Ira.xcodeproj           # or: scripts/ci.sh
```

`scripts/ci.sh` picks an iPhone simulator (an iPhone 15 when there is one),
runs the kit's tests on it, builds the app, runs the UI tests, and zips an
unsigned Release build for the simulator in `dist/Ira-simulator.zip`. To
open it in a simulator: unzip, then `xcrun simctl install booted Ira.app`.

### Against a local Ira

`scripts/local-ira.sh` starts `ira serve` on 127.0.0.1:8799 (set
`IRA_TEST_PORT` for another) with the demo model and fake speech-to-text
and voice, makes an owner, a PIN and an iPhone pairing code with every
iPhone skill on, and prints the variables the tests read:

```bash
eval "$(scripts/local-ira.sh)"
export IRA_TEST_SERVER IRA_TEST_PAIRING IRA_UITEST_LINK
scripts/test-kit.sh --filter LocalServerCheck   # on this Mac
scripts/ci.sh                                    # and on a simulator, with Xcode
kill "$(cat "$IRA_TEST_DIR/ira.pid")"
```

`LocalServerCheck` pairs as the app does, says hello with the iPhone's
tools, answers a real `contacts_lookup` call, says yes to a Tier 2
`call_place` proposal and answers that call, then holds a live call: a
typed turn, a spoken one (the voice detector on a synthetic tone), a
barge-in, and a report.

### On your own iPhone

Choose your team in Xcode (the Ira target, Signing & Capabilities) and run
on the iPhone; or see [The native app: TestFlight](../../docs/clients/iphone.md#the-native-app-testflight)
for a paid membership, and the free Apple ID option there. The bundle id is
`io.github.helloupendra.ira`; change it in `project.yml` if you build your
own copy under your own Apple account.

## Notes

- **Swift 6** language mode throughout. Callbacks that iOS makes on its own
  threads (the microphone tap, playback, speech recognition, location) are
  made outside any actor and hop to the main actor, so the runtime's
  isolation checks never trip on them.
- **The token** is in the Keychain, readable only on this iPhone after its
  first unlock since it started, never synced or in a backup that moves to
  another phone. A read that fails is never "not paired".
- **No third-party dependencies**: everything comes with iOS.
- **Logs** go to the system log (subsystem `io.github.helloupendra.ira`):
  tool names and outcomes, never what was said, read or answered; tokens and
  codes are masked.
