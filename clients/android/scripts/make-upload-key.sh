#!/usr/bin/env bash
# Make the Google Play upload key, once, outside the repository:
#   ~/.ira-android/upload-keystore.jks (RSA 4096, alias "upload"),
#   its password in the macOS Keychain (service "ira-android-upload").
# Back up both: Play needs this key for every update (a lost key can be reset in Play
# Console, which takes a few days).
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source-path=SCRIPTDIR source=env.sh
. "$here/env.sh"

dir="$HOME/.ira-android"
store="$dir/upload-keystore.jks"
service="ira-android-upload"

if [ -f "$store" ]; then
  echo "The upload key already exists: $store"
  exit 0
fi
command -v security >/dev/null || { echo "This script stores the password in the macOS Keychain." >&2; exit 1; }

mkdir -p "$dir"
chmod 700 "$dir"
IRA_KEY_PASSWORD="$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32)"
export IRA_KEY_PASSWORD

# The password goes to the Keychain first, so a key never exists without it. (It is on
# security's command line for that moment; keytool reads it from the environment.)
security add-generic-password -U -a "$USER" -s "$service" -l "IRA Android upload key" -w "$IRA_KEY_PASSWORD"
keytool -genkeypair -noprompt \
  -keystore "$store" -storetype PKCS12 \
  -alias upload -keyalg RSA -keysize 4096 -validity 10000 \
  -dname "CN=IRA Android upload key" \
  -storepass:env IRA_KEY_PASSWORD -keypass:env IRA_KEY_PASSWORD
chmod 600 "$store"
echo "Made $store; its password is in the Keychain as \"$service\"."
echo "Its certificate's fingerprint, for your records:"
keytool -list -v -keystore "$store" -storepass:env IRA_KEY_PASSWORD | grep -E "SHA256:"
unset IRA_KEY_PASSWORD
