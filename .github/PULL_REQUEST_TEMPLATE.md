# What changed

<!-- One or two sentences. What is different for someone watching a caption? -->

## Why

<!-- The problem this solves. Link the issue if there is one. -->

## Config values that moved

<!-- Every tunable that changed, old -> new, with the section it cites.
     "None" is a fine answer. A new magic number in code is not. -->

| Key | Was | Now |
| --- | --- | --- |
|     |     |     |

## How it was verified

<!-- Which probes, and what they said. For anything visual, attach a
     screenshot or recording — numeric probes have passed a visibly broken
     layout before. Include the `--broken` negative control: a check that has
     never been seen to fail is not evidence. -->

- [ ] `npm --prefix web run check` passes (lint + reducer tests + static build)
- [ ] `.venv/bin/python -m pytest` passes, if you have the suite
- [ ] Watched it in `live --sample` — not judged from numbers alone

Probe output:

```
```

## Ground rules

- [ ] Still local and offline; no telemetry, no new required network path
- [ ] No word onsets synthesized from a transcript that lacks them
- [ ] The frontend still statically exports (no Node server, route handler, server action, cookie or rewrite)
- [ ] Settled captions do not re-animate — corrections update in place
- [ ] CaptionSpec changes are optional fields, or the version is bumped
- [ ] No CWI token styling chrome, and no Apple token reaching `.caption-word`

## If this touches motion

<!-- The probes and the motion notes are development tooling and are not
     distributed with the project. Skip what you do not have — but say so. -->

- [ ] Read the motion contract (`docs/MOTION.md`) before changing it
- [ ] Measured on the system that ships (**enhanced**), not only on legacy
- [ ] The numbers come from `docs/reference/PR_Flim.mp4` or the AE template — not
      from the silent `.mov` recordings, and not from `docs/DESIGN.md`
- [ ] Re-ran `scripts/ink_collision.py` if `voice_scale_range`, wave amplitude,
      `hold_lift_em` or `character_wave_falloff` changed
- [ ] Printed every `@keyframes` stop list and asserted it is sorted, if a
      keyframe was edited
