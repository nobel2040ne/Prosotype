# Source

## The official release

`captionwithintention.org` publishes the system as open source. The **complete** release is five artifacts — there is no code repository, and the site itself is a Squarespace page whose only scripts are Squarespace's own. Verified 2026-08-11:

| artifact | official size |
|---|---|
| `Caption-With-Intention_Design-System_V1.0.pdf` | 45,667,613 — 56 pages |
| `cwi-quickstart-guide.pdf` | 144,710 |
| `Academy_CI_Template.aep` | 5,083,469 |
| `cena-ci-template-v02a.mp4` | 7,364,118 — the footage the template is authored against, and the only one of the five carrying audio |
| `Instal Font - RobotoFlex.ttf` | — `scripts/fetch_font.py` downloads it to `assets/RobotoFlex.ttf` |

**V1.0 is the current design system.** `V1.1` and `V1.2` return 403; there is no newer document to be missing.

**None of the four documents are redistributed here** — download them from `captionwithintention.org`. The copies this project measured were verified byte-identical to the sizes above.

## `PR_Flim.mp4`

The Caption with Intention PR film, 68.6 s with audio, and the one reference file this repository carries. **It is the only source where motion and audio are both real**, which is why it is the one kept: the site's own screen recordings are silent, so the audio columns in `assets/reference_specs/*.json` are solved backwards out of measured motion and motion must never be regressed against them. Those specs are tracked, so the measurement stands on its own.

It is also what `autocwi live --sample` plays, resolved by `live.py` from this directory.
