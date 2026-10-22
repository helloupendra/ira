# Hindi, English and Hinglish

People speak to their own Ira the way they speak: in Hindi (written in
Devanagari or in Latin letters), in English, and in Hinglish, mixing both in
one sentence, often in half sentences: "upload kitna hua", "jab khatam ho
jaaye, batana".

## What Ira does

- **Understanding.** The system prompt says which languages the person
  speaks (each person chooses, in **Your assistant**; Hindi, English and
  Hinglish by default), that half sentences are normal, and that Ira should
  ask one short question back rather than guess.
- **Transcription keeps the words.** The speech-to-text prompt says to
  transcribe in the language spoken and never to translate, answer or tidy
  up. A vocabulary list (`voice.stt.vocabulary`) helps with names.
- **Replies in kind.** Ira answers in the language and script it was spoken
  to in, or always in the language the person chose (`reply_language`:
  `auto`, `en`, `hi`, `hinglish`).
- **A bilingual Indian voice.** With Amazon Polly and an Indian English or
  Hindi voice (Kajal speaks both), a reply in Devanagari is spoken as `hi-IN`
  and everything else as `en-IN`, which reads Hinglish in Latin letters
  naturally.

## Measured, not assumed

`ira eval language` asks a small fictional set of requests
(`src/ira/evals/language.yaml`: 7 in Hindi, 10 in Hinglish, 7 in English)
of the models configured in `ira.yaml`, with stand-in devices and search, and
reports:

- **intent**: the share of requests where Ira's first tool was the right one
  (or no tool, when none fits);
- **reply**: the share of answers in the language of the request;
- **heard** (with `--spoken`): each request is spoken by a macOS voice
  (Lekha for Hindi, Rishi for English and Hinglish), transcribed by the
  configured speech-to-text, and scored by word accuracy (1 minus the word
  error rate). The transcript is then what Ira is asked.

```bash
cd ~/ira/me
ira eval language              # typed requests: one or two model calls each
ira eval language --spoken     # macOS only: speak, transcribe, then ask
ira eval language --json       # every request, answer and score
```

Nothing is written to the business folder: the run uses a database in memory.

### Results so far

| Date | Models | Speech-to-text | Intent (hi / hinglish / en) | Reply language (hi / hinglish / en) | Heard |
| --- | --- | --- | --- | --- | --- |
| 22 Oct 2026 | `demo:router` (the keyword router, no model) | none | 29% / 100% / 57% | 0% / 0% / 100% | not measured |

The demo router is not a language model. It knows a few Hinglish words for
the quick start's phrases, so it routes those, and it always answers in
English. These numbers are a floor, not a measure of Ira with a model.

**Not measured yet:** Ira with a real language model and real speech-to-text.
No model or speech key was available where these docs were written. Once a
server with models is running (for example Bedrock with Voxtral and Polly,
as `ira init --provider bedrock` sets up), run `ira eval language --spoken`
there and add the row above. Until then, IRA makes no claim about how well it
understands Hindi or Hinglish beyond what this table shows.
