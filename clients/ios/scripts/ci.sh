#!/bin/sh
# Build and test Ira for iPhone on a Mac with Xcode (CI's macOS runner):
#
# 1. IraPhoneKit's tests on an iOS simulator;
# 2. the app from project.yml (XcodeGen), for the simulator, and its UI tests;
# 3. an unsigned Release build of Ira.app for the simulator, zipped in dist/.
#
# With IRA_TEST_SERVER, IRA_TEST_PAIRING and IRA_UITEST_LINK set (see
# scripts/local-ira.sh), the tests also pair with that local Ira, talk to it and
# answer its tool calls. Nothing here signs with an Apple identity: simulator
# builds need none.
set -eu
cd "$(dirname "$0")/.."

device=$(xcrun simctl list --json devices available | python3 -c '
import json, sys
runtimes = json.load(sys.stdin)["devices"]
ios = sorted((r for r in runtimes if ".iOS-" in r), key=lambda r: [int(p) for p in r.split(".iOS-")[1].split("-")])
for runtime in reversed(ios):
    phones = [d for d in runtimes[runtime] if d["name"].startswith("iPhone")]
    # The iPhone 15 when there is one (the owner has one), else the first iPhone.
    for d in sorted(phones, key=lambda d: (not d["name"].startswith("iPhone 15"), d["name"])):
        print(d["udid"], d["name"], runtime.rsplit(".", 1)[-1], sep="|")
        sys.exit(0)
sys.exit("no iPhone simulator")
')
udid=${device%%|*}
echo "Simulator: $device"
xcrun simctl boot "$udid" 2>/dev/null || true
xcrun simctl bootstatus "$udid" -b >/dev/null

# Test runners see variables prefixed TEST_RUNNER_, without the prefix.
export TEST_RUNNER_IRA_TEST_SERVER="${IRA_TEST_SERVER:-}"
export TEST_RUNNER_IRA_TEST_PAIRING="${IRA_TEST_PAIRING:-}"
export TEST_RUNNER_IRA_UITEST_LINK="${IRA_UITEST_LINK:-}"

echo "== IraPhoneKit tests on the simulator"
(cd IraPhoneKit && xcodebuild test -quiet -scheme IraPhoneKit -destination "id=$udid" \
    -derivedDataPath ../build/kit -resultBundlePath ../build/kit.xcresult)

echo "== The app and its UI tests"
xcodegen generate --quiet
xcodebuild build-for-testing -quiet -project Ira.xcodeproj -scheme Ira -destination "id=$udid" \
    -derivedDataPath build/app
app=build/app/Build/Products/Debug-iphonesimulator/Ira.app
xcrun simctl install "$udid" "$app"
# What the UI tests would otherwise answer in iOS's prompts.
for service in microphone contacts; do
    xcrun simctl privacy "$udid" grant "$service" io.github.helloupendra.ira || true
done
xcodebuild test-without-building -quiet -project Ira.xcodeproj -scheme Ira -destination "id=$udid" \
    -derivedDataPath build/app -resultBundlePath build/app.xcresult

echo "== Ira.app for the simulator, unsigned"
xcodebuild build -quiet -project Ira.xcodeproj -scheme Ira -configuration Release -sdk iphonesimulator \
    -destination "generic/platform=iOS Simulator" -derivedDataPath build/release CODE_SIGNING_ALLOWED=NO
mkdir -p dist
rm -f dist/Ira-simulator.zip
ditto -c -k --keepParent build/release/Build/Products/Release-iphonesimulator/Ira.app dist/Ira-simulator.zip
ls -l dist
