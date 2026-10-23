#!/usr/bin/env bash
# Check a built APK or bundle carries the SMS and call-log permissions only where it should:
#   scripts/check-permissions.sh lite  build/ira-play-lite.aab      none of them
#   scripts/check-permissions.sh full  build/ira-play-release.aab   all of them
# A bundle's manifest is protobuf, whose strings are plain UTF-8, so a byte search is exact.
set -euo pipefail

want="$1"
file="$2"
restricted="android.permission.READ_CALL_LOG android.permission.READ_SMS android.permission.SEND_SMS"

case "$file" in
  *.aab) manifest="$(unzip -p "$file" base/manifest/AndroidManifest.xml | LC_ALL=C tr -c '[:print:]' '\n')" ;;
  *.apk)
    aapt2=""
    for tool in "$ANDROID_HOME"/build-tools/*/aapt2; do aapt2="$tool"; done
    manifest="$("$aapt2" dump permissions "$file")"
    ;;
  *) echo "an .apk or .aab, please" >&2; exit 2 ;;
esac

status=0
for permission in $restricted; do
  if grep -q "$permission" <<<"$manifest"; then found=yes; else found=no; fi
  if [ "$want" = lite ] && [ "$found" = yes ]; then echo "$file: has $permission, which Play Lite must not" >&2; status=1; fi
  if [ "$want" = full ] && [ "$found" = no ]; then echo "$file: lacks $permission" >&2; status=1; fi
done
[ "$status" = 0 ] && echo "$file: the SMS and call-log permissions are as a $want build needs"
exit "$status"
