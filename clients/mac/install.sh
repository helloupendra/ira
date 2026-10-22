#!/bin/bash
# Install (or update) the Ira companion for this Mac user. Safe to run again.
#
#   ./install.sh                     install, and pair if this Mac has no token yet
#   ./install.sh --pair              pair again (a new code from the Devices page)
#   ./install.sh --server URL        the IRA server, when you type a code, not a link
#                                    (a zip from your server already knows it: server.txt)
#
# What it sets up, all under your own account (no sudo):
#   ~/Library/Application Support/ira-mac/    the companion, its virtualenv, logs
#   ~/Library/LaunchAgents/in.ira.mac.plist   starts the daemon at login, keeps it up
#   Chrome's NativeMessagingHosts/in.ira.mac.json  lets only the Ira extension reach it
#   the device token, in your login Keychain (service "ira-mac"), never in a file
set -euo pipefail

EXTENSION_ID="lidenefpfghfkmlcddnbjmladjhobdhp"
LABEL="in.ira.mac"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="$HOME/Library/Application Support/ira-mac"
AGENT="$HOME/Library/LaunchAgents/$LABEL.plist"
SERVER=""
PAIR=0

while [ $# -gt 0 ]; do
    case "$1" in
        --server) SERVER="${2:?--server needs an address}"; shift 2 ;;
        --pair) PAIR=1; shift ;;
        -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

say() { printf '\n%s\n' "$*"; }
fail() { printf 'Error: %s\n' "$*" >&2; exit 1; }

if [ "$(uname -s)" != "Darwin" ] && [ -z "${IRA_MAC_ANY_OS:-}" ]; then
    fail "the Ira companion is for macOS"
fi

# Python 3.9 or newer: Homebrew's, the Command Line Tools' own, or python.org's (last:
# it has no certificates until its "Install Certificates" step; the companion copes).
PYTHON=""
for candidate in "${IRA_PYTHON:-}" /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3 \
    /Library/Frameworks/Python.framework/Versions/Current/bin/python3; do
    [ -n "$candidate" ] && [ -x "$candidate" ] || continue
    if [ "$candidate" = /usr/bin/python3 ] && ! xcode-select -p >/dev/null 2>&1; then
        continue  # only a stub that offers to install the Command Line Tools
    fi
    if "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
        PYTHON="$candidate"
        break
    fi
done
[ -n "$PYTHON" ] || fail "Python 3.9 or newer is needed. Run: xcode-select --install"
say "Using $PYTHON (Python $("$PYTHON" -c 'import sys; print(sys.version.split()[0])'))"

say "Installing the Ira companion in $APP"
mkdir -p "$APP/app" "$APP/run" "$APP/logs"
chmod 700 "$APP" "$APP/run" "$APP/logs"
rm -rf "$APP/app/ira_mac"
cp -R "$HERE/ira_mac" "$APP/app/ira_mac"
# The server a typed code is for: --server, else the one that served this download.
rm -f "$APP/server.txt"
if [ -n "$SERVER" ]; then
    printf '%s\n' "$SERVER" > "$APP/server.txt"
elif [ -f "$HERE/server.txt" ]; then
    cp "$HERE/server.txt" "$APP/server.txt"
fi
find "$APP/app" -name __pycache__ -type d -prune -exec rm -rf {} +

# The Chrome extension, kept where "Load unpacked" can find it again after updates.
EXTENSION=""
for folder in "$HERE/chrome-extension" "$HERE/../chrome-extension"; do
    if [ -f "$folder/manifest.json" ]; then EXTENSION="$folder"; break; fi
done
if [ -n "$EXTENSION" ]; then
    rm -rf "$APP/chrome-extension"
    mkdir -p "$APP/chrome-extension"
    for item in manifest.json background.js reader.js popup.html popup.js popup.css icons README.md; do
        [ -e "$EXTENSION/$item" ] && cp -R "$EXTENSION/$item" "$APP/chrome-extension/"
    done
fi

