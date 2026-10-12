"""`ira doctor`, run against fakes: no network, no keys, no cloud."""

from __future__ import annotations

import os
import socket
from pathlib import Path

import pytest

from ira import doctor
from ira.accounts import Accounts
from ira.cli import main
from ira.config import ConfigError, load_settings
from ira.doctor import DoctorOptions, PortState, probe_port, run
from ira.models.base import ChatResponse, ProviderError
from ira.scaffold import BEDROCK_DEFAULT_CHAIN, BEDROCK_FAST_CHAIN, InitOptions, init_folder
from ira.store import Store
from ira.tools.actions import ActionGuard
from ira.tools.registry import ToolRegistry
from ira.voice.providers import FakeSTT, FakeTTS

from .conftest import FAST_PIN_ITERATIONS

PASSWORD = "correct-horse-battery"  # pragma: allowlist secret
FREE = PortState("free")


@pytest.fixture(autouse=True)
def no_network(monkeypatch, isolated_tools):
    """Any attempt to open a connection or resolve a name fails the test."""

    def refuse(*args, **kwargs):
        raise AssertionError("doctor tests must not touch the network")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_PROFILE", "IRA_PUBLIC_URL"):
        monkeypatch.delenv(name, raising=False)


class ByModel:
    """A chat provider whose answer depends on the model: text, or an exception."""

    def __init__(self, answers: dict[str, object]) -> None:
        self.answers = answers
        self.asked: list[str] = []

    async def chat(self, model, messages, tools, *, max_tokens, timeout):
        self.asked.append(model)
        answer = self.answers.get(model, "ready")
        if isinstance(answer, BaseException):
            raise answer
        return ChatResponse(text=str(answer))

    def stream(self, *args, **kwargs):  # pragma: no cover - doctor never streams
        raise NotImplementedError


def make_folder(tmp_path: Path, **options) -> Path:
    folder = tmp_path / "biz"
    init_folder(folder, InitOptions(**options))
    return folder / "ira.yaml"


def add_owner(config: Path, *, pin: bool = True) -> None:
    store = Store(load_settings(config).db_path)
    owner = Accounts(store).create_first_owner("owner@example.com", PASSWORD)
    if pin:
        ActionGuard(store, ToolRegistry(), pin_iterations=FAST_PIN_ITERATIONS).set_pin(
            "2468", user_id=owner.id
        )
    store.close()


def lines(report) -> dict[str, list[tuple[str, str]]]:
    out: dict[str, list[tuple[str, str]]] = {}
    for check in report.checks:
        out.setdefault(check.what, []).append((check.status, check.detail))
    return out


def statuses(report, what: str) -> list[str]:
    return [status for status, _ in lines(report).get(what, [])]


def test_a_ready_demo_folder_passes(tmp_path):
    config = make_folder(tmp_path)
    add_owner(config)
    report = run(config, port_probe=lambda host, port: FREE)
    assert report.failed == 0, report.text()
    seen = lines(report)
    assert seen["config"] == [("ok", "parses: Ira for your business")]
    assert seen["tools"] == [("ok", "./tools.py: find_notes (read), add_note (action)")]
    assert statuses(report, "model default 1/1") == ["ok"]
    assert statuses(report, "speech-to-text") == ["ok"]
    assert statuses(report, "text-to-speech") == ["skip"]
    assert seen["owner"] == [("ok", "owner@example.com has an action PIN")]
    assert statuses(report, "public url") == ["skip"]
    assert report.text().endswith("All good.")


def test_each_bedrock_model_is_asked_once(tmp_path):
    config = make_folder(tmp_path, provider="bedrock", public_url="https://ira.example.com")
    add_owner(config)
    bedrock = ByModel(
        {
            "zai.glm-5": ProviderError("bedrock: HTTP 403: not allowed", kind="auth", status=403),
            "mistral.mistral-large-3": ProviderError("bedrock: busy", kind="capacity"),
        }
    )
    stt, tts = FakeSTT(""), FakeTTS("Kajal")
    report = run(
        config,
        providers={"bedrock": bedrock},
        stt=stt,
        tts=tts,
        port_probe=lambda host, port: FREE,
    )
    assert sorted(bedrock.asked) == sorted(BEDROCK_DEFAULT_CHAIN + BEDROCK_FAST_CHAIN)
    seen = lines(report)
    status, detail = seen["model default 2/3"][0]
    assert status == "fail" and "bedrock:zai.glm-5" in detail and "auth" in detail
    assert "HTTP 403" in detail
    assert seen["model fast 2/2"][0][0] == "fail" and "capacity" in seen["model fast 2/2"][0][1]
    for what in ("model default 1/3", "model default 3/3", "model fast 1/2"):
        assert seen[what][0][0] == "ok" and "answered in" in seen[what][0][1]
    assert stt.received and stt.received[0][:4] == b"RIFF"  # a real WAV
    assert tts.spoken == ["Ready."]
    assert seen["speech-to-text"][0][0] == "ok" and "heard nothing" in seen["speech-to-text"][0][1]
    assert seen["text-to-speech"][0][0] == "ok"
    assert seen["public url"] == [("ok", "links point at https://ira.example.com")]
    assert report.failed == 2
    assert "2 failed." in report.text()


