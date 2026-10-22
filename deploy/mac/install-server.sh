#!/bin/bash
# Run an IRA folder all day on this Mac, under your own account. Safe to run again.
#
#   deploy/mac/install-server.sh FOLDER [--aws-profile NAME] [--ref REF]
#   deploy/mac/install-server.sh FOLDER --remove
#
# FOLDER is one made by `ira init` (it has ira.yaml). The script:
#   - installs IRA from GitHub (REF: a tag, a branch or a commit; default main) into
#     FOLDER/.venv, with the aws and ogg extras: its own copy, outside ~/Documents;
#   - writes ~/Library/LaunchAgents/in.ira.server.<folder name>.plist, which starts
#     `ira serve` at login and again if it stops, logging to FOLDER/logs/ira.log;
#   - with --aws-profile, sets AWS_PROFILE for it, so Bedrock and Polly calls are
#     signed by that profile in ~/.aws (no key in FOLDER).
#
# macOS does not let launchd processes read ~/Documents, ~/Desktop or ~/Downloads,
# so FOLDER must be somewhere else, for example ~/ira-personal.
set -euo pipefail

REPO="${IRA_REPO:-https://github.com/helloupendra/ira.git}"
REF="main"
PROFILE=""
REMOVE=0
FOLDER=""

while [ $# -gt 0 ]; do
    case "$1" in
        --aws-profile) PROFILE="${2:?--aws-profile needs a name}"; shift 2 ;;
        --ref) REF="${2:?--ref needs a tag, branch or commit}"; shift 2 ;;
        --remove) REMOVE=1; shift ;;
        -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
        -*) echo "Unknown option: $1" >&2; exit 2 ;;
        *) FOLDER="$1"; shift ;;
    esac
done

fail() { printf 'Error: %s\n' "$*" >&2; exit 1; }

[ -n "$FOLDER" ] || fail "say which folder: install-server.sh FOLDER"
[ -d "$FOLDER" ] || fail "$FOLDER is not a folder (make one with: ira init FOLDER)"
FOLDER="$(cd "$FOLDER" && pwd -P)"
NAME="$(basename "$FOLDER" | tr -c 'A-Za-z0-9-\n' '-')"
LABEL="in.ira.server.$NAME"
AGENT="$HOME/Library/LaunchAgents/$LABEL.plist"

if [ "$REMOVE" = 1 ]; then
    if [ -z "${IRA_MAC_NO_AGENT:-}" ]; then
        launchctl bootout "gui/$(id -u)" "$AGENT" 2>/dev/null || true
    fi
    rm -f "$AGENT"
    echo "Stopped and removed $LABEL. The folder $FOLDER is untouched."
    exit 0
fi

[ -f "$FOLDER/ira.yaml" ] || fail "$FOLDER has no ira.yaml (make one with: ira init FOLDER)"
for protected in Documents Desktop Downloads; do
    case "$FOLDER/" in
        "$HOME/$protected/"*) fail "launchd cannot read ~/$protected: move the folder, e.g. to ~/$(basename "$FOLDER")" ;;
    esac
done

PYTHON=""
for candidate in "${IRA_PYTHON:-}" /opt/homebrew/bin/python3 /usr/local/bin/python3 \
    /Library/Frameworks/Python.framework/Versions/Current/bin/python3; do
    [ -n "$candidate" ] && [ -x "$candidate" ] || continue
    if "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
        PYTHON="$candidate"
        break
    fi
done
[ -n "$PYTHON" ] || fail "IRA needs Python 3.11 or newer (for example: brew install python@3.12)"

mkdir -p "$FOLDER/logs"
chmod 700 "$FOLDER/logs"
if [ ! -x "$FOLDER/.venv/bin/python" ]; then
    "$PYTHON" -m venv "$FOLDER/.venv"
fi
if [ -z "${IRA_NO_PIP:-}" ]; then
    echo "Installing IRA ($REF) into $FOLDER/.venv"
    "$FOLDER/.venv/bin/python" -m pip install --quiet --disable-pip-version-check --upgrade \
        "ira-assistant[aws,ogg] @ git+$REPO@$REF"
fi

xml() { "$PYTHON" -c 'import sys; from xml.sax.saxutils import escape; print(escape(sys.argv[1]))' "$1"; }
ENVIRONMENT="<key>PATH</key><string>/usr/bin:/bin:/usr/sbin:/sbin</string>"
if [ -n "$PROFILE" ]; then
    ENVIRONMENT="$ENVIRONMENT<key>AWS_PROFILE</key><string>$(xml "$PROFILE")</string>"
fi
mkdir -p "$(dirname "$AGENT")"
cat > "$AGENT" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$(xml "$FOLDER/.venv/bin/ira")</string>
    <string>serve</string>
  </array>
  <key>WorkingDirectory</key><string>$(xml "$FOLDER")</string>
  <key>EnvironmentVariables</key>
  <dict>$ENVIRONMENT</dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>ProcessType</key><string>Background</string>
  <key>StandardOutPath</key><string>$(xml "$FOLDER/logs/ira.log")</string>
  <key>StandardErrorPath</key><string>$(xml "$FOLDER/logs/ira.log")</string>
</dict>
</plist>
PLIST

if [ -z "${IRA_MAC_NO_AGENT:-}" ]; then
    launchctl bootout "gui/$(id -u)" "$AGENT" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$AGENT"
fi

cat <<NEXT

$LABEL runs $FOLDER and starts again at login.
  Its log:      $FOLDER/logs/ira.log
  Restart it:   launchctl kickstart -k gui/\$(id -u)/$LABEL
  Stop it:      $0 $FOLDER --remove

While no account exists, the log shows a one-time setup link:
  grep 'code=' "$FOLDER/logs/ira.log"
NEXT
