#!/usr/bin/env bash
# Add one business: its folder, its IRA instance on its own port, and the lines
# to give it a hostname through the Cloudflare tunnel.
#
#   sudo ira-add-business clinic 8811 clinic.example.com
#
# Optional, in the environment:
#   IRA_BUSINESS  one line about the business (default: the business name)
#   IRA_NAME      the assistant's name (default: Ira)
#
# It runs `ira init --provider bedrock` as the ira user in /srv/ira/<business>,
# enables and starts ira@<business>, and prints the cloudflared ingress lines,
# the one-time setup link from the journal, and what to do next.
# Installed by bootstrap.sh as /usr/local/sbin/ira-add-business.

set -euo pipefail

IRA=/opt/ira/app/.venv/bin/ira
SRV=/srv/ira

die() {
    printf 'add-business: %s\n' "$*" >&2
    exit 1
}

if [ $# -lt 2 ] || [ $# -gt 3 ]; then
    echo "usage: $0 <business> <port> [hostname]" >&2
    exit 2
fi
business=$1
port=$2
hostname=${3:-}

[[ $business =~ ^[a-z0-9][a-z0-9-]{0,30}$ ]] ||
    die "the business name must be lowercase letters, digits and dashes, e.g. sunrise-dental"
if ! [[ $port =~ ^[0-9]{4,5}$ ]] || [ "$port" -lt 1024 ] || [ "$port" -gt 65535 ]; then
    die "the port must be a number from 1024 to 65535"
fi
if [ -n "$hostname" ]; then
    [[ $hostname =~ ^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+$ ]] ||
        die "'$hostname' is not a hostname, e.g. clinic.example.com"
fi
[ "$(id -u)" -eq 0 ] || die "run it as root: sudo $0 $*"
[ -x "$IRA" ] || die "$IRA is missing: run bootstrap.sh first"
id ira >/dev/null 2>&1 || die "there is no ira user: run bootstrap.sh first"

folder="$SRV/$business"
[ ! -e "$folder" ] || die "$folder already exists"
if grep -qsE "^[[:space:]]+port:[[:space:]]*$port([[:space:]]|$)" "$SRV"/*/ira.yaml; then
    die "port $port is already in another business's ira.yaml"
fi
if ss -Hltn "sport = :$port" | grep -q .; then
    die "something already listens on port $port"
fi

echo "==> $folder"
install -d -o ira -g ira -m 750 "$folder"
args=(init "$folder" --provider bedrock --port "$port"
    --business "${IRA_BUSINESS:-$business}" --name "${IRA_NAME:-Ira}")
if [ -n "$hostname" ]; then
    args+=(--public-url "https://$hostname")
fi
(cd "$folder" && runuser -u ira -- "$IRA" "${args[@]}" >/dev/null) || {
    rmdir "$folder" 2>/dev/null || true
    die "ira init failed"
}

echo "==> ira@$business"
since="$(date '+%Y-%m-%d %H:%M:%S')"
systemctl enable --now "ira@$business" || {
    journalctl -u "ira@$business" --since "$since" -n 40 --no-pager >&2 || true
    die "ira@$business did not start; its log is above"
}

link=""
for _ in $(seq 1 30); do
    link="$(journalctl -u "ira@$business" --since "$since" -o cat --no-pager 2>/dev/null |
        grep -oE 'https?://[^ ]+#code=[0-9A-F-]+' | tail -n 1 || true)"
    [ -n "$link" ] && break
    if ! systemctl is-active --quiet "ira@$business"; then
        journalctl -u "ira@$business" --since "$since" -n 40 --no-pager >&2 || true
        die "ira@$business did not start; its log is above"
    fi
    sleep 1
done

cat <<EOF

Business $business: /srv/ira/$business, port $port, running as ira@$business.
EOF
if [ -n "$hostname" ]; then
    cat <<EOF

1. Give it its hostname. Add these lines to /etc/cloudflared/config.yml, under
   "ingress:" and before the final "- service: http_status:404":

  - hostname: $hostname
    service: http://127.0.0.1:$port

   then point the name at the tunnel (as the user who ran
   "cloudflared tunnel login") and restart the tunnel:

     cloudflared tunnel route dns <tunnel-name> $hostname
     sudo systemctl restart cloudflared
EOF
else
    cat <<EOF

1. No hostname given: it is reachable only from this server, at
   http://127.0.0.1:$port (for example through an SSH tunnel).
EOF
fi
cat <<EOF

2. Create the owner account and the action PIN with this one-time link:

     ${link:-(not in the journal yet: journalctl -u ira@$business | grep code=)}

3. Check everything, models and voice included:

     sudo -u ira ira doctor /srv/ira/$business

4. Replace /srv/ira/$business/tools.py with this business's own tools, then:

     sudo systemctl restart ira@$business
EOF
