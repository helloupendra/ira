"""install.sh and uninstall.sh: strict bash, and a dry run in a throwaway home folder."""

from __future__ import annotations

import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
SCRIPTS = [HERE / "install.sh", HERE / "uninstall.sh"]
EXTENSION_ID = "lidenefpfghfkmlcddnbjmladjhobdhp"


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_scripts_are_strict_executable_bash(script):
    text = script.read_text(encoding="utf-8")
    assert text.startswith("#!/bin/bash\n")
    assert "set -euo pipefail" in text or "set -uo pipefail" in text
    assert os.access(script, os.X_OK)
    subprocess.run(["bash", "-n", str(script)], check=True)


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck is not installed")
def test_scripts_pass_shellcheck():
    subprocess.run(["shellcheck", *map(str, SCRIPTS)], check=True)


def test_the_installer_pins_the_extension_id_of_the_manifest():
    manifest = json.loads((HERE.parent / "chrome-extension" / "manifest.json").read_text())
    import base64
    import hashlib

    digest = hashlib.sha256(base64.b64decode(manifest["key"])).hexdigest()[:32]
    derived = "".join(chr(ord("a") + int(c, 16)) for c in digest)
    assert derived == EXTENSION_ID
    assert f'EXTENSION_ID="{EXTENSION_ID}"' in (HERE / "install.sh").read_text()


@pytest.mark.skipif(sys.platform != "darwin", reason="the installer is for macOS")
def test_a_dry_run_installs_and_uninstalls_in_place():
    home = Path(tempfile.mkdtemp(prefix="iram-home"))
    env = {
        **os.environ,
        "HOME": str(home),
        "IRA_MAC_NO_PIP": "1",
        "IRA_MAC_NO_PAIR": "1",
        "IRA_MAC_NO_AGENT": "1",
    }
    try:
        for _ in range(2):  # safe to run again
            subprocess.run([str(HERE / "install.sh")], env=env, check=True, capture_output=True)
        app = home / "Library" / "Application Support" / "ira-mac"
        assert not (app / "server.txt").exists()  # a checkout's installer knows no server
        given = ["--server", "https://ira.example.com"]
        subprocess.run([str(HERE / "install.sh"), *given], env=env, check=True, capture_output=True)
        assert (app / "server.txt").read_text() == "https://ira.example.com\n"
        assert (app / "app" / "ira_mac" / "daemon.py").is_file()
        assert (app / "chrome-extension" / "manifest.json").is_file()
        assert not (app / "chrome-extension" / "test").exists()
        assert oct(app.stat().st_mode & 0o777) == "0o700"
        hosts = home / "Library" / "Application Support" / "Google" / "Chrome"
        host = json.loads((hosts / "NativeMessagingHosts" / "in.ira.mac.json").read_text())
        assert host["allowed_origins"] == [f"chrome-extension://{EXTENSION_ID}/"]
        assert host["path"] == str(app / "ira-chrome-host") and host["type"] == "stdio"
        agent = plistlib.loads(
            (home / "Library" / "LaunchAgents" / "in.ira.mac.plist").read_bytes()
        )
        assert agent["Label"] == "in.ira.mac" and agent["KeepAlive"] is True
        assert agent["ProgramArguments"][1:] == ["-m", "ira_mac", "run"]
        assert "Documents" not in json.dumps(agent)  # launchd may not read ~/Documents
        relay = subprocess.run([host["path"]], input=b"", capture_output=True, timeout=30)
        assert relay.returncode == 0 and relay.stdout == b""
        for _ in range(2):
            subprocess.run([str(HERE / "uninstall.sh")], env=env, check=True, capture_output=True)
        assert not app.exists()
        assert not (home / "Library" / "LaunchAgents" / "in.ira.mac.plist").exists()
    finally:
        shutil.rmtree(home, ignore_errors=True)
