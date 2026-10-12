#!/usr/bin/env python3
"""Fail when a file contains a string from a private deny-list.

The deny-list lives OUTSIDE the repository, so the list itself can never be
committed. Its path is ``$IRA_DENYLIST``, or ``~/.config/ira/denylist.txt``.

File format, one entry per line:

    # comments start with '#'
    my-company-internal.example
    re:acct[-_ ]?\\d{6}

Plain lines are literals; lines starting with ``re:`` are regular expressions.
Matching is case-insensitive. A missing deny-list is a warning, not an error,
so contributors without one can still commit.

Usage:
    check_denylist.py FILE...    # what pre-commit runs on staged files
    check_denylist.py --all      # every file tracked by git

Matches are reported as ``file:line`` with a masked preview; the matched text
is never printed in full, because CI logs and terminals are not private.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

DEFAULT_PATH = "~/.config/ira/denylist.txt"
MAX_BYTES = 5 * 1024 * 1024


def denylist_path() -> Path:
    return Path(os.environ.get("IRA_DENYLIST") or DEFAULT_PATH).expanduser()


def load_patterns(path: Path) -> list[tuple[int, re.Pattern[str]]]:
    """Return (line number, compiled pattern) pairs. Bad regexes are skipped with a warning."""
    patterns: list[tuple[int, re.Pattern[str]]] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        entry = raw.strip()
        if not entry or entry.startswith("#"):
            continue
        if entry.startswith("re:"):
            source = entry[3:].strip()
            if not source:
                continue
            try:
                patterns.append((number, re.compile(source, re.IGNORECASE)))
            except re.error as exc:
                # Name the line, not the pattern: the pattern may itself be private.
                print(
                    f"deny-list: line {number} is not a valid regex ({exc.msg}); skipped",
                    file=sys.stderr,
                )
        else:
            patterns.append((number, re.compile(re.escape(entry), re.IGNORECASE)))
    return patterns


def mask(text: str) -> str:
    """A preview that proves which text matched without repeating it."""
    text = text.replace("\n", " ")
    if len(text) <= 4:
        return text[:1] + "*" * (len(text) - 1)
    if len(text) <= 8:
        return text[:1] + "*" * (len(text) - 2) + text[-1:]
    return text[:2] + "*" * (len(text) - 4) + text[-2:]


def scan_text(text: str, patterns: list[tuple[int, re.Pattern[str]]]) -> list[tuple[int, int, str]]:
    """Return (file line, deny-list line, masked match) for every hit."""
    hits: list[tuple[int, int, str]] = []
    for list_line, pattern in patterns:
        for match in pattern.finditer(text):
            if not match.group(0):
                continue
            file_line = text.count("\n", 0, match.start()) + 1
            hits.append((file_line, list_line, mask(match.group(0))))
    return sorted(hits)


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], check=True, capture_output=True, text=True
    ).stdout
    return [name for name in out.split("\0") if name]


def scan_files(names: Iterable[str], patterns: list[tuple[int, re.Pattern[str]]]) -> int:
    found = 0
    for name in names:
        path = Path(name)
        if not path.is_file():
            continue
        if path.stat().st_size > MAX_BYTES:
            print(f"deny-list: {name} is larger than 5 MB; not scanned", file=sys.stderr)
            continue
        # Binary files are scanned too: names and IDs hide in metadata.
        text = path.read_bytes().decode("utf-8", errors="replace")
        for file_line, list_line, preview in scan_text(text, patterns):
            print(f"{name}:{file_line}: deny-list entry #{list_line} matched '{preview}'")
            found += 1
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="*", help="files to scan")
    parser.add_argument("--all", action="store_true", help="scan every file tracked by git")
    args = parser.parse_args(argv)

    path = denylist_path()
    if not path.is_file():
        print(
            f"deny-list: WARNING no deny-list at {path}; private strings are NOT being checked. "
            "Create it (one literal or 're:regex' per line) or set IRA_DENYLIST.",
            file=sys.stderr,
        )
        return 0

    patterns = load_patterns(path)
    if not patterns:
        print(f"deny-list: WARNING {path} has no entries", file=sys.stderr)
        return 0

    names = tracked_files() if args.all else args.files
    found = scan_files(names, patterns)
    if found:
        print(
            f"deny-list: {found} match(es). Remove the private text before committing.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
