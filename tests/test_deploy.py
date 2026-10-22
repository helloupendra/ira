"""The AWS deployment files keep their safety settings, and the scripts stay valid bash."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

AWS = Path(__file__).resolve().parent.parent / "deploy" / "aws"
SCRIPTS = sorted(AWS.glob("*.sh"))


def unit(path: Path) -> dict[str, list[str]]:
    """A systemd unit as {Section.Key: [values]}; a key may repeat."""
    out: dict[str, list[str]] = {}
    section = ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            section = line.strip("[]")
            continue
        key, _, value = line.partition("=")
        out.setdefault(f"{section}.{key}", []).append(value)
    return out


def test_the_service_template_runs_one_business_unprivileged():
    service = unit(AWS / "ira@.service")
    expected = {
        "Service.User": "ira",
        "Service.WorkingDirectory": "/srv/ira/%i",
        "Service.ExecStart": "/opt/ira/app/.venv/bin/ira serve",
        "Service.Restart": "on-failure",
        "Service.TimeoutStopSec": "15",
        "Service.EnvironmentFile": "-/srv/ira/%i/.env",
        "Service.MemoryMax": "400M",
        "Service.CPUQuota": "50%",
        "Install.WantedBy": "multi-user.target",
    }
    for key, value in expected.items():
        assert service.get(key) == [value], key


def test_the_service_template_is_hardened():
    service = unit(AWS / "ira@.service")
    for key, value in {
        "NoNewPrivileges": "true",
        "ProtectSystem": "strict",
        "ReadWritePaths": "/srv/ira/%i",
        "ProtectHome": "true",
        "PrivateTmp": "true",
        # The other businesses' folders are hidden, not just read-only.
        "TemporaryFileSystem": "/srv/ira:ro",
        "BindPaths": "/srv/ira/%i",
    }.items():
        assert service.get(f"Service.{key}") == [value], key


def test_the_hardening_leaves_the_instance_role_reachable():
    # botocore reads the role's credentials from the instance metadata service
    # over HTTP; nothing on disk. Anything that cuts IPv4 off would break it.
    service = unit(AWS / "ira@.service")
    for key in ("PrivateNetwork", "IPAddressDeny", "IPAddressAllow", "ReadOnlyPaths"):
        assert f"Service.{key}" not in service, key
    families = " ".join(service.get("Service.RestrictAddressFamilies", ["AF_INET"])).split()
    assert "AF_INET" in families


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_scripts_are_strict_executable_bash(script):
    text = script.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash\n")
    assert "\nset -euo pipefail\n" in text
    assert os.access(script, os.X_OK), f"chmod +x {script.name}"
    assert not re.search(r"curl[^\n|]*\|\s*(sudo\s+)?(ba)?sh", text), "no curl | sh"


def test_bootstrap_installs_from_the_public_repository():
    text = (AWS / "bootstrap.sh").read_text(encoding="utf-8")
    assert 'IRA_REPO="${IRA_REPO:-https://github.com/helloupendra/ira.git}"' in text
    assert "ira-assistant[aws,ogg,connectors] @ git+${IRA_REPO}@${IRA_REF}" in text
    assert "/opt/ira/app" in text and "/srv/ira" in text
    assert "useradd --system" in text and "--shell /usr/sbin/nologin ira" in text
    assert "/etc/systemd/system/ira@.service" in text
    # The tunnel is a separate, documented step: no install, no login here.
    assert "cloudflared" not in text.replace("does not install cloudflared", "")


def test_add_business_runs_init_as_the_ira_user():
    text = (AWS / "add-business.sh").read_text(encoding="utf-8")
    assert "runuser -u ira --" in text
    assert "--provider bedrock" in text
    assert 'systemctl enable --now "ira@$business"' in text
    assert "http_status:404" in text and "#code=" in text
    assert "[[ $business =~ ^[a-z0-9][a-z0-9-]{0,30}$ ]]" in text
    # One person's own assistant: ira init --personal, no placeholder tools.
    assert 'if [ "${1:-}" = "--personal" ]' in text and "args+=(--personal)" in text


def test_cloudflared_example_routes_two_businesses_then_404():
    config = yaml.safe_load((AWS / "cloudflared-config.example.yml").read_text(encoding="utf-8"))
    rules = config["ingress"]
    assert rules[-1] == {"service": "http_status:404"}
    hosts = [r["hostname"] for r in rules[:-1]]
    assert len(hosts) == 2 and len(set(hosts)) == 2
    assert all(h.endswith((".example.com", ".example.org")) for h in hosts)
    assert all(r["service"].startswith("http://127.0.0.1:") for r in rules[:-1])


def test_the_iam_policy_allows_only_chat_and_speech():
    policy = json.loads((AWS / "iam-policy.example.json").read_text(encoding="utf-8"))
    statements = policy["Statement"]
    assert all(s["Effect"] == "Allow" for s in statements)
    actions = {s["Action"] for s in statements}
    assert actions == {"bedrock-mantle:CreateInference", "polly:SynthesizeSpeech"}
    bedrock = next(s for s in statements if s["Action"].startswith("bedrock-mantle:"))
    assert bedrock["Resource"].startswith("arn:aws:bedrock-mantle:")
    assert bedrock["Resource"].endswith(":project/default")


def test_no_real_addresses_or_accounts():
    allowed_ips = {"127.0.0.1", "169.254.169.254"}
    for path in AWS.iterdir():
        text = path.read_text(encoding="utf-8")
        ips = set(re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", text))
        assert ips <= allowed_ips, (path.name, ips - allowed_ips)
        assert not re.search(r"\b\d{12}\b", text), f"{path.name}: an AWS account id?"
        for host in re.findall(r"\b[\w-]+(?:\.[\w-]+)*\.(?:com|org|net|io|in|dev)\b", text):
            assert host.endswith(("example.com", "example.org", "github.com")), (path.name, host)


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_scripts_parse(script):
    subprocess.run(["bash", "-n", str(script)], check=True)


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck is not installed")
def test_scripts_pass_shellcheck():
    subprocess.run(["shellcheck", *map(str, SCRIPTS)], check=True)


def test_a_restart_waits_for_live_calls():
    script = (AWS / "restart-when-quiet.sh").read_text(encoding="utf-8")
    assert script.startswith("#!/usr/bin/env bash") and "set -euo pipefail" in script
    assert "/srv/ira/$name/data/live-calls.json" in script
    assert 'systemctl restart "ira@$name"' in script
    assert "*[!a-z0-9-]*" in script  # a name cannot reach another path
    bootstrap = (AWS / "bootstrap.sh").read_text(encoding="utf-8")
    assert "/usr/local/sbin/ira-restart-when-quiet" in bootstrap
