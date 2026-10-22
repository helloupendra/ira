#!/bin/sh
# Build and test Ira for iPhone on a Mac with Xcode (CI's macOS runner):
#
#   scripts/ci.sh simulator   pick and boot an iPhone simulator (an iPhone 15 if there is one)
#   scripts/ci.sh kit         IraPhoneKit's tests on it
#   scripts/ci.sh app         the app from project.yml (XcodeGen), and its UI tests
#   scripts/ci.sh release     an unsigned Release build for the simulator, in dist/
#   scripts/ci.sh             all four
#   scripts/ci.sh diagnose    which kit file the compiler is slow on (one file per process)
#
# With IRA_TEST_SERVER, IRA_TEST_PAIRING and IRA_UITEST_LINK set (see
# scripts/local-ira.sh), the tests also pair with that local Ira, talk to it
# and answer its tool calls. Nothing here signs with an Apple identity:
# simulator builds need none.
set -eu
cd "$(dirname "$0")/.."
mkdir -p build

# Test runners see variables prefixed TEST_RUNNER_, without the prefix.
export TEST_RUNNER_IRA_TEST_SERVER="${IRA_TEST_SERVER:-}"
export TEST_RUNNER_IRA_TEST_PAIRING="${IRA_TEST_PAIRING:-}"
export TEST_RUNNER_IRA_UITEST_LINK="${IRA_UITEST_LINK:-}"

simulator() {
    xcrun simctl list --json devices available | python3 -c '
import json, sys
runtimes = json.load(sys.stdin)["devices"]
ios = sorted((r for r in runtimes if ".iOS-" in r), key=lambda r: [int(p) for p in r.split(".iOS-")[1].split("-")])
for runtime in reversed(ios):
    phones = [d for d in runtimes[runtime] if d["name"].startswith("iPhone")]
    for d in sorted(phones, key=lambda d: (not d["name"].startswith("iPhone 15"), d["name"])):
        print(d["udid"], d["name"], runtime.rsplit(".", 1)[-1], sep="|")
        sys.exit(0)
sys.exit("no iPhone simulator")
' >build/simulator
    echo "Simulator: $(cat build/simulator)"
    udid=$(cut -d'|' -f1 build/simulator)
    xcrun simctl boot "$udid" 2>/dev/null || true
    xcrun simctl bootstatus "$udid" -b >/dev/null
}

udid() {
    [ -s build/simulator ] || simulator >&2
    cut -d'|' -f1 build/simulator
}

kit() {
    destination="platform=iOS Simulator,id=$(udid)"
    cd IraPhoneKit
    xcodebuild build-for-testing -scheme IraPhoneKit -destination "$destination" -derivedDataPath ../build/kit
    xcodebuild test-without-building -scheme IraPhoneKit -destination "$destination" -derivedDataPath ../build/kit \
        -resultBundlePath ../build/kit.xcresult
    cd ..
}

app() {
    destination="platform=iOS Simulator,id=$(udid)"
    xcodegen generate --quiet
    xcodebuild build-for-testing -project Ira.xcodeproj -scheme Ira -destination "$destination" \
        -derivedDataPath build/app
    xcrun simctl install "$(udid)" build/app/Build/Products/Debug-iphonesimulator/Ira.app
    # What the UI tests would otherwise answer in iOS's prompts.
    for service in microphone contacts; do
        xcrun simctl privacy "$(udid)" grant "$service" io.github.helloupendra.ira || true
    done
    xcodebuild test-without-building -project Ira.xcodeproj -scheme Ira -destination "$destination" \
        -derivedDataPath build/app -resultBundlePath build/app.xcresult \
        -test-timeouts-enabled YES -default-test-execution-time-allowance 180
}

release() {
    [ -d Ira.xcodeproj ] || xcodegen generate --quiet
    xcodebuild build -project Ira.xcodeproj -scheme Ira -configuration Release \
        -destination "generic/platform=iOS Simulator" -derivedDataPath build/release CODE_SIGNING_ALLOWED=NO
    mkdir -p dist
    rm -f dist/Ira-simulator.zip
    ditto -c -k --keepParent build/release/Build/Products/Release-iphonesimulator/Ira.app dist/Ira-simulator.zip
    ls -l dist
}

# Which file the compiler spends its time on: one file per compiler process, and
# every 30 s the files still compiling and for how long. Stops after 150 s.
diagnose() {
    cd IraPhoneKit
    swift build -Xswiftc -disable-batch-mode -Xswiftc -j2 >../build/diagnose.log 2>&1 &
    build=$!
    for tick in 1 2 3 4 5; do
        sleep 30
        kill -0 "$build" 2>/dev/null || break
        echo "== after $((tick * 30)) s, still compiling:"
        ps -axo etime=,args= | grep '[s]wift-frontend' | sed -n 's/^ *\([0-9:]*\) .*-primary-file \([^ ]*\).*/\1 \2/p' | sort -u
    done
    kill "$build" 2>/dev/null || true
    pkill -f swift-frontend || true
    grep -E "error|warning: (expression|instance method|function)" ../build/diagnose.log | head -20 || true
    tail -5 ../build/diagnose.log
    cd ..
}

case "${1:-all}" in
    simulator) simulator ;;
    kit) kit ;;
    app) app ;;
    release) release ;;
    diagnose) diagnose ;;
    all) simulator && kit && app && release ;;
    *) echo "usage: scripts/ci.sh [simulator|kit|app|release]" >&2; exit 2 ;;
esac
