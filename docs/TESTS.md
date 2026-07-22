# Testing

Last updated: 2026-07-23

73 tests, ~3 s, **fully offline by design** — no model loads, no network, and
no video decoding. Audio is synthesised with known ground truth; the reference
recordings are represented by the CaptionSpecs already derived from them. Keep
it that way: a suite that needs 1.9 GB of weights or a 9 MB `.mov` stops being
run.

Generated pages are checked by asserting against the HTML/JS **source string**
rather than by driving a browser. It is blunt, but it is what pins a documented
motion constant to the code that reads it.

## Running

```bash
python3.11 -m venv .venv                       # one time
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest                     # the whole suite
.venv/bin/python -m pytest tests/test_live.py -k motion -v
```

## Layout

```
tests/
├── fixtures/
│   └── forward_map_golden.json   441-point grid captured FROM the page's JS
├── test_schema.py      (6)  CaptionSpec validation: colours, ranges, ordering
├── test_overlap.py     (5)  word -> speaker by max span overlap
├── test_fuse.py        (5)  per-speaker normalization, palette assignment
├── test_prosody.py     (3)  dB/F0 on synthetic tones with known answers
├── test_reference.py   (3)  the Python prosody mirror vs the golden grid
└── test_live.py       (51)  live engine, both renderers, derived specs
```

`test_live.py` is most of the suite and covers four areas: the streaming
engine (batching, gain, endpoint verification, SSE replay), speaker tracking,
the live page, and the `cc` renderer plus the three derived reference specs.

## The golden grid

`autocwi/ccprosody.py` re-implements the renderer's own `typeOf()` so the
derivation can **invert** it. Two implementations of one map drift, and drift
is silent here — the spec still validates and the page still renders while
every derived word is wrong.

So the map is pinned to a grid captured from the JavaScript itself. After
touching `mapping`, `expression`, `closed_caption`'s axis keys, or `typeOf`:

```bash
.venv/bin/python scripts/dump_forward_map.py   # needs Chrome; never run by pytest
```

`test_reference.py` asserts Python reproduces every point *and* that the config
stored beside the grid still matches `config.yaml`, so a stale fixture fails
with "re-run dump_forward_map.py" instead of quietly passing. It earned this on
its first run: it caught `restWght` being rounded to a multiple of 4 in the
page but not in Python.

## Conventions

- Assertions carry the *reason* in a comment. Most of this suite exists because
  something specific broke; a bare `assert x == 3` invites the next person to
  update the number instead of the code.
- Pin behaviour, not implementation strings, wherever there is a choice — but
  when the only handle is generated JS, assert the source string and say why.
- Values the design system states are asserted **against the PDF's section
  number** (`sync_pop == 0.15`, 2.2.3), not against whatever the code happens
  to do.
- No mocks or fakes; the boundaries that need crossing are crossed with small
  real inputs (synthetic numpy audio, a three-word spec).

## Benchmarks

Not part of the suite — they load models and take minutes.

```bash
.venv/bin/python scripts/benchmark_streaming.py            # WER + RTF
.venv/bin/python scripts/benchmark_streaming.py --stress   # 4-condition matrix
.venv/bin/python scripts/benchmark_streaming.py --quiet-sweep
```

Current: 0 edits / 77 words clean; 7 edits / 308 words across the stress
matrix (2.27%). Re-run before swapping any checkpoint — the recognizer choice
here is measured, not assumed.