def test_no_models_builds_and_calls_nothing(tmp_path, monkeypatch):
    config = make_folder(tmp_path, provider="bedrock")
    add_owner(config)

    def never(*args, **kwargs):
        raise AssertionError("--no-models must not build a provider")

    monkeypatch.setattr(doctor, "_build_providers", never)
    report = run(config, DoctorOptions(models=False), port_probe=lambda host, port: FREE)
    seen = lines(report)
    assert seen["models"] == [("skip", "5 models not called (--no-models)")]
    assert statuses(report, "voice") == ["skip"]
    assert report.failed == 0, report.text()


def test_a_provider_that_cannot_be_built_fails_its_models(tmp_path, monkeypatch):
    config = make_folder(tmp_path, provider="bedrock")
    add_owner(config)

    def no_key(name, cfg):
        raise ConfigError(f"provider '{name}' needs the environment variable EXAMPLE_KEY")

    monkeypatch.setattr("ira.runtime.build_http", no_key)
    report = run(config, tts=FakeTTS(), port_probe=lambda host, port: FREE)
    models = [c for c in report.checks if c.what.startswith("model ")]
    assert len(models) == 5 and all(c.status == "fail" for c in models)
    assert all("EXAMPLE_KEY" in c.detail for c in models)
    assert statuses(report, "speech-to-text") == ["fail"]  # it rides on the same provider
    assert statuses(report, "text-to-speech") == ["ok"]


def test_a_config_that_does_not_parse_stops_early(tmp_path):
    config = tmp_path / "ira.yaml"
    config.write_text("assistant:\n  nmae: typo\n", encoding="utf-8")
    report = run(config, port_probe=lambda host, port: FREE)
    assert [c.what for c in report.checks] == ["config"]
    assert report.checks[0].status == "fail" and "nmae" in report.checks[0].detail


def test_model_references_are_checked(tmp_path):
    config = tmp_path / "ira.yaml"
    config.write_text(
        "models:\n"
        "  providers: {demo: {type: fake}}\n"
        "  tiers: {default: [demo:router, nowhere:model, bare]}\n"
        "voice:\n"
        "  stt: {type: chat_audio, provider: missing, model: x}\n",
        encoding="utf-8",
    )
    report = run(config, DoctorOptions(models=False), port_probe=lambda host, port: FREE)
    problems = [d for s, d in lines(report)["config"] if s == "fail"]
    assert any("unknown provider 'nowhere'" in p for p in problems)
    assert any("'bare'" in p for p in problems)
    assert any("voice.stt.provider 'missing'" in p for p in problems)


def test_a_broken_tool_module_is_named(tmp_path):
    config = make_folder(tmp_path)
    (config.parent / "tools.py").write_text("import nothing_called_this\n", encoding="utf-8")
    (config.parent / "empty.py").write_text("X = 1\n", encoding="utf-8")
    text = config.read_text(encoding="utf-8").replace(
        "  - ./tools.py\n", "  - ./tools.py\n  - ./empty.py\n"
    )
    config.write_text(text, encoding="utf-8")
    report = run(config, DoctorOptions(models=False), port_probe=lambda host, port: FREE)
    tools = lines(report)["tools"]
    assert tools[0][0] == "fail" and "ModuleNotFoundError" in tools[0][1]
    assert tools[1] == ("warn", "./empty.py: imports, but registers no tools")


@pytest.mark.skipif(not hasattr(os, "geteuid") or os.geteuid() == 0, reason="root can write")
def test_a_data_folder_that_cannot_be_written(tmp_path):
    config = make_folder(tmp_path)
    data = config.parent / "data"
    data.mkdir()
    data.chmod(0o500)
    try:
        report = run(config, DoctorOptions(models=False), port_probe=lambda host, port: FREE)
    finally:
        data.chmod(0o700)
    assert statuses(report, "data dir") == ["fail"]


