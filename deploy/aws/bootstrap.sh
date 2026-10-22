#!/usr/bin/env bash
# Prepare an Ubuntu 24.04 server (arm64 or x86_64) to run IRA, one instance per
# business. Safe to run again: with a new IRA_REF it upgrades the shared install.
#
#   sudo ./bootstrap.sh                   the newest release tag, or main
#   sudo IRA_REF=v0.3.0 ./bootstrap.sh    a tag, branch or commit
#
# What it does:
#   - installs Python 3, venv, git and build tools (and libsndfile if needed);
#   - creates the system user `ira`;
#   - installs ira-assistant[aws,ogg] from IRA_REPO at IRA_REF into
#     /opt/ira/app/.venv, owned by root so the service cannot change its code;
#   - creates /srv/ira for the business folders, and /var/backups/ira;
#   - installs the ira@.service systemd template and `ira-add-business`.
#
# It does not install cloudflared, open a port or start any instance. Add a
# business with `sudo ira-add-business <business> <port> [hostname]`, or one person's own
# assistant with `sudo ira-add-business --personal <name> <port> [hostname]`.
# See docs/deployment.md, "AWS with Bedrock".

set -euo pipefail

IRA_REPO="${IRA_REPO:-https://github.com/helloupendra/ira.git}"
IRA_REF="${IRA_REF:-}"
APP=/opt/ira/app
VENV="$APP/.venv"
SRV=/srv/ira
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

say() { printf '\n==> %s\n' "$*"; }
die() {
    printf 'bootstrap: %s\n' "$*" >&2
    exit 1
}

[ "$(id -u)" -eq 0 ] || die "run it as root: sudo $0"
for file in ira@.service add-business.sh; do
    [ -f "$HERE/$file" ] || die "$file must sit next to this script (run it from a clone of the repository)"
done

# shellcheck source=/dev/null
. /etc/os-release
[ "${ID:-}" = ubuntu ] || die "this script is for Ubuntu; this is ${ID:-unknown}"
if [ "${VERSION_ID:-}" != "24.04" ]; then
    printf 'bootstrap: written for Ubuntu 24.04; this is %s. Going on.\n' "${VERSION_ID:-unknown}" >&2
fi
case "$(uname -m)" in
    aarch64 | arm64 | x86_64) ;;
    *) die "unsupported architecture $(uname -m)" ;;
esac

say "Packages: python3, venv, git, build tools"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q --no-install-recommends \
    python3 python3-venv python3-dev build-essential git ca-certificates sqlite3

say "System user ira"
if id ira >/dev/null 2>&1; then
    echo "ira exists"
else
    useradd --system --user-group --home-dir /opt/ira --no-create-home \
        --shell /usr/sbin/nologin ira
    echo "created ira"
fi

install -d -o root -g root -m 755 /opt/ira "$APP"
install -d -o root -g ira -m 750 "$SRV"
install -d -o ira -g ira -m 750 /var/backups/ira

if [ -z "$IRA_REF" ]; then
    IRA_REF="$(git ls-remote --tags --refs --sort=-version:refname "$IRA_REPO" 'refs/tags/v*' |
        awk 'NR == 1 { sub(".*refs/tags/", ""); print }')"
    IRA_REF="${IRA_REF:-main}"
fi

say "IRA from $IRA_REPO at $IRA_REF"
if [ ! -x "$VENV/bin/python" ]; then
    python3 -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install --quiet --upgrade pip
# --force-reinstall --no-deps: the same version number at another commit is still
# reinstalled. The second command then adds or upgrades the dependencies.
"$VENV/bin/python" -m pip install --quiet --no-cache-dir --force-reinstall --no-deps \
    "ira-assistant @ git+${IRA_REPO}@${IRA_REF}"
"$VENV/bin/python" -m pip install --quiet --no-cache-dir \
    "ira-assistant[aws,ogg] @ git+${IRA_REPO}@${IRA_REF}"

# soundfile ships its own libsndfile on most platforms; if this one cannot load
# it, use the system's (Telegram voice notes are OGG/Opus).
if ! "$VENV/bin/python" -c 'import soundfile' >/dev/null 2>&1; then
    say "soundfile needs the system libsndfile: installing libsndfile1"
    apt-get install -y -q --no-install-recommends libsndfile1
    "$VENV/bin/python" -c 'import soundfile' || die "soundfile still does not load"
fi

installed="$("$VENV/bin/python" - <<'PY'
import json
from importlib import metadata

dist = metadata.distribution("ira-assistant")
commit = json.loads(dist.read_text("direct_url.json") or "{}").get("vcs_info", {}).get("commit_id", "")
print(dist.version, commit[:12])
PY
)"
printf 'ref=%s\nversion+commit=%s\ninstalled=%s\n' "$IRA_REF" "$installed" "$(date -u +%FT%TZ)" \
    >"$APP/INSTALLED"
ln -sfn "$VENV/bin/ira" /usr/local/bin/ira

say "systemd template ira@.service and ira-add-business"
install -m 644 "$HERE/ira@.service" /etc/systemd/system/ira@.service
install -m 755 "$HERE/add-business.sh" /usr/local/sbin/ira-add-business
systemctl daemon-reload

mapfile -t running < <(systemctl list-units --type=service --state=running --no-legend \
    --plain 'ira@*' | awk '{ print $1 }')

say "Done: ira $installed (ref $IRA_REF)"
if [ "${#running[@]}" -gt 0 ]; then
    echo "Running instances use the old code until they restart:"
    printf '    %s\n' "${running[@]}"
    echo "Restart them with:  sudo systemctl restart 'ira@*'"
else
    echo "Next: sudo ira-add-business [--personal] <name> <port> [hostname]"
fi
