#!/usr/bin/env bash
# Run the unit tests and build both debug APKs into clients/android/build/:
#   ira-play-debug.apk      what Google Play will carry
#   ira-personal-debug.apk  the sideloaded build with everything
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source-path=SCRIPTDIR source=env.sh
. "$here/env.sh"
cd "$here/.."

./gradlew test assembleDebug
mkdir -p build
cp app/build/outputs/apk/play/debug/app-play-debug.apk build/ira-play-debug.apk
cp app/build/outputs/apk/personal/debug/app-personal-debug.apk build/ira-personal-debug.apk
ls -l build/*.apk
