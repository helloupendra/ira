# Deployment

IRA is one Python process and one data folder. A small VM or a spare machine
in the office is enough.

## Checklist

1. A dedicated user and a virtualenv. IRA is not on PyPI yet, so install it
   from GitHub with only the extras you use:
   `pip install "ira-assistant[aws,ogg] @ git+https://github.com/helloupendra/ira.git"`.
2. A config folder with `ira.yaml`, your tool modules, and a `.env` readable
   only by that user (`chmod 600 .env`).
3. `ira setup` and `ira pin set` as that user.
4. HTTPS in front (the browser mic requires a secure context).
5. A service manager to keep it running, and backups of `data_dir`.

`ira init <folder>` writes a new folder with a commented `ira.yaml`, a
placeholder `tools.py` and a README, and `ira doctor <folder>` checks one
before it goes live. On AWS, [AWS with Bedrock](#aws-with-bedrock) below does
all of this with scripts, for several businesses on one server.

## Bind locally, terminate TLS in a proxy

Keep the default `host: 127.0.0.1` and let a reverse proxy face the network.
With [Caddy](https://caddyserver.com) (automatic certificates):

```text
assistant.example.com {
    reverse_proxy 127.0.0.1:8765 {
        flush_interval -1        # pass server-sent events through unbuffered
    }
}
```

With nginx, pass the original host through (`proxy_set_header Host $host;`):
the API refuses a browser write whose `Origin` names a different host. Also
disable buffering for `/v1/ask/stream` (`proxy_buffering off;`);
IRA also sends `X-Accel-Buffering: no`.

Tell IRA the address people use, so the links it prints and sends (the
setup link, invitations) point there rather than at `127.0.0.1`:
`channels.http.public_url: https://assistant.example.com` in `ira.yaml`, or
`IRA_PUBLIC_URL=https://assistant.example.com` in the environment.

The proxy should pass the real client address if you rely on per-address
sign-in throttling (run uvicorn with `--proxy-headers` and
`--forwarded-allow-ips` set to the proxy's address).

## systemd

```ini
# /etc/systemd/system/ira.service
[Unit]
Description=IRA assistant
After=network-online.target

[Service]
User=ira
WorkingDirectory=/srv/ira
ExecStart=/srv/ira/.venv/bin/ira serve
Restart=on-failure
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/srv/ira/data
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now ira
journalctl -u ira -f            # the first-run setup code appears here
```

## Cloud credentials

- **Amazon Bedrock / Polly**: give the machine an IAM role (instance profile
  or task role) allowed to call the Mantle endpoint and
  `polly:SynthesizeSpeech` (the policy is in
  [The instance role](#2-the-instance-role)). botocore finds it
  automatically; no key on disk.
- **Other providers**: keys in `.env` or the service's environment, named by
  `api_key_env` in `ira.yaml`.

## Telegram behind a firewall

The bot uses long polling, so it needs outbound HTTPS to
`api.telegram.org` only. No inbound port or webhook is required.

## Upgrades

Stop the service, back up `data_dir`, upgrade the package, start it again.
The schema is created with `IF NOT EXISTS`, and columns added since an older
release are added in place on start-up. v0.x releases note any manual
migration in the changelog.

## On your own Mac, all day

A personal Ira can run on the Mac you use every day, until (or instead of) a
server. It answers while the Mac is awake; for answers around the clock, use a
server ([AWS with Bedrock](#aws-with-bedrock) below).

1. **A folder outside `~/Documents`, `~/Desktop` and `~/Downloads`**: macOS
   does not let background (launchd) processes read those.

    ```bash
    ira init ~/ira-personal --provider bedrock --port 8801 --business "my own work"
    ```

2. **AWS credentials for Bedrock and Polly**, if you use them. On a Mac there
   is no instance role, so create an IAM user for IRA alone, with only the
   permissions in
   [`deploy/aws/iam-policy.example.json`](https://github.com/helloupendra/ira/blob/main/deploy/aws/iam-policy.example.json),
   and keep its access key in a named profile, never in the folder:

    ```bash
    aws configure --profile ira        # or edit ~/.aws/credentials (chmod 600)
    ```

    - **Rotate the access key every 90 days**: create a second key, put it in
      the profile, check `AWS_PROFILE=ira ira doctor ~/ira-personal`, then
      delete the old key.
    - Set an **AWS Budgets** alert on the account, so an unexpected bill
      cannot grow quietly.
    - A key on a laptop is easier to lose than a role on a server: if the Mac
      is lost, deactivate the key in the IAM console first.

3. **Run it under launchd**, with the profile:

    ```bash
    deploy/mac/install-server.sh ~/ira-personal --aws-profile ira
    ```

    It installs IRA from GitHub into `~/ira-personal/.venv` (its own copy,
    outside `~/Documents`), and writes a LaunchAgent that starts `ira serve`
    at login and again if it stops, logging to `~/ira-personal/logs/ira.log`.
    Run it again to upgrade (`--ref v0.3.0` pins a release); `--remove`
    stops it and leaves the folder alone.

4. **Create the owner** with the one-time link in the log
   (`grep 'code=' ~/ira-personal/logs/ira.log`), then pair your Mac with
   [Ira for Mac](clients/macos.md).

## AWS with Bedrock

One small EC2 instance can host several businesses side by side. Each
business is its own IRA instance: its own folder under `/srv/ira`, its own
port on `127.0.0.1`, its own owner account and its own hostname. Amazon
Bedrock answers through its OpenAI-compatible Mantle endpoint and Amazon
Polly speaks, both signed by the instance's IAM role, so no key is stored on
the server. A Cloudflare named tunnel publishes each hostname over HTTPS; the
server accepts no inbound connection except SSH.

```text
browser --HTTPS--> Cloudflare --tunnel--> cloudflared --> 127.0.0.1:8811  ira@clinic  /srv/ira/clinic
                                                      \-> 127.0.0.1:8812  ira@shop    /srv/ira/shop

ira@clinic, ira@shop --SigV4, the instance role--> Bedrock Mantle (us-east-1), Polly (ap-south-1)
```

The files are in
[deploy/aws](https://github.com/helloupendra/ira/tree/main/deploy/aws):

| File | What it is |
| --- | --- |
| `bootstrap.sh` | Prepares the server. Run it again to upgrade. |
| `ira@.service` | The systemd template: `ira@clinic` runs `/srv/ira/clinic`. |
| `add-business.sh` | Adds one business. Installed as `ira-add-business`. |
| `restart-when-quiet.sh` | Restarts one business once no live call is open on it (10 minutes at most). Installed as `ira-restart-when-quiet`. |
| `cloudflared-config.example.yml` | Tunnel ingress for two businesses. |
| `iam-policy.example.json` | The instance role's permissions. |

### 1. Launch the instance

- **Image**: Ubuntu Server 24.04 LTS, arm64 (for example `t4g.small`, 2 GB)
  or x86_64 (`t3.small`). The scripts handle both.
- **Disk**: 20 GB gp3 is plenty; the data is SQLite files.
- **Instance metadata**: IMDSv2 only (token required). The default hop limit
  of 1 is enough, because IRA runs on the host, not in a container.
- **IAM role**: the instance profile from step 2.
- **Security group**: the one from step 3.
- **Key pair**: for SSH.

Each instance is capped at 400 MB of memory and half a CPU. In a test
container (arm64, Ubuntu 24.04), an idle instance with the Bedrock
configuration used about 55 MB.

### 2. The instance role

Create an IAM role for EC2 (trusted entity: AWS service, EC2) and give it
this policy, from `iam-policy.example.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BedrockMantleChatCompletions",
      "Effect": "Allow",
      "Action": "bedrock-mantle:CreateInference",
      "Resource": "arn:aws:bedrock-mantle:us-east-1:*:project/default"
    },
    {
      "Sid": "TranscribeStreaming",
      "Effect": "Allow",
      "Action": [
        "transcribe:StartStreamTranscription",
        "transcribe:StartStreamTranscriptionWebSocket"
      ],
      "Resource": "*",
      "Condition": { "StringEquals": { "aws:RequestedRegion": "ap-south-1" } }
    },
    {
      "Sid": "PollySynthesizeSpeech",
      "Effect": "Allow",
      "Action": "polly:SynthesizeSpeech",
      "Resource": "*",
      "Condition": { "StringEquals": { "aws:RequestedRegion": "ap-south-1" } }
    }
  ]
}
```

- **Bedrock**: inference on the `bedrock-mantle` endpoint authorizes
  `bedrock-mantle:CreateInference`, on a Mantle *project*. A request that
  names no project, as IRA's do, belongs to the account's default project,
  `arn:aws:bedrock-mantle:<region>:<account>:project/default`. The `*` in the
  account field saves editing the file; put your account id there to pin it.
  Use your Mantle region if it is not `us-east-1`. Sources:
  the [Service Authorization Reference for
  bedrock-mantle](https://docs.aws.amazon.com/service-authorization/latest/reference/list_bedrock-mantle.html)
  and the Bedrock user guide's [Projects](https://docs.aws.amazon.com/bedrock/latest/userguide/projects.html)
  page.
- **Polly**: `SynthesizeSpeech` has no resource to scope it to unless you
  use lexicons, so the policy limits it to the Polly region instead.
- **Not verified against a live account here.** If model calls fail with
  HTTP 403 under this policy, compare it with a role that already works, and
  please open an issue.
- `ira doctor` shows each model's result separately, so a model your account
  cannot use stands out.

### 3. The security group

- **Inbound**: SSH (TCP 22) from your own address only. Nothing else: no 80
  and no 443, because the tunnel connects outwards.
- **Outbound**: the default (all). The server reaches Bedrock, Polly,
  GitHub and the Ubuntu mirrors, and cloudflared reaches Cloudflare on port
  7844.

### 4. Bootstrap

Git is on Ubuntu's server image. Clone the repository and run the script as
root:

```bash
git clone --depth 1 https://github.com/helloupendra/ira.git
sudo ira/deploy/aws/bootstrap.sh
```

`IRA_REF` picks what to install: a tag, a branch or a commit. It defaults to
the newest `v*` tag, or `main` while there is none. To pin a release, clone
the same tag so the scripts match the code:

```bash
git clone --depth 1 --branch v0.3.0 https://github.com/helloupendra/ira.git
sudo IRA_REF=v0.3.0 ira/deploy/aws/bootstrap.sh
```

What it leaves on the server:

| Path | What it is |
| --- | --- |
| `/opt/ira/app/.venv` | IRA with the `aws` and `ogg` extras, owned by root: the service cannot change its own code |
| `/opt/ira/app/INSTALLED` | The ref and commit installed, and when |
| `/usr/local/bin/ira` | The `ira` command |
| `/usr/local/sbin/ira-add-business` | Adds a business (step 5) |
| `/etc/systemd/system/ira@.service` | The systemd template |
| `/srv/ira` | The business folders (`root:ira`, mode 750) |
| `/var/backups/ira` | Backups (step 8), owned by `ira` |

It does not install cloudflared, open a port or start an instance. It is
safe to run again. `IRA_REPO` points it at a fork.

### 5. Add a business

```bash
sudo IRA_BUSINESS="Sunrise Dental, a small clinic" ira-add-business clinic 8811 clinic.example.com
```

- `clinic` names the folder (`/srv/ira/clinic`) and the service
  (`ira@clinic`): lowercase letters, digits and dashes.
- `8811` is its port on `127.0.0.1`, one per business.
- `clinic.example.com` is where people open it. It becomes `public_url`, so
  the links IRA prints and sends point there. Leave it out for an instance
  only reachable from the server (through an SSH tunnel, say).
- `IRA_BUSINESS` is one line about the business for the model, and
  `IRA_NAME` the assistant's name (default Ira). Both can be edited later in
  `ira.yaml`.
- `--personal` (first) makes one person's own assistant instead:
  `sudo ira-add-business --personal riley 8812 ira.example.com`. It has no
  placeholder tools, since the person's paired devices and search add their
  tools, and a `search:` section for news feeds; a Brave Search key goes in
  its `.env`.

It runs `ira init --provider bedrock` as the `ira` user, enables and starts
`ira@clinic`, and prints the cloudflared ingress lines, the one-time setup
link from the journal, and the next steps. The new `ira.yaml` uses:

| | Models |
| --- | --- |
| `default` tier, in fallback order | `moonshotai.kimi-k2.5`, `zai.glm-5`, `deepseek.v3.2` |
| `fast` tier | `openai.gpt-oss-120b`, `mistral.mistral-large-3-675b-instruct` |
| Speech-to-text | Amazon Transcribe streaming in `ap-south-1`, Hindi then Indian English |
| Text-to-speech | Polly in `ap-south-1`, voice Kajal, neural, `en-IN` |

These are the Bedrock ids that answered on 11 Oct 2026. Bedrock adds and
retires models, and `ira doctor` asks each one a tiny question. If one is
refused with "isn't supported on this route", it is served under
`/openai/v1` on Mantle: give it a second provider with
`base_url: https://bedrock-mantle.us-east-1.api.aws/openai/v1`.

**Speech-to-text.** `ira init --provider bedrock` writes Amazon Transcribe
streaming in `ap-south-1` (Hindi first, then Indian English), which the role
above allows. It has run live calls since 23 Oct 2026; see
[Real-time voice](realtime.md#measured) and
[Hindi, English and Hinglish](language.md). Voxtral through `chat_audio`
does not work on Mantle today: on 22 Oct 2026 it refused audio ("Model does
not support audio modality").

Each instance runs as `ira` in a hardened unit:

- the file system is read-only except its own folder, and the other
  businesses' folders, their data and their `.env`, are not visible at all;
- 400 MB of memory and half a CPU at most;
- a private `/tmp`, no `/home`, no new privileges, a system-call filter;
- the network stays on: Bedrock and Polly need it, and botocore fetches the
  role's short-lived credentials from the instance metadata service over
  HTTP and keeps them in memory. Nothing about them is written to disk.

Day to day:

```bash
sudo systemctl status ira@clinic
sudo journalctl -u ira@clinic -f
sudo -u ira -e /srv/ira/clinic/tools.py      # edit as the ira user
sudo systemctl restart ira@clinic            # after changing ira.yaml or tools.py
sudo -u ira ira doctor /srv/ira/clinic       # --no-models: no calls, no cost
```

A key for a provider other than the instance role goes in
`/srv/ira/clinic/.env`, owned by `ira` and `chmod 600`.

### 6. The Cloudflare tunnel

This needs a domain whose DNS is on Cloudflare. Once per server, as your
admin user (not root):

```bash
# cloudflared from Cloudflare's package repository
sudo mkdir -p --mode=0755 /usr/share/keyrings
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
  | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' \
  | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt-get update && sudo apt-get install cloudflared

cloudflared tunnel login          # prints a link: open it, pick the domain; writes ~/.cloudflared/cert.pem
cloudflared tunnel create ira     # writes ~/.cloudflared/<TUNNEL-ID>.json
```

Then the configuration, from `cloudflared-config.example.yml`: set `tunnel`,
point `credentials-file` at the copied JSON, and keep one ingress rule per
business with `http_status:404` last.

```bash
sudo install -d -m 755 /etc/cloudflared
sudo install -m 600 ~/.cloudflared/<TUNNEL-ID>.json /etc/cloudflared/
sudo cp ira/deploy/aws/cloudflared-config.example.yml /etc/cloudflared/config.yml
sudo nano /etc/cloudflared/config.yml

cloudflared tunnel route dns ira clinic.example.com     # a CNAME to the tunnel
sudo cloudflared --config /etc/cloudflared/config.yml service install
```

For each later business, add its two ingress lines (`ira-add-business`
prints them), route its hostname, and `sudo systemctl restart cloudflared`.

- Cloudflare serves HTTPS, which the browser's microphone requires.
- Devices (Ira for Mac, the Android app) connect to
  `wss://<hostname>/v1/devices/ws` through the same tunnel: cloudflared
  passes WebSockets through with no extra setting. Cloudflare closes a
  WebSocket idle for 100 seconds; both sides ping every 30, and a device
  reconnects by itself after a tunnel restart. The pairing link carries the
  server's address, from `public_url`, so set the hostname before pairing.
- IRA refuses a browser write whose `Origin` names another host than the
  `Host` (or `X-Forwarded-Host`) it receives. cloudflared normally forwards
  the public hostname. If the app or the console answers 403 "cross-origin
  request refused" once you are signed in, add
  `originRequest: { httpHostHeader: clinic.example.com }` to that business's
  ingress rule.

### 7. Set up with the one-time code

Open the setup link `ira-add-business` printed. If you lost it:

```bash
sudo journalctl -u ira@clinic | grep 'code='
```

The link opens the console's setup wizard with the code filled in: the
owner's email and password, the assistant's name and voice, the providers
(Bedrock needs no key here), the owner's action PIN, and channels. The code
rides after `#`, so the browser never sends it to Cloudflare or to IRA's
logs. It works once, for 24 hours, and survives restarts (`ira setup
--new-code` replaces it). Then check everything:

```bash
sudo -u ira ira doctor /srv/ira/clinic
```

```text
IRA doctor: /srv/ira/clinic/ira.yaml

  ok    config             parses: Ira for Sunrise Dental, a small clinic
  ok    data dir           /srv/ira/clinic/data is writable
  ok    port               127.0.0.1:8811 is held by this instance (IRA 0.2.0 named 'Ira')
  ok    tools              ./tools.py: find_notes (read), add_note (action)
  ok    model default 1/3  bedrock:moonshotai.kimi-k2.5  answered in ...
  ...
  ok    owner              owner@example.com has an action PIN
  ok    public url         links point at https://clinic.example.com
```

It exits non-zero when anything fails, so it also fits a deploy script.

### 8. Backups

Each business's state is its `data/` folder: `ira.db` (accounts,
conversations, actions, the audit and call logs) and whatever its tools keep.
SQLite's `.backup` takes a consistent copy while the instance runs, which
copying the files does not. As root (`sudo -i`):

```bash
day=$(date +%F)
for db in /srv/ira/*/data/*.db; do
    business=$(basename "$(dirname "$(dirname "$db")")")
    sudo -u ira sqlite3 "$db" ".backup /var/backups/ira/$business-$(basename "$db" .db)-$day.db"
done
find /var/backups/ira -name '*.db' -mtime +14 -delete     # keep two weeks
```

Put those lines in `/etc/cron.daily/ira-backup` (`chmod 755`, starting with
`#!/bin/bash`) to run them every night. Copy `/var/backups/ira` off the
server too: only root and `ira` can read it, so pull it from another machine
with `rsync --rsync-path='sudo rsync'`. Keep each folder's `ira.yaml`,
`tools.py` and `.env` with it. The backups hold conversations and customer
details: treat them as confidential.

To restore one business:

```bash
sudo systemctl stop ira@clinic
sudo rm -f /srv/ira/clinic/data/ira.db-wal /srv/ira/clinic/data/ira.db-shm
sudo -u ira cp /var/backups/ira/clinic-ira-2026-10-12.db /srv/ira/clinic/data/ira.db
sudo systemctl start ira@clinic
```

### 9. Upgrades

Back up first. Then take the scripts of the new release, run the bootstrap
with its ref, and restart each instance once nobody is on a live call with
it (the server keeps the count in `data/live-calls.json`, and sets it to
none when it starts, so a crash leaves no stale count; a restart closes
calls and devices with "going away", and the apps reconnect at once):

```bash
rm -rf ira && git clone --depth 1 --branch v0.3.0 https://github.com/helloupendra/ira.git
sudo IRA_REF=v0.3.0 ira/deploy/aws/bootstrap.sh
sudo ira-restart-when-quiet clinic            # waits for open calls, 10 minutes at most
sudo -u ira ira doctor /srv/ira/clinic
```

The bootstrap reinstalls IRA even when the version number is unchanged, and
lists the instances still running the old code. `/opt/ira/app/INSTALLED`
says which ref and commit is installed; to go back, run the bootstrap with
the previous ref and restore the backup if the release changed the database.
