# Documentation

Organised by what you are trying to do. Start at the top.

## Getting started

| Document | What's in it |
|---|---|
| [motion.html](motion.html) | **The whole project on one page, with the motion running.** Open it in a browser |
| [../CONTRIBUTING.md](../CONTRIBUTING.md) | From a fresh clone to running captions, then the conventions and the ground rules |
| [ARCHITECTURE.md — glossary](../ARCHITECTURE.md#glossary) | Plain-language definitions of every domain term |

## How the system works

| Document | What's in it |
|---|---|
| [../ARCHITECTURE.md](../ARCHITECTURE.md) | System design, the module map, and the data contract |
| [LIVE.md](LIVE.md) | Live captioning in depth — the caption stack, speaker attribution, recognition |
| [../web/README.md](../web/README.md) | The studio frontend and the caption behaviour that cannot change |
| [HARDWARE.md](HARDWARE.md) | The ReSpeaker array + Pi Zero 2 W + motor node: bring-up, wiring, booth runbook |

## Design intent — read before changing anything visual

| Document | What's in it |
|---|---|
| [MOTION.md](MOTION.md) | **The motion contract.** The five channels, the playhead, and the acceptance figures |
| [RESEARCH.md — sources](RESEARCH.md#sources) | The primary sources, in order of authority, and which wins when they disagree |
| [RESEARCH.md](RESEARCH.md) | Research grounding for the design decisions |
| `reference/cwi-design-system-v1.0.pdf` | The design system itself — the final word on any disagreement |

## Language

| Document | What's in it |
|---|---|
| [KOREAN.md](KOREAN.md) | Korean expression measured against English, and the material blocker |
| [KOREAN-ASR.md](KOREAN-ASR.md) | Korean recognition: open-benchmark comparison and what to adopt |

## Reference materials

- `reference/` — screen recordings of the official CWI site, with transcripts.
  Used to measure motion timing and per-word emphasis.
- `reference/pr-film-annotated.txt` — the PR film's transcript, annotated
  word by word from 28 s on. Where it disagrees with a statistic, it wins.
- `reference/cwi-quickstart-guide.pdf` — the After Effects template
  workflow.

[RESEARCH.md — sources](RESEARCH.md#sources) explains how these fit together.

## A note on what is not here

Some working files are kept out of the repository: a rulebook written for an AI
assistant, a decision ledger of everything that was tried and reverted, an
early interpretation of the design values that later measurement contradicted,
and a catalogue of measurement recipes. They are notes rather than
documentation. Everything a reader needs is in the documents above; everything
a contributor needs is in [CONTRIBUTING.md](../CONTRIBUTING.md).
