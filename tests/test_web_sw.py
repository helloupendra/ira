"""The web app's service worker (plain JavaScript, no build step), run in Node with a browser's
parts stubbed: offline, a versioned script is the script, never the app's page."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node")
def test_the_service_worker_works_offline():
    script = Path(__file__).parent / "web_sw_scenarios.js"
    result = subprocess.run(
        ["node", str(script)], capture_output=True, text=True, timeout=60, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
