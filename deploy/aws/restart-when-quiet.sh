#!/usr/bin/env bash
# Restart one Ira instance once no live call is open on it, so a deploy cuts nobody off.
# The server keeps the count in <data>/live-calls.json. After the wait limit it restarts
# anyway; a restart closes calls with 1001 and the apps call again.
#
#   sudo ira-restart-when-quiet <name> [minutes to wait, default 10]
set -euo pipefail

name="${1:?usage: ira-restart-when-quiet <name> [minutes]}"
minutes="${2:-10}"
case "$name" in *[!a-z0-9-]*) echo "a name is lowercase letters, digits and -" >&2; exit 2 ;; esac
file="/srv/ira/$name/data/live-calls.json"
deadline=$(( $(date +%s) + minutes * 60 ))

open_calls() {
    [ -f "$file" ] || { echo 0; return; }
    python3 -c 'import json, sys; print(int(json.load(open(sys.argv[1])).get("open", 0)))' \
        "$file" 2>/dev/null || echo 0
}

while :; do
    open="$(open_calls)"
    [ "$open" -eq 0 ] && break
    if [ "$(date +%s)" -ge "$deadline" ]; then
        echo "Still $open live call(s) on $name after $minutes minutes: restarting anyway."
        break
    fi
    echo "$open live call(s) open on $name: waiting..."
    sleep 15
done
systemctl restart "ira@$name"
echo "Restarted ira@$name."
