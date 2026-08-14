# Security Policy

Weave captures a microphone and renders what it hears. The material it handles
is speech, in a room, from people who did not necessarily consent to a
recording — so most of what matters here is about where audio goes, not about
memory safety.

## Supported versions

This is a research prototype. Only the current `main` is supported; fixes land
there and are not backported.

## Reporting a vulnerability

Report privately — **do not open a public issue**.

- Preferred: [GitHub private vulnerability reporting](https://github.com/nobel2040ne/Weave/security/advisories/new)
- Or email **nobel2040ne@gmail.com**

Include what you did, what happened, and what you expected. A minimal
reproduction (a config diff, a command line) is worth more than a description.

Expect an acknowledgement within about a week. This is a one-person student
project, so there is no bounty and no guaranteed fix window. Please give a
reasonable window before disclosing publicly.

## What is in scope

- **Audio or transcript leaving the machine** on any path other than the ones
  listed below. That is the highest-severity class here.
- **The live server's network exposure.** It binds `127.0.0.1` unless `--host`
  says otherwise. A path that widens the bind without the flag, or that exposes
  more than the static export, `/runtime-config.json`, `/session`,
  `/session/language`, the two fonts and `/events`, is a bug.
- **The LAN link to the hardware node** (`scripts/hw/prosotype_node.py`): it is
  unauthenticated and unencrypted by design — see the limitation below — but a
  way to make it execute or write something on either end is in scope.
- **Credential handling.** `HF_TOKEN`, `OPENAI_API_KEY`, `SPEECHMATICS_API_KEY`
  and `SONIOX_API_KEY` are read from the environment; any path that logs,
  serializes into `spec.json`, or transmits one is in scope.
- **Path traversal or arbitrary write** from a media file, a `spec.json`, or a
  request to the live server.
- **Dependency vulnerabilities** that are actually reachable from a documented
  command. `requirements.txt` is pinned.

## Known and accepted

These are documented design decisions, not vulnerabilities. Reporting them is
fine; they will be closed as accepted risk.

- **The hardware node link is unauthenticated plaintext over the LAN.** The
  booth setup is a Pi and a Mac on a private network for the length of a demo.
  Do not run it on a network you do not control.
- **`--host 0.0.0.0` exposes the caption stream to the LAN.** That is what the
  flag is for. It is opt-in and announced on stdout.
- **Opt-in cloud lanes send audio or text off the machine.**
  `live.verifier_backend: openai` sends audio for text-only verification;
  `scripts/benchmark.py --backends speechmatics,soniox` **uploads the evaluation
  audio**. Both default off, and the local path is always the mandatory
  fallback. If you enable one, that is a disclosure you are making on purpose.
- **First-run downloads reach the network** — models, fonts, and the FLEURS
  evaluation set. After they complete, the app runs fully offline.
- **Captured audio and derived transcripts are written to `--out` unencrypted.**
  There is no at-rest encryption and no retention policy; treat the output
  directory as sensitive.
- **`HF_TOKEN` is only an authorisation for a gated download.** Inference still
  runs locally.

## Not in scope

Findings from a tool run without a working proof of concept, missing hardening
headers on a loopback-bound development server, social engineering, and
denial of service against a process the reporter already controls.