if [ ! -x "$APP/venv/bin/python" ]; then
    "$PYTHON" -m venv "$APP/venv"
fi
if [ -z "${IRA_MAC_NO_PIP:-}" ]; then
    # truststore: macOS's own certificates; certifi: a bundle for Python 3.9.
    "$APP/venv/bin/python" -m pip install --quiet --disable-pip-version-check \
        "websockets>=13,<18" "certifi" "truststore; python_version >= '3.10'"
fi

companion() { PYTHONPATH="$APP/app" "$APP/venv/bin/python" -m ira_mac "$@"; }

# A launcher: ira-mac status, ira-mac detach, ira-mac pair.
cat > "$APP/ira-mac" <<LAUNCHER
#!/bin/sh
PYTHONPATH="$APP/app" exec "$APP/venv/bin/python" -m ira_mac "\$@"
LAUNCHER
chmod 755 "$APP/ira-mac"

# The native messaging host: a small wrapper Chrome starts for the extension.
HOST="$APP/ira-chrome-host"
cat > "$HOST" <<HOSTSCRIPT
#!/bin/sh
# Chrome starts this for the Ira extension (native messaging host $LABEL). It relays only.
PYTHONPATH="$APP/app" exec "$APP/venv/bin/python" -m ira_mac host
HOSTSCRIPT
chmod 755 "$HOST"

json_string() { "$PYTHON" -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$1"; }
for browser in "Google/Chrome" "Google/Chrome Beta" "Chromium"; do
    base="$HOME/Library/Application Support/$browser"
    [ "$browser" = "Google/Chrome" ] || [ -d "$base" ] || continue
    mkdir -p "$base/NativeMessagingHosts"
    cat > "$base/NativeMessagingHosts/$LABEL.json" <<MANIFEST
{
  "name": "$LABEL",
  "description": "Ira companion for Mac",
  "path": $(json_string "$HOST"),
  "type": "stdio",
  "allowed_origins": ["chrome-extension://$EXTENSION_ID/"]
}
MANIFEST
done

# Pair when asked to, or when this Mac has no token yet.
has_token="$(companion status 2>/dev/null | "$PYTHON" -c 'import json, sys; print(json.load(sys.stdin).get("token_in_keychain", False))' || echo False)"
if [ -z "${IRA_MAC_NO_PAIR:-}" ] && { [ "$PAIR" = 1 ] || [ "$has_token" != True ]; }; then
    say "Pair this Mac: on the Devices page of your Ira app, choose Add a device, then Mac."
    companion pair
fi

xml() { "$PYTHON" -c 'import sys; from xml.sax.saxutils import escape; print(escape(sys.argv[1]))' "$1"; }
mkdir -p "$(dirname "$AGENT")"
cat > "$AGENT" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$(xml "$APP/venv/bin/python")</string>
    <string>-m</string>
    <string>ira_mac</string>
    <string>run</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict><key>PYTHONPATH</key><string>$(xml "$APP/app")</string></dict>
  <key>WorkingDirectory</key><string>$(xml "$APP")</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>ProcessType</key><string>Background</string>
  <key>StandardOutPath</key><string>$(xml "$APP/logs/launchd.log")</string>
  <key>StandardErrorPath</key><string>$(xml "$APP/logs/launchd.log")</string>
</dict>
</plist>
PLIST

if [ -z "${IRA_MAC_NO_AGENT:-}" ]; then
    launchctl bootout "gui/$(id -u)" "$AGENT" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$AGENT"
    launchctl kickstart -k "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
fi

say "Done. The Ira companion runs in the background and starts again at login."
if [ -n "$EXTENSION" ]; then
    cat <<NEXT

Next, in Chrome:
  1. Open chrome://extensions and switch on Developer mode (top right).
  2. Click "Load unpacked" and choose:
       $APP/chrome-extension
  3. Click the Ira icon in the toolbar: it should say "Connected".

Then ask Ira: "Chrome mein kaunse tabs khule hain?"
NEXT
fi
