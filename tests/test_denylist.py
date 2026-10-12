"""The pre-commit hooks that keep private strings and addresses out of git."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DENYLIST = ROOT / "scripts" / "check_denylist.py"
SECRET = "Acme-Internal-Project-Falcon"


def run(args: list[str], denylist: Path | None, cwd: Path) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "IRA_DENYLIST"}
    env["IRA_DENYLIST"] = str(denylist) if denylist else str(cwd / "does-not-exist.txt")
    return subprocess.run(
        [sys.executable, str(DENYLIST), *args], cwd=cwd, env=env, capture_output=True, text=True
    )


def write_list(tmp_path: Path) -> Path:
    path = tmp_path / "denylist.txt"
    path.write_text(
        f"# private words, one per line\n\n{SECRET}\nre:acct[-_ ]?\\d{{6}}\nre:([unclosed\n",
        encoding="utf-8",
    )
    return path


def test_blocks_a_literal_match_case_insensitively_without_printing_it(tmp_path):
    denylist = write_list(tmp_path)
    staged = tmp_path / "notes.md"
    staged.write_text("line one\nmeeting about acme-internal-project-falcon\n", encoding="utf-8")

    result = run([str(staged)], denylist, tmp_path)

    assert result.returncode == 1
    assert f"{staged}:2:" in result.stdout
    assert "entry #3" in result.stdout
    output = result.stdout + result.stderr
    assert SECRET.lower() not in output.lower()  # never echoed in full
    assert re.search(r"'ac\*+on'", result.stdout)  # masked preview


def test_regex_entries_match(tmp_path):
    denylist = write_list(tmp_path)
    staged = tmp_path / "config.py"
    staged.write_text("ACCOUNT = 'ACCT-123456'\n", encoding="utf-8")

    result = run([str(staged)], denylist, tmp_path)

    assert result.returncode == 1
    assert "123456" not in result.stdout


def test_bad_regex_is_reported_by_line_number_only(tmp_path):
    denylist = write_list(tmp_path)
    clean = tmp_path / "clean.txt"
    clean.write_text("nothing to see\n", encoding="utf-8")

    result = run([str(clean)], denylist, tmp_path)

    assert result.returncode == 0
    assert "line 5 is not a valid regex" in result.stderr
    assert "unclosed" not in result.stderr


def test_missing_denylist_warns_but_does_not_block(tmp_path):
    staged = tmp_path / "a.txt"
    staged.write_text(SECRET, encoding="utf-8")

    result = run([str(staged)], None, tmp_path)

    assert result.returncode == 0
    assert "WARNING no deny-list" in result.stderr


def test_all_mode_scans_tracked_files(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "tracked.txt").write_text(f"x {SECRET} y\n", encoding="utf-8")
    (tmp_path / "untracked.txt").write_text(f"{SECRET}\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True)
    denylist = write_list(tmp_path)

    result = run(["--all"], denylist, tmp_path)

    assert result.returncode == 1
    assert "tracked.txt:1:" in result.stdout
    assert "untracked.txt" not in result.stdout


def test_identity_check_requires_a_noreply_address_and_respects_the_denylist():
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        from check_identity import problems
    finally:
        sys.path.pop(0)
    patterns = [(1, re.compile("private-corp", re.IGNORECASE))]

    good = {"author": "123+someone@users.noreply.github.com"}
    assert problems(good, patterns) == []

    work = {"author": "me@private-corp.example"}
    found = problems(work, patterns)
    assert any("not a GitHub no-reply address" in p for p in found)
    assert any("deny-list entry #1" in p for p in found)
    assert all("private-corp" not in p for p in found)

    assert problems({"author": ""}, patterns) == ["author email is not set"]
