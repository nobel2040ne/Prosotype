# Korean recognition: what to adopt, from open benchmarks

Written 2026-08-11 after a report that Korean word recognition is poor. **Desk
research only — nothing here was benchmarked locally.** Every number is someone
else's published figure, and the caveat below about comparing them is the most
important paragraph in this file.

## The complaint is justified

| | measured here | on |
|---|---|---|
| English | **2.27% WER** | FLEURS en |
| Korean | **10.54% CER** normalized / 13.23% raw | FLEURS ko, 120 clips |

And the largest remaining Korean error category is already recorded: **the FIRST
word of a clip** — 5 of 8 clips in the old slice had an error in their opening
word, with `다리 밑`, `염`, `합금은` dropped outright. Padding leading silence and
disabling `InputGain` both changed nothing, so it is the model, not the pipeline.

That failure mode matters for the recommendation: a word at the very start of an
utterance is where a *causal streaming* model has the least context, and it is
exactly what a full-utterance pass fixes.

## What a replacement has to satisfy

This is what eliminates almost every candidate, so it comes first:

1. **True streaming**, and fast. `chunk-64` was already disqualified here at
   1552 ms paint p90 — it left 198 ms before the playhead turn against a 420 ms
   `min_read_ahead_ms` floor, i.e. CWI 2.2.1 read-ahead disappears.
2. **Per-word `start`/`end`.** The project's binding constraint. Prosody, the
   motion clock, the hold gate and Sortformer coverage all key off word spans,
   and synthesizing onsets is explicitly forbidden.
3. **Local and offline.**

**No open model satisfies all three better than what ships.** The accurate
Korean models are offline and give no streaming timestamps:

| model | streaming | word timestamps | licence |
|---|---|---|---|
| Whisper large-v3 / turbo | no | approximate, via attention alignment | MIT |
| **Qwen3-ASR-1.7B / 0.6B** | yes, vLLM | **"streaming inference does not support … returning timestamps"** — offline only, via `Qwen3-ForcedAligner-0.6B` | **Apache-2.0** |
| our 174M causal Zipformer | **yes, 640 ms chunks** | **yes, native** | Apache-2.0 |

Qwen3-ASR's streaming mode has the same disqualifier the project already applies
to OpenAI's streaming models: *audio in, bare text out*, which is why those sit
at `EndpointVerifier` and nowhere else.

**And sherpa-onnx has nothing newer.** Its official Korean catalogue is still
`sherpa-onnx-streaming-zipformer-korean-2024-06-16` — the model this repo already
tested and rejected at 14.47% CER. The shipped 174M is a community checkpoint
and is still the best streaming Korean option available.

## The open benchmark numbers

