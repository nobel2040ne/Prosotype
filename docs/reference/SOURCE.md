# Source

## The official Caption With Intention release, in full

`captionwithintention.org` publishes the system as open source. The **complete**
release is five artifacts — there is no code repository, and the site itself is
a Squarespace page whose only scripts are Squarespace's own. Verified
2026-08-11:

| artifact | official size | ours |
|---|---|---|
| `Caption-With-Intention_Design-System_V1.0.pdf` | 45,667,613 | `docs/reference/CWI_Design_System.pdf` — byte-identical, 56 pages |
| `cwi-quickstart-guide.pdf` | 144,710 | `docs/` — byte-identical |
| `Academy_CI_Template.aep` | 5,083,469 | git blob `1518434:` — byte-identical |
| `cena-ci-template-v02a.mp4` | 7,364,118 | **here** (was missing until 2026-08-11) |
| `Instal Font - RobotoFlex.ttf` | — | `assets/RobotoFlex.ttf` |

**V1.0 is the current design system.** `V1.1` and `V1.2` return 403; there is no
newer document to be missing.

## `PR_Flim.mp4` — the film, and the clip `--sample` streams

The Caption with Intention PR film, 68.6 s with audio. **It is the only source
where motion and audio are both real** — every `*.mov` here is silent, so their
audio columns in `assets/reference_specs/*.json` are solved backwards out of the
measured motion and motion must never be regressed against them.

It is also what `autocwi live --sample` plays. It used to be checked in twice,
once here and once as `assets/sample.mp4`, byte for byte identical; there is one
copy now and `live.py` resolves it from this directory.

`PR_Flim_Annotated.txt` in `docs/` is its transcript, annotated word by word
from 28 s on. Where that annotation disagrees with a statistic, it wins.

## `cena-ci-template-v02a.mp4` — what it is, and is not

The AE template's **source footage**, not its output: 34.5 s of the Back to the
Future diner scene, 1920x1080 30 fps, **h264 + AAC**. It carries NO captions, so
it is not a motion reference.

What makes it worth keeping is that it is the clip `Academy_CI_Template.aep` is
authored against, and **it has audio** — every `*.mov` here is silent, which is
why their prosody columns had to be back-fitted. The `.aep`'s markers plus this
audio are therefore an authored caption timing paired with real speech: the one
place the template's own timing can be checked against sound without measuring
pixels. `autocwi/live.py` already lists it as a `sample_clip_path` fallback.
