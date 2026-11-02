"""The web call client (plain JavaScript, no build step), run in Node with a browser's parts
stubbed: words stop Ira, not sounds; a pause stays in the sentence."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node")
def test_the_web_call_stays_steady():
    script = Path(__file__).parent / "web_call_scenarios.js"
    result = subprocess.run(
        ["node", str(script)], capture_output=True, text=True, timeout=60, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
