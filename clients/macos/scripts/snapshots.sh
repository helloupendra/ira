#!/bin/sh
# Draw Ira for Mac's window into PNGs, offscreen, with a test build that never touches the
# installed Ira: its own bundle id (in.ira.mac.test) and name ("Ira Test"), no Keychain
# prompt, no permission asked, and nothing left behind. After the run its Keychain item,
# its settings, its permissions (tccutil) and its LaunchServices entry are gone, so System
# Settings never lists a second Ira.
#
#   scripts/snapshots.sh <folder>                 an unpaired window
#   scripts/snapshots.sh <folder> <pairing link>  paired with a test server first
#
# The pairing link comes from a throwaway server (POST /v1/me/devices/pairing), never from
# anyone's own Ira.
set -eu

[ $# -ge 1 ] || { echo "usage: scripts/snapshots.sh <folder> [pairing link]" >&2; exit 2; }
here=$(cd "$(dirname "$0")/.." && pwd)
out=$1
link=${2:-}
test_id=in.ira.mac.test
app="$here/dist/build.noindex/Ira Test.app"
lsregister=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister

forget() {
  # One item a call: the key, and the server kept with it.
  while security delete-generic-password -s "$test_id" >/dev/null 2>&1; do :; done
  defaults delete "$test_id" >/dev/null 2>&1 || true
}
cleanup() {
  forget
  rm -f "$HOME/Library/Preferences/$test_id.plist"
  tccutil reset All "$test_id" >/dev/null 2>&1 || true
  "$lsregister" -u "$app" >/dev/null 2>&1 || true
}
trap cleanup EXIT

BUNDLE_ID=$test_id IRA_SIGNING_NAME=none "$here/scripts/make-app.sh" >/dev/null
# A fresh build is a new app to the Keychain: start from nothing, past the first-run guide.
forget
defaults write "$test_id" firstRunDone -bool true
export IRA_KEYCHAIN_NO_UI=1
if [ -n "$link" ]; then
  "$app/Contents/MacOS/Ira" --pair "$link"
fi
mkdir -p "$out"
IRA_SNAPSHOT="$out" "$app/Contents/MacOS/Ira"
echo "Snapshots in $out"
