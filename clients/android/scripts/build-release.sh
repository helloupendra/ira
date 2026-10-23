#!/usr/bin/env bash
# Build the signed release: the Play bundle (AAB) and the personal APK, into
# clients/android/build/. The upload key's password is read from the macOS Keychain and
# passed to Gradle in the environment; it is never written to a file.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source-path=SCRIPTDIR source=env.sh
. "$here/env.sh"
cd "$here/.."

store="$HOME/.ira-android/upload-keystore.jks"
[ -f "$store" ] || { echo "No upload key yet: run scripts/make-upload-key.sh" >&2; exit 1; }
password="$(security find-generic-password -a "$USER" -s ira-android-upload -w)"

IRA_UPLOAD_STORE_FILE="$store" \
IRA_UPLOAD_STORE_PASSWORD="$password" \
IRA_UPLOAD_KEY_ALIAS="upload" \
IRA_UPLOAD_KEY_PASSWORD="$password" \
  ./gradlew test bundlePlayRelease bundlePlayLiteRelease assemblePersonalRelease
unset password

mkdir -p build
cp app/build/outputs/bundle/playRelease/app-play-release.aab build/ira-play-release.aab
cp app/build/outputs/bundle/playLiteRelease/app-playLite-release.aab build/ira-play-lite.aab
cp app/build/outputs/apk/personal/release/app-personal-release.apk build/ira-personal-release.apk

# The full Play build asks for SMS and the call log; Play Lite must not.
scripts/check-permissions.sh full build/ira-play-release.aab
scripts/check-permissions.sh lite build/ira-play-lite.aab

# Check all three are signed by the upload key.
jarsigner -verify build/ira-play-release.aab >/dev/null && echo "build/ira-play-release.aab: signed"
jarsigner -verify build/ira-play-lite.aab >/dev/null && echo "build/ira-play-lite.aab: signed"
apksigner=""
for tool in "$ANDROID_HOME"/build-tools/*/apksigner; do apksigner="$tool"; done
"$apksigner" verify build/ira-personal-release.apk && echo "build/ira-personal-release.apk: signed"
