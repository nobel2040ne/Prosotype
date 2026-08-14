# Source

## The official Caption With Intention release, in full

`captionwithintention.org` publishes the system as open source. The **complete**
release is five artifacts — there is no code repository, and the site itself is
a Squarespace page whose only scripts are Squarespace's own. Verified
2026-08-11:

| artifact | official size | ours |
|---|---|---|
| `Caption-With-Intention_Design-System_V1.0.pdf` | 45,667,613 | `docs/reference/CWI_Design_System.pdf` — byte-identical, 56 pages |
| `cwi-quickstart-guide.pdf` | 144,710 | `docs/reference/CWI_Quickstart_Guide.pdf` — byte-identical |
| `Academy_CI_Template.aep` | 5,083,469 | git blob `1518434:` — byte-identical |
| `cena-ci-template-v02a.mp4` | 7,364,118 | git history only, since `CLEAN STAGE 3` |
| `Instal Font - RobotoFlex.ttf` | — | `assets/RobotoFlex.ttf` |

**V1.0 is the current design system.** `V1.1` and `V1.2` return 403; there is no
newer document to be missing.

## Where these live now

`CLEAN STAGE 2`–`3` (2026-08-13) took the reference material out of the tree.
**Two files in this directory are tracked** — `PR_Flim.mp4` and this note.
Everything else is untracked on the machine that measured it, recoverable only
from git history, or both. Sizes verified 2026-08-14; each command writes the
file back where the tooling expects it.

| artifact | in the tree | recover with |
|---|---|---|
| `PR_Flim.mp4` | yes | — |
| `CWI_Design_System.pdf` | no | `git show 54c8e31^:docs/reference/cwi-design-system-v1.0.pdf > docs/reference/CWI_Design_System.pdf` |
| `CWI_Quickstart_Guide.pdf` | no | `git show 54c8e31^:docs/reference/cwi-quickstart-guide.pdf > docs/reference/CWI_Quickstart_Guide.pdf` |
| `PR_Flim_Annotated.txt` | no | `git show 54c8e31^:docs/reference/pr-film-annotated.txt > docs/reference/PR_Flim_Annotated.txt` |
| `character_identification.mov` | no | `git show d39a4e7^:docs/reference/character_identification.mov > docs/reference/character_identification.mov` |
| `character_identification.txt` | no | `git show d39a4e7^:docs/reference/character_identification.txt > docs/reference/character_identification.txt` |
| `intonation.mov` | no | `git show 34636c5^:docs/reference/intonation.mov > docs/reference/intonation.mov` |
| `intonation.txt` | no | `git show 34636c5^:docs/reference/intonation.txt > docs/reference/intonation.txt` |
| `synchronization.mov` | no | `git show 34636c5^:docs/reference/synchronization.mov > docs/reference/synchronization.mov` |
| `synchronization.txt` | no | `git show 34636c5^:docs/reference/synchronization.txt > docs/reference/synchronization.txt` |
| `cena-ci-template-v02a.mp4` | no | `git show 54c8e31^:docs/reference/cena-ci-template-v02a.mp4 > docs/reference/cena-ci-template-v02a.mp4` |
| `Academy_CI_Template.aep` | no | `git cat-file blob '1518434:AE PROJECT/AE PROJECT/Academy_CI_Template.aep' > Academy_CI_Template.aep` |

The delete commit is what `git log` reports for each path, so the content is in
its **parent** — hence the `^`. `1518434` is the first commit and never held a
delete, so it takes no `^`. Two files were renamed on the way out of the tree:
the design system PDF and the annotation, whose history names are the
lower-case ones above.

**A history rewrite would break every command in that table**, including the
`.aep` recipe quoted in `../../CLAUDE.md` and `../MOTION.md`. That is the
reason the reference media is still carried in history rather than stripped.

## `PR_Flim.mp4` — the film, and the clip `--sample` streams

The Caption with Intention PR film, 68.6 s with audio. **It is the only source
where motion and audio are both real** — every `*.mov` is silent, so their
audio columns in `assets/reference_specs/*.json` are solved backwards out of the
measured motion and motion must never be regressed against them. The specs are
tracked, so that measurement survives the recordings leaving the tree.

It is also what `autocwi live --sample` plays. It used to be checked in twice,
once here and once as `assets/sample.mp4`, byte for byte identical; there is one
copy now and `live.py` resolves it from this directory.

`PR_Flim_Annotated.txt`, beside it in this directory, is its transcript,
annotated word by word from 28 s on. Where that annotation disagrees with a
statistic, it wins.

## `cena-ci-template-v02a.mp4` — what it is, and is not

The AE template's **source footage**, not its output: 34.5 s of the Back to the
Future diner scene, 1920x1080 30 fps, **h264 + AAC**. It carries NO captions, so
it is not a motion reference.

What makes it worth keeping is that it is the clip `Academy_CI_Template.aep` is
authored against, and **it has audio** — every `*.mov` is silent, which is why
their prosody columns had to be back-fitted. The `.aep`'s markers plus this
audio are therefore an authored caption timing paired with real speech: the one
place the template's own timing can be checked against sound without measuring
pixels.

`sample_clip_path()` in `autocwi/live.py` still names a cena fallback, but at the
AE project's own path (`AE PROJECT/…/Cena_ref_CI_Template_v02a.mp4`), and that
directory is no longer in the tree either. The fallback therefore cannot fire —
`PR_Flim.mp4` is tracked and always answers first.
