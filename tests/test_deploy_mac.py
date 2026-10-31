"""deploy/mac/install-server.sh: strict bash, refuses folders launchd cannot read."""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# A script for macOS servers; on Windows "bash" is WSL's launcher.
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="needs bash")

SCRIPT = Path(__file__).resolve().parent.parent / "deploy" / "mac" / "install-server.sh"


def test_the_script_is_strict_executable_bash():
    assert SCRIPT.read_text(encoding="utf-8").startswith("#!/bin/bash\n")
    assert "set -euo pipefail" in SCRIPT.read_text(encoding="utf-8")
    assert os.access(SCRIPT, os.X_OK)
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck is not installed")
def test_the_script_passes_shellcheck():
    subprocess.run(["shellcheck", str(SCRIPT)], check=True)


def run(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "HOME": str(home), "IRA_NO_PIP": "1", "IRA_MAC_NO_AGENT": "1"}
    env["IRA_PYTHON"] = sys.executable
    return subprocess.run(
        [str(SCRIPT), *args], env=env, capture_output=True, text=True, check=False
    )


def test_it_refuses_folders_launchd_cannot_read(tmp_path: Path):
    folder = tmp_path / "Documents" / "shop"
    folder.mkdir(parents=True)
    (folder / "ira.yaml").write_text("{}\n")
    result = run(tmp_path, str(folder))
    assert result.returncode == 1 and "launchd cannot read ~/Documents" in result.stderr
    assert run(tmp_path, str(tmp_path / "missing")).returncode == 1


def test_it_writes_a_launch_agent_with_the_profile(tmp_path: Path):
    folder = tmp_path / "ira-personal"
    folder.mkdir()
    (folder / "ira.yaml").write_text("{}\n")
    for _ in range(2):  # safe to run again
        result = run(tmp_path, str(folder), "--aws-profile", "ira")
        assert result.returncode == 0, result.stderr
    agent = tmp_path / "Library" / "LaunchAgents" / "in.ira.server.ira-personal.plist"
    data = plistlib.loads(agent.read_bytes())
    assert data["ProgramArguments"] == [str(folder.resolve() / ".venv" / "bin" / "ira"), "serve"]
    assert data["WorkingDirectory"] == str(folder.resolve())
    assert data["EnvironmentVariables"]["AWS_PROFILE"] == "ira"
    assert data["KeepAlive"] is True
    assert (folder / ".venv" / "bin" / "python").exists()
    assert run(tmp_path, str(folder), "--remove").returncode == 0
    assert not agent.exists()
