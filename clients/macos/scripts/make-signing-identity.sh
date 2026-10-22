#!/bin/sh
# Make a code-signing identity for Ira on this Mac. Run it once.
#
# Without an Apple Developer account, Ira is signed "ad hoc": every new build
# looks like a new app to macOS, so it asks again for the microphone, Screen
# Recording, Contacts and the rest, and for Ira's key in the Keychain. Signed
# with the same identity every time, each build is the same app to macOS, and
# the permissions stay.
#
# This makes a self-signed certificate for code signing ("Ira Local Signing"),
# valid for ten years, and puts it with its private key in your login
# keychain. Nothing is sent anywhere. make-app.sh uses it when it is there.
# The first build may ask whether codesign may use the key: choose Always Allow.
#
# It is not a Developer ID: a dmg built with it still needs right-click, Open
# (or Open Anyway in Privacy & Security) on another Mac. Notarization needs the
# paid Apple Developer Program; see docs/clients/macos.md.
#
#   scripts/make-signing-identity.sh            make it (once)
#   scripts/make-signing-identity.sh --remove   remove it
set -eu

name="${IRA_SIGNING_NAME:-Ira Local Signing}"
keychain="${IRA_SIGNING_KEYCHAIN:-$HOME/Library/Keychains/login.keychain-db}"

if [ "${1:-}" = "--remove" ]; then
  security delete-identity -c "$name" "$keychain" >/dev/null 2>&1 \
    && echo "Removed the signing identity \"$name\"." \
    || echo "There was no signing identity \"$name\"."
  exit 0
fi

if security find-identity -p codesigning "$keychain" 2>/dev/null | grep -q "\"$name\""; then
  echo "The signing identity \"$name\" is already in your keychain. Nothing to do."
  exit 0
fi

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
cat > "$work/cert.conf" <<CONF
[req]
distinguished_name = dn
x509_extensions = ext
prompt = no
[dn]
CN = $name
[ext]
basicConstraints = critical,CA:false
keyUsage = critical,digitalSignature
extendedKeyUsage = critical,codeSigning
CONF

pass=$(/usr/bin/openssl rand -hex 16)
/usr/bin/openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -config "$work/cert.conf" \
  -keyout "$work/key.pem" -out "$work/cert.pem" 2>/dev/null
/usr/bin/openssl pkcs12 -export -inkey "$work/key.pem" -in "$work/cert.pem" -name "$name" \
  -out "$work/identity.p12" -passout "pass:$pass"
# -T: codesign may use the key; nothing else may.
security import "$work/identity.p12" -k "$keychain" -P "$pass" -T /usr/bin/codesign >/dev/null

if security find-identity -p codesigning "$keychain" | grep -q "\"$name\""; then
  echo "Made the signing identity \"$name\" in your login keychain."
  echo "Now build Ira with scripts/make-app.sh: it signs with it, and macOS keeps"
  echo "Ira's permissions from one build to the next."
else
  echo "The identity was not found after importing it. Open Keychain Access and look for \"$name\"." >&2
  exit 1
fi
