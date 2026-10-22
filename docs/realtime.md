# Real-time voice

Talking to Ira like a phone call: no button between turns, Ira starts
speaking a moment after you stop, and stops the moment you speak. The Ira
app (in the browser and on the phone), the Mac app and the Android app all
use the same connection, described here.

Status: **protocol version 1** (22 Oct 2026). The server answers, and the
Ira app has a live call: the phone button next to the text box starts it,
**End call** stops it, and typing during a call goes into the call. Fields
may still be added; none will change meaning without a new version.

## How a turn flows

```text
you speak ──► the app's voice detector ──► audio, only while you speak
                                              │
          Amazon Transcribe streaming ◄───────┘  (Hindi and English told apart)
                 │  live captions
                 ▼
     you stop ─► final text ─► Ira's model, streaming, with your tools and tiers
                                   │  each sentence as soon as it is complete
                                   ▼
                          Amazon Polly ──► audio ──► the app plays it
```

- **The app detects speech** and sends audio only while you speak, with a
  short lead-in. Silence is never sent, so nothing is transcribed (or paid
  for) while nobody talks.
- **End of turn**: the app says when you stopped (`speech_end`, after
  about 0.6 s of quiet). Ira takes the final transcript and answers.
- **Barge-in**: when you start speaking while Ira talks, the app stops
  playing at once, without waiting for the server, and says so
  (`speech_start`). The server stops speaking that answer.
- **Sentence by sentence**: Ira's answer streams from the model; each
  sentence is spoken as soon as it is complete, so the first words play
  while the rest is still being written.
