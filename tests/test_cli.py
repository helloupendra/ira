"""The ira command, run in-process against a temporary config."""

from __future__ import annotations

import io
import sys

import pytest

from ira.cli import main

PASSWORD = "correct-horse-battery"  # pragma: allowlist secret


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "ira.yaml"
    path.write_text("data_dir: ./data\n", encoding="utf-8")
    return str(path)


def run(config: str, *args: str, stdin: str = "") -> int:
    # Piped stdin stands in for the terminal prompts (one line per secret).
    original = sys.stdin
    sys.stdin = io.StringIO(stdin)
    try:
        return main(["--config", config, *args])
    finally:
        sys.stdin = original


def test_setup_pin_users_and_tokens(config, capsys):
    assert run(config, "user", "add", "--email", "a@example.com", "--role", "staff") == 1
    assert run(config, "setup", "--email", "owner@example.com", stdin=PASSWORD + "\n") == 0
    assert run(config, "setup", "--email", "again@example.com", stdin=PASSWORD + "\n") == 1

    assert run(config, "pin", "set", stdin="12ab\n") == 1
    assert run(config, "pin", "set", stdin="4321\n") == 0

    assert run(config, "user", "add", "--email", "desk@example.com", "--role", "staff",
               stdin=PASSWORD + "\n") == 0  # fmt: skip
    capsys.readouterr()
    assert run(config, "user", "list") == 0
    listing = capsys.readouterr().out
    assert "owner@example.com" in listing and "desk@example.com" in listing and "staff" in listing

    assert run(config, "device", "code", "--email", "nobody@example.com") == 1
    assert run(config, "device", "code", "--email", "desk@example.com", "--days", "30") == 1
    capsys.readouterr()
    assert run(config, "device", "code", "--email", "desk@example.com", "--uses", "2") == 0
    printed = capsys.readouterr().out
    assert "for desk@example.com (android)" in printed and "/pair#code=" in printed
    assert "7 days, for 2 device(s)" in printed
    assert run(config, "device", "code", "--email", "desk@example.com", "--kind", "ios",
               "--skills", "contacts,location") == 0  # fmt: skip
    printed = capsys.readouterr().out
    assert "(ios)" in printed and "Skills on: contacts, location." in printed

    assert run(config, "token", "create", "--label", "phone") == 0
    token = capsys.readouterr().out.strip().splitlines()[-1]
    assert token.startswith("ira_t_")
    assert run(config, "token", "create", "--label", "x", "--user", "desk@example.com",
               "--scope", "admin.read") == 1  # fmt: skip
    capsys.readouterr()
    assert run(config, "token", "list") == 0
    assert token not in capsys.readouterr().out  # only ids and labels, never the value
    assert run(config, "token", "revoke", "phone") == 0
    assert run(config, "token", "revoke", "phone") == 1


def test_telegram_pair_prints_a_one_time_code(config, capsys):
    run(config, "setup", "--email", "owner@example.com", stdin=PASSWORD + "\n")
    capsys.readouterr()
    assert run(config, "telegram", "pair") == 0
    assert "/pair " in capsys.readouterr().out


def test_config_errors_are_reported_not_raised(tmp_path, capsys):
    bad = tmp_path / "ira.yaml"
    bad.write_text("assistant: [not, a, mapping]\n", encoding="utf-8")
    assert run(str(bad), "user", "list") == 2
    assert "Config error" in capsys.readouterr().err


def test_each_user_gets_their_own_pin(config, capsys):
    from ira.accounts import Accounts
    from ira.config import load_settings
    from ira.store import Store
    from ira.tools.actions import ActionGuard
    from ira.tools.registry import ToolRegistry

    run(config, "setup", "--email", "owner@example.com", stdin=PASSWORD + "\n")
    run(config, "user", "add", "--email", "desk@example.com", "--role", "staff",
        stdin=PASSWORD + "\n")  # fmt: skip
    assert run(config, "pin", "set", "--user", "desk@example.com", stdin="2468\n") == 0
    assert "desk@example.com" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="No user"):
        run(config, "pin", "set", "--user", "nobody@example.com", stdin="2468\n")

    store = Store(load_settings(config).db_path)
    accounts, guard = Accounts(store), ActionGuard(store, ToolRegistry())
    assert guard.has_pin(accounts.find_user("desk@example.com").id)
    assert not guard.has_pin(accounts.find_user("owner@example.com").id)
