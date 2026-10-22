"""``ira eval live``: how long from the end of speech to Ira's first word, on a real call.

It starts this server in the process (a database in memory, the models and
voices of ``ira.yaml``), and for each request of the language set: Polly
speaks it, the audio goes to ``/v1/voice/live`` in real time, 100 ms at a
time, and after the app's end-of-speech wait (0.6 s by default) comes
``speech_end``. The latency of a turn is from the end of the audio to the
first audio frame back, the measure in docs/realtime.md, less only the
app's own decoding and playback start. The network is this machine's own;
a phone adds its round trip.
"""

from __future__ import annotations

import asyncio
import json
import socket
import statistics
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from ira.config import Settings
from ira.store import Store
from ira.tools.registry import ToolRegistry

CHUNK_SECONDS = 0.1
LEAD_IN = b"\x00\x00" * 4800  # 300 ms of silence before speech, as an app sends


@dataclass
class LiveResult:
    id: str
    language: str
    asked: str
    heard: str = ""
    answer: str = ""
    latency_ms: float | None = None
    timings: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def percentile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return float("nan")
    index = max(0, min(len(ordered) - 1, round(share * (len(ordered) - 1))))
    return ordered[index]


async def _turn(url: str, headers: dict[str, str], pcm: bytes, hangover: float) -> dict[str, Any]:
    import websockets

    async with websockets.connect(url, additional_headers=headers, max_size=2**22) as ws:
        await ws.send(json.dumps({"type": "start", "protocol": 1, "client": "ira-eval-live"}))
        ready = json.loads(await ws.recv())
        if ready.get("type") != "ready":
            raise RuntimeError(ready.get("message") or "not ready")
        clock = time.monotonic
        await ws.send(json.dumps({"type": "speech_start", "at": clock() * 1000}))
        audio = LEAD_IN + pcm
        step = int(32_000 * CHUNK_SECONDS)
        started = clock()
        for n, start in enumerate(range(0, len(audio), step)):
            await ws.send(audio[start : start + step])
            # Real time: the next 100 ms goes when it would have been spoken.
            await asyncio.sleep(max(0.0, started + (n + 1) * CHUNK_SECONDS - clock()))
        ended = clock()
        # The app's voice detector waits for quiet, sending the quiet as it goes.
        quiet = b"\x00\x00" * int(16_000 * CHUNK_SECONDS)
        for n in range(round(hangover / CHUNK_SECONDS)):
            await ws.send(quiet)
            await asyncio.sleep(max(0.0, ended + (n + 1) * CHUNK_SECONDS - clock()))
        await ws.send(json.dumps({"type": "speech_end", "at": ended * 1000}))
        out: dict[str, Any] = {"first_audio": None}
        while True:
            message = await asyncio.wait_for(ws.recv(), 60)
            if isinstance(message, bytes):
                if out["first_audio"] is None:
                    out["first_audio"] = clock()
                    await ws.send(
                        json.dumps({"type": "played", "turn": 1, "at": out["first_audio"] * 1000})
                    )
                continue
            event = json.loads(message)
            if event["type"] == "heard":
                out["heard"] = event["text"]
            elif event["type"] == "error" and event.get("fatal"):
                raise RuntimeError(event["message"])
            elif event["type"] == "error":
                out["error"] = event["message"]
                if "heard" not in out:
                    return out
            elif event["type"] == "done":
                out["answer"] = event["text"]
                out["timings"] = event.get("timings") or {}
                break
        await ws.send(json.dumps({"type": "bye"}))
        out["latency_ms"] = (
            round((out["first_audio"] - ended) * 1000) if out["first_audio"] is not None else None
        )
        return out


