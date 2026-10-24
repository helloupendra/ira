"""``ira init``: a new business folder from the templates in ``ira/templates/business``.

One business is one IRA instance: its own folder with ``ira.yaml``, its tools
and its ``data/``. ``ira init`` writes the first three files and nothing else.
It never writes a secret: on AWS the instance role signs Bedrock and Polly
calls, and any other key belongs in a ``.env`` the owner creates.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from string import Template

import yaml

from ira.config import Settings, check_public_url
from ira.voice.voices import voices_for

PROVIDERS = ("demo", "bedrock")

# Amazon Bedrock ids for a new business folder: the ones that answered on
# 11 Oct 2026 through the Mantle endpoint in us-east-1. Bedrock adds and retires
# models, so `ira doctor` asks each model a tiny question and says which ones
# still answer. Change them here, and only here.
BEDROCK_REGION = "us-east-1"
BEDROCK_DEFAULT_CHAIN = ("moonshotai.kimi-k2.5", "zai.glm-5", "deepseek.v3.2")
BEDROCK_FAST_CHAIN = ("openai.gpt-oss-120b", "mistral.mistral-large-3-675b-instruct")
TRANSCRIBE_REGION = "ap-south-1"
POLLY_REGION = "ap-south-1"
POLLY_VOICE = "Kajal"
POLLY_ENGINE = "neural"

REGION_PATTERN = re.compile(r"[a-z]{2}(-[a-z]+)+-\d")
TEMPLATES = ("ira.yaml", "tools.py", "README.md", ".gitignore")


class InitError(ValueError):
    """The folder or an option cannot be used; the message says why."""


@dataclass(frozen=True)
class InitOptions:
    name: str = "Ira"
    business: str = "your business"
    port: int = 8765
    provider: str = "demo"
    region: str | None = None
    voice: str | None = None
    public_url: str | None = None
    # One person's own assistant: no placeholder tools (their devices and search
    # add tools), a search section, and wording about a person, not a business.
    personal: bool = False


PERSONAL_BUSINESS = "one person's own work and day"
BUSINESS_INSTRUCTIONS = """\
    Answer from the tools. When they do not have the answer, say so plainly
    rather than guessing. Keep answers short: they are often spoken."""
PERSONAL_INSTRUCTIONS = """\
    This is one person's own assistant. When they ask about their Mac, their
    browser tabs, the web or the news, use their devices and search. When a
    tool does not have the answer, say so plainly rather than guessing. Keep
    answers short: they are often spoken."""
BUSINESS_TOOLS = """\
# Tool modules, relative to this file. tools.py holds two examples to replace.
tools:
  - ./tools.py"""
PERSONAL_TOOLS = """\
# Tool modules, relative to this file. tools.py holds two examples, switched off:
# a personal assistant's tools come from the person's paired devices and search.
tools: []"""
PERSONAL_SEARCH = """
# Web and news search, which each person switches on for themselves (with their
# PIN) in the Ira app. web_search needs BRAVE_SEARCH_API_KEY in .env.
search:
  calls_per_hour: 30
  news:
    cache_minutes: 15
    feeds: []   # RSS or Atom: - { name: Example News, url: https://news.example.com/rss }"""


def _template(name: str) -> str:
    return (resources.files("ira") / "templates" / "business" / name).read_text(encoding="utf-8")


def _quoted(value: str) -> str:
    """A YAML double-quoted scalar. JSON's string syntax is a subset of it."""
    return json.dumps(value, ensure_ascii=False)


def _one_line(label: str, value: str, limit: int) -> str:
    value = value.strip()
    if not value:
        raise InitError(f"{label} cannot be empty")
    if "\n" in value or "\r" in value:
        raise InitError(f"{label} must be one line")
    if len(value) > limit:
        raise InitError(f"{label} is longer than {limit} characters")
    return value


def _chain(provider: str, models: tuple[str, ...]) -> str:
    return "\n".join(f"      - {provider}:{model}" for model in models)


def _polly_language(voice: str) -> str | None:
    for known in voices_for("polly"):
        if known.id == voice:
            return known.languages[0] if known.languages else None
    return None


def _provider_sections(options: InitOptions) -> str:
    if options.provider == "demo":
        return _template("models-demo.yaml.tmpl")
    voice = options.voice or POLLY_VOICE
    language = _polly_language(voice)
    language_line = (
        f"    language_code: {language}"
        if language
        else "    # language_code: en-IN       # set it if the voice speaks several languages"
    )
    return Template(_template("models-bedrock.yaml.tmpl")).substitute(
        region=options.region or BEDROCK_REGION,
        default_chain=_chain("bedrock", BEDROCK_DEFAULT_CHAIN),
        fast_chain=_chain("bedrock", BEDROCK_FAST_CHAIN),
        transcribe_region=TRANSCRIBE_REGION,
        voice=voice,
        engine=POLLY_ENGINE,
        language_line=language_line,
        polly_region=POLLY_REGION,
    )


