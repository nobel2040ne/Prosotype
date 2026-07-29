# Glossary

Plain-language definitions of the terms used throughout this project. If a term
in the code or docs is unclear, it should be here — if it isn't, please add it.

## Product & domain

**Prosotype** — the name of this project: an application that turns live speech
into expressive captions. "Prosody" (the melody and rhythm of speech) + "type"
(typography).

**Caption with Intention (CWI)** — the published design system we implement. It
specifies how captions should look and move so that Deaf and hard-of-hearing
viewers can follow *who* is speaking, *when* each word is spoken, and *how* it
is said. Authored by the Chicago Hearing Society. The V1.0 PDF is the single
source of truth for the visual design; see [SOURCES.md](SOURCES.md).

**Deaf / hard-of-hearing (Deaf/HoH, DHH)** — the primary audience. The whole
design exists to give this audience information that hearing viewers get for
free from the audio.

**Open captions** — captions burned into the view that everyone sees (as
opposed to *closed* captions the viewer can toggle). Our live mode renders open
captions in the browser.

### The three CWI pillars

**Attribution** — *who is speaking.* Each speaker is assigned a distinct color
(yellow, green, blue, pink, red, orange, in that wheel order). A word is drawn
in its speaker's color.

**Synchronization** — *when a word is spoken.* As each word begins, it turns
from white to its speaker's color and does a brief "pop" (a small size increase
and lift, then a return to normal). This points the viewer's eye at the word
being said right now.

**Intonation** — *how a word is spoken.* The typography carries the voice:
louder speech is larger, and pitch changes the font weight and width. This uses
a *variable font* (see below).

## Speech processing

**Automatic speech recognition (ASR)** — turning audio into text. We run
recognizers locally (no cloud).

**Streaming / online ASR** — recognition that emits words continuously as you
speak, before the sentence is finished. Required for live captions. Contrasted
with offline recognition, which processes a whole recording at once.

**Diarization** — "who spoke when": splitting audio into speaker turns. It does
not identify names, only that speaker A differs from speaker B.

**Prosody** — the measurable qualities of *how* speech sounds: loudness, pitch,
and timing. Prosody drives the Intonation pillar.

**Endpoint** — the moment a phrase finishes (a pause). At an endpoint we run a
more accurate verification pass over the completed phrase.

**Onset** — the very beginning of a word or speech sound. The *onset sidecar* is
an optional component that guesses the first few letters of a word from its
opening sounds (e.g. `H → He → Hel`) so a drawn-out word can start appearing
before the recognizer commits to full spelling.

**Word error rate (WER)** — the standard accuracy metric for ASR: the fraction
of words inserted, deleted, or substituted compared to a reference transcript.

## Models & components

**Nemotron / Parakeet** — the English streaming recognizer (Nemotron) and its
endpoint verifier (Parakeet). Nemotron gives fast provisional text; Parakeet
re-checks each finished phrase.

**Zipformer** — the Korean streaming recognizer (a 174M-parameter causal
model).

**Sortformer** — the streaming diarization model (from NVIDIA) that tracks
speaker turns in real time on Apple Silicon.

**Speaker embedding** — a numeric "voiceprint" used to confirm a speaker's
identity at an endpoint. English uses a model called ERes2Net; Korean uses
CAM++.

**Variable font** — a font whose weight, width, and other axes can be set to any
value continuously, not just a few presets. We use Roboto Flex (English/Latin)
and Noto Sans KR (Korean). This is what lets typography track pitch smoothly.

## Data & runtime

**CaptionSpec (`spec.json`)** — the versioned data contract. It is the single,
stable description of a caption: the words, their timing, speaker, loudness,
pitch, and how to style them. **Every consumer (the renderer, a future haptic
device) reads only the CaptionSpec — never the internal model objects.** See
[../ARCHITECTURE.md](../ARCHITECTURE.md).

**Server-Sent Events (SSE)** — a one-way stream from the Python server to the
browser over plain HTTP. Live captions arrive as SSE `word` events. The browser
reconnects automatically and can replay missed events.

**Stage** — the main audience-facing caption surface in the studio UI: a stable
stack of the most recent caption rows.

**Transcript** — the secondary UI surface that keeps the complete history of
what was said, organized by speaker and utterance.

**Voice Compass / voice circle** — UI indicators that show continuous voice
qualities (volume, pitch, brightness) as shapes, separate from the caption text.
The compass reserves a direction marker for future multi-microphone input.

**Haptics** — physical/vibration feedback. Not built yet. A future haptic module
would subscribe to the same CaptionSpec / SSE contract and buzz on meaningful
events (speaker changes, emphasis) rather than every word.

## The three run modes

**Live** — the primary mode. Microphone → CWI-styled captions in the browser, in
real time.

**`cc` (closed-caption renderer)** — plays a finished `spec.json` with the text
known in advance. Because the future is known, it renders the *exact* reference
CWI motion. It is the visual benchmark the live mode is measured against.

**Offline** — a batch pipeline (`media → transcribe → diarize → prosody → fuse`)
that ends at `spec.json`. Kept as the reference generator for the CaptionSpec
contract.
