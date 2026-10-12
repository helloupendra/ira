from __future__ import annotations

import os

import pytest

from ira.config import ConfigError, load_settings
from ira.runtime import build_runtime
from ira.store import Store
from ira.tools.registry import ToolRegistry


def test_defaults_run_the_no_key_demo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("IRA_CONFIG", raising=False)
    settings = load_settings()
    runtime = build_runtime(settings, registry=ToolRegistry(), store=Store(":memory:"))
    assert settings.models.tiers == {"default": ["demo:router"]}
    assert runtime.stt is None and runtime.tts is None


def test_relative_paths_resolve_against_the_config_file(tmp_path):
    (tmp_path / "ira.yaml").write_text("data_dir: ./state\n", encoding="utf-8")
    settings = load_settings(tmp_path / "ira.yaml")
    assert settings.data_dir == (tmp_path / "state").resolve()


def test_unknown_keys_are_rejected(tmp_path):
    (tmp_path / "ira.yaml").write_text("assistant:\n  nmae: typo\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="nmae"):
        load_settings(tmp_path / "ira.yaml")


def test_missing_secret_names_the_variable_not_a_value(tmp_path, monkeypatch):
    monkeypatch.delenv("IRA_TEST_KEY", raising=False)
    (tmp_path / "ira.yaml").write_text(
        "models:\n"
        "  providers:\n"
        "    p: {type: openai, api_key_env: IRA_TEST_KEY}\n"
        "  tiers:\n"
        "    default: [p:some-model]\n",
        encoding="utf-8",
    )
    settings = load_settings(tmp_path / "ira.yaml")
    with pytest.raises(ConfigError, match="IRA_TEST_KEY"):
        build_runtime(settings, registry=ToolRegistry(), store=Store(":memory:"))


def test_dotenv_never_overrides_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("IRA_TEST_ALREADY", "from-shell")
    monkeypatch.delenv("IRA_TEST_NEW", raising=False)
    (tmp_path / ".env").write_text(
        "IRA_TEST_ALREADY=from-file\nexport IRA_TEST_NEW='quoted value'\n", encoding="utf-8"
    )
    (tmp_path / "ira.yaml").write_text("{}\n", encoding="utf-8")
    load_settings(tmp_path / "ira.yaml")
    assert os.environ["IRA_TEST_ALREADY"] == "from-shell"
    assert os.environ["IRA_TEST_NEW"] == "quoted value"
    monkeypatch.delenv("IRA_TEST_NEW")


def test_example_configs_are_valid(monkeypatch):
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    load_settings(root / "ira.example.yaml")