def check_options(options: InitOptions) -> InitOptions:
    """Validate the options; returns them with text fields trimmed."""
    if options.provider not in PROVIDERS:
        raise InitError(f"--provider must be one of {', '.join(PROVIDERS)}")
    if options.provider != "bedrock":
        for flag, value in (("--region", options.region), ("--voice", options.voice)):
            if value:
                raise InitError(f"{flag} only applies with --provider bedrock")
    if not 1024 <= options.port <= 65535:
        raise InitError("--port must be between 1024 and 65535")
    if options.region and not REGION_PATTERN.fullmatch(options.region):
        raise InitError(f"--region '{options.region}' does not look like an AWS region")
    if options.voice and not re.fullmatch(r"[A-Za-z]{2,20}", options.voice):
        raise InitError(f"--voice '{options.voice}' does not look like a Polly voice id")
    try:
        public_url = check_public_url(options.public_url)
    except ValueError as exc:
        raise InitError(f"--public-url: {exc}") from None
    business = options.business
    if options.personal and business == InitOptions.business:
        business = PERSONAL_BUSINESS
    return InitOptions(
        name=_one_line("--name", options.name, 40),
        business=_one_line("--business", business, 200),
        port=options.port,
        provider=options.provider,
        region=options.region,
        voice=options.voice,
        public_url=public_url,
        personal=options.personal,
    )


def render(options: InitOptions, *, today: dt.date | None = None) -> dict[str, str]:
    """The files ``ira init`` writes, by name. Raises InitError on a bad option."""
    options = check_options(options)
    public_url_line = (
        f"    public_url: {options.public_url}"
        if options.public_url
        else "    # public_url: https://ira.example.com"
    )
    values = {
        "name": options.name,
        "name_yaml": _quoted(options.name),
        "business": options.business,
        "business_yaml": _quoted(options.business),
        "date": (today or dt.date.today()).isoformat(),
        "port": str(options.port),
        "public_url_line": public_url_line,
        "provider_sections": _provider_sections(options).rstrip("\n"),
        "provider_note": (
            "Amazon Bedrock models, Voxtral speech-to-text and Polly speech, signed by "
            "the server's AWS role"
            if options.provider == "bedrock"
            else "the free demo router: a keyword matcher, not a language model"
        ),
        "instructions": PERSONAL_INSTRUCTIONS if options.personal else BUSINESS_INSTRUCTIONS,
        "tools_section": PERSONAL_TOOLS if options.personal else BUSINESS_TOOLS,
        "search_section": PERSONAL_SEARCH if options.personal else "",
        "kind": "a personal assistant" if options.personal else "One IRA instance",
        "tools_row": (
            "Two example tools, switched off: your devices and search add your tools."
            if options.personal
            else "Two placeholder tools. Replace them with your own."
        ),
        "make_it_yours": (
            "- Sign in, set your PIN, and pair Ira for Mac on **Your devices** in the Ira\n"
            "  app: Ira can then find your files, read your screen and your browser tabs\n"
            "  when you ask.\n"
            "- Switch web and news search on in **Your assistant**, and list news feeds\n"
            "  under `search.news.feeds`."
            if options.personal
            else "- Describe the business in `assistant.business` and `assistant.instructions`.\n"
            "- Replace `find_notes` and `add_note` in `tools.py` with tools over your own\n"
            "  data. Reads are `@tool`; changes are `@action`, and run only after a PIN."
        ),
    }
    files = {
        "ira.yaml": Template(_template("ira.yaml.tmpl")).substitute(values),
        "tools.py": _template("tools.py"),
        "README.md": Template(_template("README.md.tmpl")).substitute(values),
        ".gitignore": _template("gitignore"),
    }
    _check_config(files["ira.yaml"])
    return files


def _check_config(text: str) -> None:
    """The written ira.yaml must load exactly as `ira serve` will load it."""
    raw = yaml.safe_load(text)
    Settings.model_validate({**raw, "config_dir": Path.cwd()})


def init_folder(folder: Path, options: InitOptions) -> list[Path]:
    """Write a new business folder. Refuses one that already has anything in it."""
    files = render(options)  # validate everything before touching the disk
    if folder.exists():
        if not folder.is_dir():
            raise InitError(f"{folder} exists and is not a folder")
        if any(folder.iterdir()):
            raise InitError(f"{folder} is not empty; ira init only fills a new or empty folder")
    else:
        folder.mkdir(mode=0o750, parents=True)
    written = []
    for name in TEMPLATES:
        path = folder / name
        # "x": never overwrite, even if something appeared since the check above.
        with path.open("x", encoding="utf-8") as handle:
            handle.write(files[name])
        written.append(path)
    return written
