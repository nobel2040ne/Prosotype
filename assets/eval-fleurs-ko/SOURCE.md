# Evaluation set: FLEURS

Source: Google FLEURS (`google/fleurs`), split `test`, config `ko_kr`. Licence: CC BY 4.0 -- https://creativecommons.org/licenses/by/4.0/ Downloaded: 2026-08-05 Rows: 120

FLEURS is read speech. It is a real, externally comparable benchmark and it fixes the "no Korean eval set at all" problem, but it is NOT booth audio: it has no spontaneous speech, no two-speaker turn-taking, and no room noise. Treat a score here as a floor, not as evidence the system works at the fair. Record real booth audio and pass it with `--refs` before trusting any A/B for the demo.