From [OpenKoASR](https://gt-kim.github.io/open-korean-automatic-speech-recognition/),
the dedicated Korean leaderboard. **KsponSpeech CER**, lower is better:

| model | params | clean | other | licence |
|---|---|---|---|---|
| **Qwen3-ASR-1.7B** | 1.7B | **0.120** | **0.117** | Apache-2.0 |
| **Qwen3-ASR-0.6B** | 0.9B | **0.139** | 0.135 | Apache-2.0 |
| Whisper large-v3 | 1.54B | 0.147 | 0.151 | MIT |
| Whisper large-v3-turbo | 807M | 0.155 | 0.155 | MIT |
| Whisper medium | 762M | 0.169 | 0.175 | MIT |
| Whisper small | 241M | 0.192 | 0.192 | MIT |

**Qwen3-ASR beats every Whisper variant on Korean at a fraction of the size** —
0.6B is better than large-v3 (1.54B), and 1.7B is better still.

### The caveat that decides how much to trust this

**These are not comparable to our 10.54%, and the leaderboards are not fully
comparable to each other.**

- Different dataset. Ours is FLEURS ko (read, clean); the board is KsponSpeech
  (spontaneous, harder). A model's CER moves several points between them.
- Different normalization. ENERZAi publishes Whisper large-v3 at **11.13%** on
  KsponSpeech eval-other where OpenKoASR has **15.1%** — a 4-point spread on the
  same model and the same set. This project has already been bitten by exactly
  this: **the same audio scored 13.23% raw and 10.54% normalized here.**

So the table ranks candidates; it does **not** predict what any of them would
score in this pipeline. Only `scripts/benchmark.py --lang ko` can say that.

## Recommendation: do not replace the streaming model — turn the verifier on

The English path already has the architecture this needs, and Korean has it
switched off:

```
English:  Nemotron streams (timings, read-ahead)  ->  Parakeet verifies at endpoint (durable text)
Korean:   Zipformer streams (timings, read-ahead)  ->  verifier_enabled: false
```

**Adopt Qwen3-ASR-0.6B as the Korean endpoint verifier.** It fits every
constraint because it is never asked to stream:

- Word timings keep coming from the Zipformer, untouched. The verifier supplies
  **text only**, which is precisely the role the project already sanctions for a
  model without timestamps.
- Apache-2.0, 0.9B, runs locally; an MLX build exists for Apple Silicon
  (`moona3k/mlx-qwen3-asr`), which is the target machine.
- It re-decodes the **whole utterance with full context**, which is the specific
  fix for the first-word errors that are Korean's largest documented error
  category — a causal streaming model has almost no context there and an offline
  pass has all of it.
- Best open Korean accuracy on the leaderboard, at a size that is plausible
  inside the ~1.3 s endpoint budget.

`verifier_enabled: false` was set because a **2024** offline Zipformer "changed
one phrase this stream had already recognized correctly". That judgement was made
on **four bundled utterances**, before the 120-clip eval set existed, and the rules
already flags it as re-testable. This is a different, much stronger model, and the
question is now answerable properly.

Second choice if Qwen proves too slow at the endpoint: **Whisper large-v3-turbo**
(MIT, 807M, RTFx ~50-69, worse Korean CER) — and `faster-whisper` + `ctranslate2`
are *already pinned in `requirements.txt`*, so it costs no new runtime.

## What shipped

The Korean profile keeps its own model and its own overlay: the English
sidecars (draft, verifier, TIMIT onset) are off, and Korean is never passed
through them. A third `multi` profile exists alongside `en` and `ko` for
sessions where both languages are spoken, including inside one sentence — it is
an ADDITION, not a replacement, because it A/B'd worse on English (3.25% against
2.27% WER). Its language is a per-stream option applied at every stream
creation, including the reset after each endpoint.

It needs sherpa-onnx from master; `requirements.txt` says so, and pinning back
disables only that profile. The full comparison is in the decision log.

## Before shipping any of this

Not done here, by request. When it is:

1. `scripts/benchmark.py --lang ko` on the 120-clip FLEURS set, reporting **both**
   raw and normalized — the only number comparable to the 10.54%/13.23% baseline.
2. Score **timing as well as text**. The benchmark already does: a backend with
   better words and worse spans is a downgrade here, and a verifier must not move
   the onsets the motion clock depends on.
3. Measure the endpoint cost. The verifier runs inside the endpoint stall; if it
   pushes paint p90 toward 1.5 s it takes read-ahead with it, which is what
   disqualified chunk-64.
4. Re-check the revision lane. A verifier that corrects text creates revisions,
   and a settled word behind the playhead may only be corrected in colour, never
   respelled — `settledTextRef` enforces that, and it needs to hold for Korean too.

## Sources

- [OpenKoASR — Korean ASR leaderboard](https://gt-kim.github.io/open-korean-automatic-speech-recognition/)
- [Qwen3-ASR-0.6B (Apache-2.0)](https://huggingface.co/Qwen/Qwen3-ASR-0.6B) ·
  [repo](https://github.com/QwenLM/Qwen3-ASR) ·
  [technical report](https://arxiv.org/html/2601.21337v1)
- [mlx-qwen3-asr — Apple Silicon](https://github.com/moona3k/mlx-qwen3-asr/)
- [sherpa-onnx pretrained models](https://k2-fsa.github.io/sherpa/onnx/pretrained_models/online-transducer/zipformer-transducer-models.html)
- [ENERZAi — low-bit Whisper for Korean](https://enerzai.com/resources/blog/small-models-big-heat-conquering-korean-asr-with-low-bit-whisper)
- [Open ASR Leaderboard](https://github.com/huggingface/open_asr_leaderboard)
