# Hindi, English and Hinglish

People speak to their own Ira the way they speak: in Hindi (written in
Devanagari or in Latin letters), in English, and in Hinglish, mixing both in
one sentence, often in half sentences: "upload kitna hua", "jab khatam ho
jaaye, batana".

## What Ira does

- **Understanding.** The system prompt says which languages the person
  speaks (each person chooses, in **Your assistant**; Hindi, English and
  Hinglish by default) and that half sentences are normal. When a tool that
  only reads can settle what they meant ("upload kitna hua": look at the
  tabs), Ira looks first, and asks one short question back only when looking
  would not help.
- **Speech in the browser, when the server has none.** With
  `voice.browser_stt: fallback` (the default), the Ira app recognises speech
  with the browser's own engine when the server has no speech-to-text, and
  sends Ira only the text: `hi-IN` for someone who speaks Hindi or Hinglish,
  `en-IN` otherwise. `prefer` uses it even when the server has
  speech-to-text; `off` never. Chrome sends the audio to Google to do this
  (see [Privacy](privacy.md)).
- **Transcription keeps the words.** The speech-to-text prompt says to
  transcribe in the language spoken and never to translate, answer or tidy
  up. A vocabulary list (`voice.stt.vocabulary`) helps with names.
- **Replies in kind.** Ira answers in the language and script of the latest
  message (English gets English, Devanagari gets Devanagari, Hindi in Latin
  letters gets Hinglish in Latin letters), or always in the language the
  person chose (`reply_language`: `auto`, `en`, `hi`, `hinglish`).
- **A bilingual Indian voice.** With Amazon Polly and an Indian English or
  Hindi voice (Kajal speaks both), a reply in Devanagari is spoken as `hi-IN`
  and everything else as `en-IN`, which reads Hinglish in Latin letters
  naturally.

## Measured, not assumed

`ira eval language` asks a small fictional set of requests
(`src/ira/evals/language.yaml`: 7 in Hindi, 10 in Hinglish, 7 in English)
of the models configured in `ira.yaml`, with stand-in devices and search, and
reports:

- **intent**: the share of requests where Ira called the right tool, first
  or after another (listing the tabs to find one, then reading it, is
  right), or called none when none fits;
- **reply**: the share of answers in the language of the request, counted
  in words, with addresses and "quoted" or **bold** titles left out (a Hindi
  answer that lists English tab titles is a Hindi answer);
- **heard** (with `--spoken`): each request is spoken by a macOS voice
  (Lekha for Hindi, Rishi for English and Hinglish), or with `--voice polly`
  by Polly's Kajal (as `hi-IN` for Devanagari, `en-IN` otherwise), transcribed by the
  configured speech-to-text, and scored by word accuracy (1 minus the word
  error rate). The transcript is then what Ira is asked.

```bash
cd ~/ira/me
ira eval language              # typed requests: one or two model calls each
ira eval language --spoken     # speak, transcribe, then ask
ira eval language --spoken --voice polly   # spoken by Polly's Kajal (any OS)
ira eval language --json       # every request, answer and score
```

Nothing is written to the business folder: the run uses a database in memory.

### Results so far

On 22 Oct 2026, typed requests, on an EC2 server in Mumbai with the
`default` tier of `ira init --provider bedrock`: `moonshotai.kimi-k2.5`, then
`zai.glm-5`, then `deepseek.v3.2` on Bedrock (us-east-1). Each run is the 24
requests once; models are not deterministic, so runs differ.

| Run | Prompt | Intent (hi / hinglish / en) | Reply language (hi / hinglish / en) | Median answer |
| --- | --- | --- | --- | --- |
| `demo:router` | (the keyword router, no model) | 29% / 100% / 57% | 0% / 0% / 100% | instant |
| 1 | ask when unsure | 100% / 100% / 100% | 100% / 100% / 100% | 2.0 s |
| 2 | ask when unsure | 86% / 90% / 100% | 100% / 80% / 100% | 1.8 s |
| 3 | look first, then ask | 100% / 100% / 100% | 100% / 100% / 100% | 2.2 s |
| 4 | look first, then ask | 100% / 100% / 100% | 100% / 100% / 86% | 2.8 s |

What the misses were:

- **Half sentences** (run 2): "upload kitna hua" and "जब अपलोड पूरा हो जाए
  तो बताना" got a question back ("which upload?") instead of a look at the
  tabs. The prompt then changed to "look first, then ask"; both passed in
  runs 3 and 4.
- **Script drift**, in every kind of prompt: an answer about the news in
  English to "aaj ki khabar batao", and in Hinglish to "What's in the news
  today?"; "theek hai, thanks" answered in Devanagari. About one answer in
  25 drifts. Keeping names and titles as they are is fine; the drift is in
  the sentence around them.
- An earlier run, scored the old way, counted a Hindi answer that listed
  English tab titles as English, and "list the tabs, then read one" as the
  wrong tool. Both were scoring faults, fixed before the runs above.

The demo router is not a language model. It knows a few Hinglish words for
the quick start's phrases, so it routes those, and it always answers in
English. Its numbers are a floor.

**Not measured yet: speech.** On 22 Oct 2026 Bedrock's OpenAI-compatible
endpoint (Mantle) refused audio for Voxtral ("Model does not support audio
modality"), with the audio part first or second, and AWS's model card now
lists Voxtral's speech input under the Converse API only. So `chat_audio`
with Voxtral on Mantle does not transcribe today, and the **heard** column
has no real number yet. Amazon Transcribe streaming (`voice.stt.type:
transcribe`, Hindi and English identified per recording) is the next to
measure, once the server's role may use it. When a speech-to-text that works is configured, run
`ira eval language --spoken` and add its row. Until then, IRA makes no claim
about how well it hears Hindi or Hinglish.
