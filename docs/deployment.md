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
  `polly:SynthesizeSpeech`. botocore finds it automatically; no key on disk.
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
