"""`ira init`: a new business folder from the packaged templates."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ira.cli import main
from ira.config import load_settings
from ira.models.fake import RouterProvider
from ira.runtime import build_runtime
from ira.scaffold import (
    BEDROCK_DEFAULT_CHAIN,
    BEDROCK_FAST_CHAIN,
    BEDROCK_REGION,
    BEDROCK_STT_MODEL,
    POLLY_REGION,
    POLLY_VOICE,
    InitError,
    InitOptions,
    init_folder,
    render,
)
from ira.store import Store
from ira.tools.loader import import_tool_module
from ira.tools.registry import ToolContext, ToolError

from .conftest import make_runtime

REPO = Path(__file__).resolve().parent.parent
WRITTEN = {"ira.yaml", "tools.py", "README.md", ".gitignore"}


def test_demo_folder_runs_with_no_key(tmp_path, isolated_tools):
    folder = tmp_path / "shop"
    written = init_folder(folder, InitOptions(business="Example Shop, a hardware store"))
    assert {p.name for p in written} == WRITTEN == {p.name for p in folder.iterdir()}

    settings = load_settings(folder / "ira.yaml")
    assert settings.data_dir == (folder / "data").resolve()
    assert settings.assistant.business == "Example Shop, a hardware store"
    assert settings.models.tiers == {"default": ["demo:router"]}
    assert settings.voice.stt.type == "fake" and settings.voice.tts.type == "none"
    assert settings.channels.http.host == "127.0.0.1" and settings.channels.http.public_url is None

    runtime = build_runtime(settings, store=Store(":memory:"))
    assert {"find_notes", "add_note"} <= {t.name for t in runtime.registry}
    assert not (folder / "data").exists()  # nothing written until something is stored


def test_bedrock_folder_uses_the_tested_ids(tmp_path):
    folder = tmp_path / "clinic"
    init_folder(
        folder,
        InitOptions(
            name="Asha",
            business="Sunrise Dental, a small clinic",
            port=8811,
            provider="bedrock",
            public_url="https://clinic.example.com/",
        ),
    )
    settings = load_settings(folder / "ira.yaml")
    bedrock = settings.models.providers["bedrock"]
    assert bedrock.type == "bedrock_mantle" and bedrock.region == BEDROCK_REGION == "us-east-1"
    assert bedrock.api_key_env is None  # signed by the instance role, no key
    assert settings.models.tiers == {
        "default": [f"bedrock:{m}" for m in BEDROCK_DEFAULT_CHAIN],
        "fast": [f"bedrock:{m}" for m in BEDROCK_FAST_CHAIN],
    }
    assert settings.models.tiers["default"] == [
        "bedrock:moonshotai.kimi-k2.5",
        "bedrock:zai.glm-5",
        "bedrock:deepseek.v3.2",
    ]
    assert settings.models.tiers["fast"] == [
        "bedrock:openai.gpt-oss-120b",
        "bedrock:mistral.mistral-large-3-675b-instruct",
    ]
    stt, tts = settings.voice.stt, settings.voice.tts
    assert (stt.type, stt.provider, stt.model) == ("chat_audio", "bedrock", BEDROCK_STT_MODEL)
    assert stt.vocabulary == ["Asha"]
    assert (tts.type, tts.voice, tts.engine, tts.language_code, tts.region) == (
        "polly",
        POLLY_VOICE,
        "neural",
        "en-IN",
        POLLY_REGION,
    )
    assert settings.channels.http.port == 8811
    assert settings.channels.http.public_url == "https://clinic.example.com"
    assert settings.assistant.name == "Asha"


def test_the_ids_agree_with_the_example_config():
    example = (REPO / "ira.example.yaml").read_text(encoding="utf-8")
    assert f"model: {BEDROCK_STT_MODEL}" in example
    assert "bedrock:openai.gpt-oss-120b" in example
    assert "openai.gpt-oss-120b" in BEDROCK_FAST_CHAIN


def test_region_and_voice_options(tmp_path):
    files = render(InitOptions(provider="bedrock", region="eu-west-1", voice="Joanna"))
    assert "region: eu-west-1" in files["ira.yaml"]
    assert "voice: Joanna" in files["ira.yaml"] and "language_code: en-US" in files["ira.yaml"]
    # A voice IRA does not list still works; the language is left to Polly.
    files = render(InitOptions(provider="bedrock", voice="Zeina"))
    assert "voice: Zeina" in files["ira.yaml"]
    assert re.search(r"^\s+language_code:", files["ira.yaml"], re.M) is None


def test_text_is_quoted_for_yaml(tmp_path):
    business = 'Shop: "Hardware" #1, नमस्ते & more'
    init_folder(tmp_path / "b", InitOptions(name="Ira: Two", business=business))
    settings = load_settings(tmp_path / "b" / "ira.yaml")
    assert settings.assistant.business == business
    assert settings.assistant.name == "Ira: Two"


@pytest.mark.parametrize(
    ("options", "message"),
    [
        (InitOptions(port=80), "--port"),
        (InitOptions(region="us-east-1"), "--region only applies"),
        (InitOptions(voice="Kajal"), "--voice only applies"),
        (InitOptions(provider="bedrock", region="mars"), "AWS region"),
        (InitOptions(provider="bedrock", voice="Kajal; rm"), "Polly voice"),
        (InitOptions(business="two\nlines"), "one line"),
        (InitOptions(name="  "), "cannot be empty"),
        (InitOptions(public_url="ira.example.com"), "--public-url"),
        (InitOptions(provider="openai"), "--provider"),
    ],
)
def test_bad_options_write_nothing(tmp_path, options, message):
    with pytest.raises(InitError, match=re.escape(message)):
        init_folder(tmp_path / "new", options)
    assert not (tmp_path / "new").exists()


def test_refuses_a_folder_that_is_not_empty(tmp_path):
    folder = tmp_path / "busy"
    folder.mkdir()
    (folder / "notes.txt").write_text("keep me", encoding="utf-8")
    with pytest.raises(InitError, match="not empty"):
        init_folder(folder, InitOptions())
    assert [p.name for p in folder.iterdir()] == ["notes.txt"]

    afile = tmp_path / "file"
    afile.write_text("", encoding="utf-8")
    with pytest.raises(InitError, match="not a folder"):
        init_folder(afile, InitOptions())


def test_an_empty_existing_folder_is_filled(tmp_path):
    folder = tmp_path / "empty"
    folder.mkdir()
    init_folder(folder, InitOptions(provider="bedrock"))
    assert {p.name for p in folder.iterdir()} == WRITTEN


SECRET_SHAPES = [
    r"AKIA[0-9A-Z]{16}",  # AWS access key id
    r"aws_secret_access_key",
    r"sk-[A-Za-z0-9]{10,}",
    r"\d{6,}:[A-Za-z0-9_-]{30,}",  # Telegram bot token
    r"BEGIN [A-Z ]*PRIVATE KEY",
    r"api_key\s*[:=]\s*\S",
]


@pytest.mark.parametrize("provider", ["demo", "bedrock"])
def test_no_secrets_are_written(tmp_path, provider):
    folder = tmp_path / provider
    init_folder(folder, InitOptions(provider=provider))
    assert not (folder / ".env").exists()
    for path in folder.iterdir():
        text = path.read_text(encoding="utf-8")
        for shape in SECRET_SHAPES:
            assert re.search(shape, text) is None, (path.name, shape)
    # The only *_env setting names a variable; it never holds a value.
    assert re.findall(r"^\s+(\w+_env): (\S+)", (folder / "ira.yaml").read_text(), re.M) == [
        ("token_env", "TELEGRAM_BOT_TOKEN")
    ]
    gitignore = (folder / ".gitignore").read_text(encoding="utf-8").split()
    assert {"data/", ".env"} <= set(gitignore)


def test_the_template_tools_work(tmp_path, isolated_tools):
    init_folder(tmp_path / "b", InitOptions())
    module = import_tool_module("./tools.py", tmp_path / "b")
    module.setup(ToolContext(data_dir=tmp_path / "data", config_dir=tmp_path / "b"))

    add_note = isolated_tools.get("add_note")
    find_notes = isolated_tools.get("find_notes")
    assert add_note.kind == "action" and find_notes.kind == "read"
    args = add_note.validate({"text": "  call the plumber  "})
    assert add_note.describe(args) == "Save the note: call the plumber"

    assert module.find_notes("plumber") == []
    saved = module.add_note("call the plumber")
    assert saved["saved"] == "call the plumber"
    found = module.find_notes("plumb")
    assert [n["text"] for n in found] == ["call the plumber"]
    with pytest.raises(ValueError):
        find_notes.validate({"text": "x"})

    fresh = import_tool_module("./tools.py", tmp_path / "b")
    fresh._db_path = None
    with pytest.raises(ToolError, match="not set up"):
        fresh.find_notes("plumber")


@pytest.mark.anyio
async def test_the_demo_router_finds_the_template_tools(tmp_path, isolated_tools):
    init_folder(tmp_path / "b", InitOptions())
    module = import_tool_module("./tools.py", tmp_path / "b")
    module.setup(ToolContext(data_dir=tmp_path / "data", config_dir=tmp_path / "b"))
    module.add_note("the delivery comes on Friday")
    runtime = make_runtime(provider=RouterProvider(), registry=isolated_tools)
    reply = await runtime.assistant.ask("find notes text=delivery", conversation_id="c1")
    assert "Friday" in reply.text


def test_cli_init(tmp_path, capsys):
    folder = tmp_path / "clinic"
    args = ["init", str(folder), "--provider", "bedrock", "--business", "A clinic"]
    assert main([*args, "--port", "8811", "--public-url", "https://c.example.com"]) == 0
    out = capsys.readouterr().out
    assert "Created" in out and "ira doctor" in out and "ira serve" in out
    assert load_settings(folder / "ira.yaml").channels.http.port == 8811

    assert main(args) == 1
    assert "not empty" in capsys.readouterr().err
    assert main(["init", str(tmp_path / "x"), "--voice", "Kajal"]) == 1
    assert "--provider bedrock" in capsys.readouterr().err
