#!/usr/bin/env python3
"""Refuse to commit under a private email address.

Every commit in a public repository publishes its author and committer email.
This hook passes only when both are a GitHub no-reply address
(``...@users.noreply.github.com``) and neither matches the private deny-list
used by ``check_denylist.py``.

It reads the effective identity (``git var``), so an address set through
``GIT_AUTHOR_EMAIL`` or ``GIT_COMMITTER_EMAIL`` is checked too, not just
``git config user.email``.

Set the identity for this repository with:

    git config user.email "<id>+<username>@users.noreply.github.com"
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_denylist import denylist_path, load_patterns, mask  # noqa: E402

NOREPLY_SUFFIX = "@users.noreply.github.com"
IDENT = re.compile(r"^(?P<name>.*?) <(?P<email>[^>]*)>")


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def ident_email(var: str) -> str:
    match = IDENT.match(git("var", var))
    return match.group("email") if match else ""


def problems(emails: dict[str, str], patterns: list[tuple[int, re.Pattern[str]]]) -> list[str]:
    found: list[str] = []
    for role, email in emails.items():
        if not email:
            found.append(f"{role} email is not set")
            continue
        if not email.lower().endswith(NOREPLY_SUFFIX):
            found.append(f"{role} email '{mask(email)}' is not a GitHub no-reply address")
        for list_line, pattern in patterns:
            if pattern.search(email):
                found.append(f"{role} email matches deny-list entry #{list_line}")
    return found


def main() -> int:
    emails = {
        "config user.email": git("config", "user.email"),
        "author": ident_email("GIT_AUTHOR_IDENT"),
        "committer": ident_email("GIT_COMMITTER_IDENT"),
    }
    path = denylist_path()
    patterns = load_patterns(path) if path.is_file() else []
    found = problems(emails, patterns)
    if found:
        for line in found:
            print(f"identity: {line}", file=sys.stderr)
        print(
            "identity: set a no-reply address with "
            '`git config user.email "<id>+<username>@users.noreply.github.com"`',
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
