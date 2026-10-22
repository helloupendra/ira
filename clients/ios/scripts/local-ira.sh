#!/bin/sh
# Start a local Ira for Ira for iPhone's tests: the demo model (no key, no
# network), fake speech-to-text and voice, on 127.0.0.1:$IRA_TEST_PORT (8799),
# with an owner, an action PIN, and an iPhone pairing code that pairs three
# devices with every iPhone skill on. It prints what the tests read:
#
#     IRA_TEST_SERVER=http://localhost:8799
#     IRA_TEST_PAIRING=ABCD-EFGH
#     IRA_UITEST_LINK=http://localhost:8799/pair#code=ABCD-EFGH
#
# and leaves the server running; its folder holds ira.pid and serve.log.
# The account and PIN are made up here and live only in that folder.
set -eu
port=${IRA_TEST_PORT:-8799}
dir=${IRA_TEST_DIR:-$(mktemp -d)}
ira=${IRA:-ira}
mkdir -p "$dir"
cd "$dir"
cat > ira.yaml <<EOF
data_dir: ./data
channels:
  http:
    host: 127.0.0.1
    port: $port
voice:
  stt:
    type: fake
  tts:
    type: fake
EOF
email=owner@example.com
printf 'local-test-password-1\n' | "$ira" --config ira.yaml setup --email "$email" >/dev/null
printf '4321\n' | "$ira" --config ira.yaml pin set >/dev/null
code=$("$ira" --config ira.yaml device code --email "$email" --kind ios --days 1 --uses 3 \
    --label "Test iPhone" --skills contacts,calendar,reminders,location,calls \
    | sed -n 's/^Pairing code for .*: \([A-Z0-9-]*\)$/\1/p')
[ -n "$code" ] || { echo "no pairing code" >&2; exit 1; }
nohup "$ira" --config ira.yaml serve >serve.log 2>&1 &
echo $! >ira.pid
for _ in $(seq 1 60); do
    if curl -sf "http://127.0.0.1:$port/healthz" >/dev/null; then break; fi
    sleep 0.5
done
curl -sf "http://127.0.0.1:$port/healthz" >/dev/null || { cat serve.log >&2; exit 1; }
echo "IRA_TEST_SERVER=http://localhost:$port"
echo "IRA_TEST_PAIRING=$code"
echo "IRA_UITEST_LINK=http://localhost:$port/pair#code=$code"
echo "IRA_TEST_DIR=$dir"