- **The same Ira**: the same conversation, tools, security tiers, privacy
  and learning as typing. A Tier 2 action is read back with its exact
  target ("call number on Pixel 7: name Rahul Sharma, number +91 98100
  00000. Haan ya na?") and takes a spoken "haan" or "yes"; a Tier 3 action
  shows its card in the app and needs the PIN typed, never spoken.

## The connection

`GET /v1/voice/live`, a WebSocket (`wss://` on a public server).

Sign-in, one of:

| Who | How |
| --- | --- |
| The Ira app in a browser | its session cookie; the `Origin` must be the server's own |
| An app with a signed-in session | `Authorization: Bearer <session token>` |
| A paired device (the Mac app, the Android app) | `Authorization: Bearer irad_...`, its device token: it speaks for the person it is paired to |
| A client that cannot set headers | `?token=...` (masked in the server's logs) |

The person needs the `voice` and `ask` permissions (owner, admin, staff),
and the server needs speech-to-text of type `transcribe` and text-to-speech.
Otherwise the server sends an `error` with `fatal: true` and closes.

Messages are JSON text frames, except audio, which goes in binary frames.

## Audio

| Direction | Format |
| --- | --- |
| up (your voice) | binary frames of raw PCM: 16-bit signed little-endian, mono, 16,000 Hz, 20 to 100 ms each (640 to 3,200 bytes). Only while speaking: from about 300 ms before speech began until `speech_end`, including the quiet of the hangover (it lets the transcript settle on the last word) |
| down (Ira's voice) | an `audio` message, then one binary frame: a whole sentence as MP3 (24 kHz mono), ready for `decodeAudioData` or `AVAudioPlayer` |

## Client to server

| Message | When |
| --- | --- |
| `{"type": "start", "protocol": 1, "client": "ira-pwa/0.2", "conversation_id": "..."}` | first, once. `conversation_id` is optional: the same one continues a conversation; without it, a new one starts |
| binary audio | while you speak |
| `{"type": "speech_start", "at": 1234.5}` | the voice detector heard speech start. While Ira is speaking, this is also a barge-in. `at`: the app's own clock, in milliseconds (`performance.now()` or monotonic), the same clock for every message |
| `{"type": "speech_end", "at": 2345.6}` | you stopped: after the app's hangover (about 600 ms of quiet). `at` is when the last spoken audio ended, not when the hangover ran out |
| `{"type": "text", "text": "..."}` | a typed turn, in the same conversation |
| `{"type": "interrupt"}` | stop talking and stop this answer (a stop button) |
| `{"type": "played", "turn": 3, "at": 3012.0}` | the first audio of turn 3 started playing. The latency of that turn is this `at` minus the `speech_end` `at` |
| `{"type": "pong"}` | the answer to a `ping` |
| `{"type": "bye"}` | closing on purpose |

## Server to client

| Message | Meaning |
| --- | --- |
| `{"type": "ready", "protocol": 1, "conversation_id": "...", "assistant": "Ira", "languages": ["en-IN", "hi-IN"], "tts": "polly"}` | after `start`: send audio when you like |
| `{"type": "partial", "text": "kal subah", "language": "hi-IN"}` | live captions while you speak; each replaces the last |
| `{"type": "heard", "turn": 3, "text": "kal subah 9 baje yaad dilana", "language": "hi-IN"}` | the final text of your turn; Ira starts answering |
| `{"type": "delta", "turn": 3, "text": "..."}` | the answer's text as it is written, as in `/v1/ask/stream` |
| `{"type": "audio", "turn": 3, "seq": 0, "text": "Theek hai.", "format": "mp3", "bytes": 5321}` | the next binary frame is this sentence's audio. Play them in `seq` order |
| `{"type": "action", "turn": 3, "action": {...}}` | a proposed action, as in `/v1/ask`. Tier 2: say yes or no. Tier 3: show the card; the PIN is typed |
| `{"type": "done", "turn": 3, "text": "...", "message_id": 812, "timings": {"stt_ms": 240, "model_first_ms": 610, "tts_first_ms": 130}}` | the answer is complete. `timings`: from `speech_end` arriving to the final transcript, to the model's first words, and the first sentence's speech synthesis |
| `{"type": "interrupted", "turn": 3}` | after a barge-in or `interrupt`: no more audio for turn 3 |
| `{"type": "ping"}` | every 20 seconds; answer with `pong` |
| `{"type": "error", "message": "...", "fatal": false}` | a turn failed (and the call goes on), or with `fatal: true` the connection closes |

Turns are numbered from 1 in each connection. Audio for an old turn after
`interrupted` is never sent.

## Latency

The measure is **from the end of your speech to the first word you hear**:
`played.at - speech_end.at`, on the app's own clock. It includes the voice
detector's hangover, the final transcript, the model's first sentence, the
speech synthesis, the network both ways and the start of playback. Each
`played` is kept with its turn (never its words), and `ira eval live`
measures it against a server from the command line. The target is 1.5
seconds or less; the measured p50 and p95 are published in
[Hindi, English and Hinglish](language.md).

## Measured

On 22 Oct 2026, with `ira eval live` on the EC2 server in Mumbai: the 24
requests of the language set, each spoken by Polly's Kajal in real time,
Amazon Transcribe in `ap-south-1` (Hindi preferred, English identified),
the `default` tier on Bedrock in `us-east-1` (`moonshotai.kimi-k2.5`, then
`zai.glm-5`, then `deepseek.v3.2`) and Polly neural in `ap-south-1`. The
app's 0.6 s end-of-speech wait is included; the network is the server's
own, so a phone adds its round trip (about 50 to 150 ms in India).

| Run | p50 | p95 | Fastest | Slowest |
| --- | --- | --- | --- | --- |
| 1 | 1.67 s | 5.58 s | 1.30 s | 7.16 s |
| 2 | 2.18 s | 5.10 s | 1.21 s | 5.79 s |
| 3, deployed (23 Oct) | 1.61 s | 5.59 s | 1.15 s | 9.54 s |

Run 3 is the same set on the server as deployed on 23 Oct 2026 (fda306a,
with `qwen.qwen3-235b-a22b-2507` added to the chain and Ira for Mac's
browser and screen tools as the stand-ins). 23 of 24 turns spoke; the
slow ones were two tool-heavy turns whose model took 5.5 s and 9.5 s to
start. The one silent turn: "woh wala", heard as "Vovala", got an answer in
Chinese, which Ira refuses to speak.

Where the time goes, as medians after `speech_end` arrives:

| Step | Run 1 | Run 2 | Run 3 |
| --- | --- | --- | --- |
| the final transcript | 0.18 s | 0.16 s | 0.18 s |
| the model's first words | 1.17 s | 1.97 s | 1.10 s |
| the first sentence's speech (Polly) | 0.08 s | 0.09 s | 0.08 s |
| the first audio sent | 1.05 s | 1.54 s | 1.00 s |

The model's first words decide it, and they vary from run to run and from
request to request: a request that needs a tool waits for two model calls
(Ira says "Ek second" or "One moment" at once, which counts as its first
word). The fast tier (`openai.gpt-oss-120b` first) was slower at the median
(2.20 s) because it reasons before it answers. Next, to bring p50 under
1.5 s: start the model on the settled transcript during the end-of-speech
wait, and try the next model in the chain when the first is slow to start.

The words themselves: Polly's speech came back accurate in Hindi and
English; Hinglish came back in Devanagari ("क्रोम में कौन से टैब्स खुले
हैं"), which the model reads well. A first word was sometimes lost when an
utterance began with long quiet. Real voices will differ from Polly's.

## Setting it up

```yaml
voice:
  stt:
    type: transcribe
    region: ap-south-1            # the role needs transcribe:StartStreamTranscriptionWebSocket
    languages: [hi-IN, en-IN]     # Hindi preferred; English identified
  tts:
    type: polly
    voice: Kajal
    engine: neural
    region: ap-south-1
  tier: default                   # optional: a model tier for calls only
```

`ira eval live` measures a server's own latency; `--transcribe REGION`
tries Transcribe without changing `ira.yaml`, and `--tier` another tier.

## Privacy

- Audio goes only to the server, and from there only to Amazon Transcribe;
  neither keeps it. Nothing is recorded.
- What is said becomes the conversation's text, as when typing.
- The app's voice detector runs on the device.