async def run(
    settings: Settings,
    *,
    hangover: float = 0.6,
    only: str | None = None,
    transcribe_region: str | None = None,
    limit: int | None = None,
    tier: str | None = None,
) -> list[LiveResult]:
    import uvicorn

    from ira.channels.http import create_app
    from ira.evals.language import load_cases, stand_ins, synthesize_polly
    from ira.runtime import build_runtime
    from ira.voice.transcribe import TranscribeSTT

    runtime = build_runtime(
        settings, registry=ToolRegistry(), store=Store(":memory:"), load_tools=False
    )
    runtime.assistant.personal_tools = lambda user_id: stand_ins()
    if transcribe_region:
        runtime.stt = TranscribeSTT(transcribe_region, ["hi-IN", "en-IN"])
    if tier:
        runtime.assistant.voice_tier = tier
    user = runtime.accounts.create_user("eval@example.com", "evaluation-only-password", "staff")
    token, _ = runtime.accounts.create_token(user, "eval", ["ask", "voice"])
    tts = settings.voice.tts
    polly_region = tts.region if tts.type == "polly" else "us-east-1"
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(runtime, start_channels=False),
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )
    )
    serving = asyncio.ensure_future(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    results = []
    try:
        cases = [c for c in load_cases() if only in (None, c.language)][:limit]
        for case in cases:
            result = LiveResult(case.id, case.language, case.text)
            try:
                wav = await asyncio.to_thread(
                    synthesize_polly, case.text, case.language, polly_region
                )
                pcm = wav[44:]  # pcm16_wav's header is 44 bytes
                out = await _turn(
                    f"ws://127.0.0.1:{port}/v1/voice/live",
                    {"Authorization": f"Bearer {token}"},
                    pcm,
                    hangover,
                )
                result.heard = out.get("heard", "")
                result.answer = (out.get("answer") or "")[:300]
                result.latency_ms = out.get("latency_ms")
                result.timings = out.get("timings", {})
                result.error = out.get("error")
            except Exception as exc:  # a failed case is reported, not fatal
                result.error = f"{type(exc).__name__}: {exc}"[:300]
            results.append(result)
    finally:
        server.should_exit = True
        await serving
        await runtime.aclose()
    return results


def summary(results: list[LiveResult], hangover: float) -> dict[str, Any]:
    latencies = [r.latency_ms for r in results if r.latency_ms is not None]
    parts: dict[str, Any] = {}
    for key in ("stt_ms", "model_first_ms", "tts_first_ms", "first_audio_ms"):
        values = [r.timings[key] for r in results if key in r.timings]
        parts[key] = statistics.median(values) if values else None
    return {
        "turns": len(results),
        "measured": len(latencies),
        "hangover_ms": round(hangover * 1000),
        "p50_ms": percentile(latencies, 0.5),
        "p95_ms": percentile(latencies, 0.95),
        "median_parts_ms": parts,
    }


def main(
    settings: Settings,
    *,
    hangover: float,
    only: str | None,
    as_json: bool,
    transcribe_region: str | None = None,
    limit: int | None = None,
    tier: str | None = None,
) -> int:
    results = asyncio.run(
        run(
            settings,
            hangover=hangover,
            only=only,
            transcribe_region=transcribe_region,
            limit=limit,
            tier=tier,
        )
    )
    report = summary(results, hangover)
    if as_json:
        print(json.dumps({"summary": report, "results": [asdict(r) for r in results]}, indent=2))
        return 0
    print(f"Live voice: {report['measured']} of {report['turns']} turns measured")
    print(f"  end of speech to first audio: p50 {report['p50_ms']} ms, p95 {report['p95_ms']} ms")
    print(f"  (includes the app's {report['hangover_ms']} ms end-of-speech wait)")
    parts = report["median_parts_ms"]
    print(
        "  medians after speech_end: transcript {stt_ms} ms, model's first words "
        "{model_first_ms} ms, first sentence's speech {tts_first_ms} ms, first audio "
        "{first_audio_ms} ms".format(**parts)
    )
    for r in results:
        if r.error:
            print(f"  {r.id}: {r.error}")
    return 0
