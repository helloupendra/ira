#!/bin/bash
# Remove the Ira companion from this Mac user. Safe to run again.
#
# It tells the server goodbye (which revokes this Mac's token), stops the
# daemon, and removes the LaunchAgent, the Chrome native messaging manifests,
# the Keychain item and ~/Library/Application Support/ira-mac. Remove the
# extension in chrome://extensions yourself.
set -uo pipefail

LABEL="in.ira.mac"
APP="$HOME/Library/Application Support/ira-mac"
AGENT="$HOME/Library/LaunchAgents/$LABEL.plist"

if [ -x "$APP/venv/bin/python" ] && [ -d "$APP/app/ira_mac" ] && [ -z "${IRA_MAC_NO_PAIR:-}" ]; then
    PYTHONPATH="$APP/app" "$APP/venv/bin/python" -m ira_mac unpair || true
fi

if [ -z "${IRA_MAC_NO_AGENT:-}" ]; then
    launchctl bootout "gui/$(id -u)" "$AGENT" 2>/dev/null || true
fi
rm -f "$AGENT"

for browser in "Google/Chrome" "Google/Chrome Beta" "Chromium"; do
    rm -f "$HOME/Library/Application Support/$browser/NativeMessagingHosts/$LABEL.json"
done

if [ -z "${IRA_MAC_NO_PAIR:-}" ] && [ -x /usr/bin/security ]; then
    /usr/bin/security delete-generic-password -s ira-mac -a device >/dev/null 2>&1 || true
fi
rm -rf "$APP"

echo "The Ira companion is removed. Remove the Ira extension in chrome://extensions,"
echo "and check the Devices page: this Mac should show as gone."