def test_doctor_creates_no_files(tmp_path):
    config = make_folder(tmp_path)
    before = sorted(p.name for p in config.parent.iterdir())
    report = run(config, DoctorOptions(models=False), port_probe=lambda host, port: FREE)
    assert lines(report)["data dir"][0][0] == "ok"
    after = sorted(p.name for p in config.parent.iterdir() if p.name != "__pycache__")
    assert after == before and not (config.parent / "data").exists()


@pytest.mark.parametrize(
    ("state", "status", "words"),
    [
        (PortState("free"), "ok", "is free"),
        (PortState("other"), "fail", "not IRA"),
        (PortState("unavailable", error="Permission denied"), "fail", "Permission denied"),
        (PortState("ira", "Ira", "0.2.0", setup_required=False), "ok", "this instance"),
        (PortState("ira", "Someone", "0.2.0", setup_required=False), "warn", "own port"),
        (PortState("ira", "Ira", "0.2.0", setup_required=True), "warn", "own port"),
    ],
)
def test_port_states(tmp_path, state, status, words):
    config = make_folder(tmp_path)
    add_owner(config)
    report = run(config, DoctorOptions(models=False), port_probe=lambda host, port: state)
    [(seen_status, detail)] = lines(report)["port"]
    assert seen_status == status and words in detail


def test_probe_port_binds_but_never_connects():
    with socket.socket() as holder:
        holder.bind(("127.0.0.1", 0))
        port = holder.getsockname()[1]
        holder.listen()
        asked = []

        def who(host, port):
            asked.append((host, port))
            return PortState("other")

        assert probe_port("127.0.0.1", port, identify=who).state == "other"
        assert asked == [("127.0.0.1", port)]
    assert probe_port("127.0.0.1", port, identify=who).state == "free"


def test_owner_and_pin(tmp_path):
    config = make_folder(tmp_path)
    report = run(config, DoctorOptions(models=False), port_probe=lambda host, port: FREE)
    assert "no database yet" in lines(report)["owner"][0][1]

    Store(load_settings(config).db_path).close()
    report = run(config, DoctorOptions(models=False), port_probe=lambda host, port: FREE)
    assert "no owner account yet" in lines(report)["owner"][0][1]

    add_owner(config, pin=False)
    report = run(config, DoctorOptions(models=False), port_probe=lambda host, port: FREE)
    status, detail = lines(report)["owner"][0]
    assert status == "fail" and "has no action PIN" in detail


@pytest.mark.parametrize(
    ("init", "options", "status"),
    [
        ({}, DoctorOptions(models=False, public=True), "fail"),
        ({"public_url": "https://ira.example.com"}, DoctorOptions(models=False), "ok"),
        ({"public_url": "http://ira.example.com"}, DoctorOptions(models=False), "warn"),
        ({"public_url": "http://127.0.0.1:8765"}, DoctorOptions(models=False), "ok"),
    ],
)
def test_public_url(tmp_path, init, options, status):
    config = make_folder(tmp_path, **init)
    report = run(config, options, port_probe=lambda host, port: FREE)
    assert statuses(report, "public url") == [status]


def test_listening_on_every_address_counts_as_public(tmp_path):
    config = make_folder(tmp_path)
    config.write_text(
        config.read_text(encoding="utf-8").replace("host: 127.0.0.1", "host: 0.0.0.0"),
        encoding="utf-8",
    )
    report = run(config, DoctorOptions(models=False), port_probe=lambda host, port: FREE)
    status, detail = lines(report)["public url"][0]
    assert status == "fail" and "0.0.0.0" in detail


@pytest.mark.skipif(not hasattr(os, "geteuid") or os.geteuid() == 0, reason="needs a non-root")
def test_root_will_not_check_someone_elses_folder(tmp_path, monkeypatch):
    config = make_folder(tmp_path)
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    report = run(config, port_probe=lambda host, port: FREE)
    assert [c.what for c in report.checks] == ["user"]
    assert report.failed == 1 and "sudo -u" in report.checks[0].detail


def test_cli(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(doctor, "probe_port", lambda host, port: FREE)
    config = make_folder(tmp_path)
    assert main(["doctor", str(config.parent), "--no-models"]) == 1  # no owner yet
    out = capsys.readouterr().out
    assert out.startswith(f"IRA doctor: {config.resolve()}") and "FAIL  owner" in out

    add_owner(config)
    assert main(["doctor", str(config.parent)]) == 0
    assert "All good." in capsys.readouterr().out
    assert main(["--config", str(config), "doctor", "--no-models"]) == 0
    capsys.readouterr()

    assert main(["doctor", str(tmp_path / "nowhere")]) == 1
    assert "no ira.yaml" in capsys.readouterr().err
