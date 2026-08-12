# The hardware node

ReSpeaker XMOS XVF3800 4-mic array + coin vibration motors on a Raspberry Pi
Zero 2 W, feeding a Mac running `autocwi live --node`.

## Why the work is split this way

**The Pi cannot caption.** It has 512 MB of RAM; the recognizers are 600 MB
per model and `requirements.txt` pulls torch. So the Pi captures and actuates,
and the Mac decides. That also puts the haptic decision where the speaker
tracker already lives — the node analyses nothing, which is the standing rule
for this module.

```
[XVF3800] --USB--> [Pi Zero 2 W] --TCP: audio + DoA--> [Mac: autocwi live]
                        |                                      |
                   [motor ring] <------ TCP: haptic cues ------+
                                                               |
                                                    [browser studio]
```

One TCP connection carries all three. Direction needs no clock of its own: it
references the audio sequence number it was measured against.

## Bring-up, in order

Do not skip Phase 0. Two of the three unknowns below cannot be answered by
reading code, and building on a guess is how this project has produced
confidently wrong results before.

### Reaching the Pi

What is on the card, read off the Pi rather than assumed — `/etc/rpi-issue`
names the pi-gen stage, which is the only reliable way to tell the images
apart after the fact:

```
Raspberry Pi reference 2026-06-18 ... stage4     # = "with Desktop", NOT Lite
Debian GNU/Linux 13 (trixie), aarch64, kernel 6.18.34+rpt-rpi-v8
user nobel2040ne
```

**arm64 is right; stage4 is not.** 64-bit is the correct call — the node's whole
dependency surface is numpy, `sounddevice` and `gpiozero` (`netaudio.py` takes
numpy, `haptics.py` is pure stdlib), so the 32-bit RAM argument buys nothing
and aarch64 gets official upstream wheels. The desktop is the problem:

| Measured at idle, nothing else running | stage4 as flashed | after the fix |
|---|---|---|
| Total RAM | 415 MB (512 less the GPU split) | 415 MB |
| Available | 240 MB | **259 MB** |
| **Swap in use** | **109 MB** | **0 MB** |
| Desktop processes | 3, `wf-panel-pi` alone at 17 MB | 0, lightdm inactive |

**It was already swapping to the SD card before the node had even started.**
That is the one failure this module cannot absorb: capture is lossless by rule,
so a swap stall surfaces as dropped blocks and an `AudioChunk.discontinuity`,
not as a graceful slowdown. Re-flashing to Lite is not necessary — dropping the
graphical session recovers it and keeps everything else. Already applied here:

```bash
sudo systemctl set-default multi-user.target && sudo reboot   # graphical.target to undo
```

The freed headroom is what the array needs: `wireplumber` is now the largest
process at 27 MB, and it is the one that has to stay.

**Do not `pip install -r requirements.txt` on the Pi.** It pulls torch, which
the node has no use for; the node analyses nothing, by rule. Trixie enforces
PEP 668 anyway, so install from apt and skip the venv:

```bash
sudo apt install -y python3-numpy python3-gpiozero git
sudo apt install -y libportaudio2 python3-cffi     # sounddevice's actual deps
pip install --break-system-packages sounddevice    # 0.5.5 here
```

**There is no `python3-sounddevice` on trixie** — the obvious one-line apt
install fails with `Unable to locate package`, and it is the only one of the
three that is not packaged. It is a pure-Python cffi wrapper, so the pip
install is a small wheel and PEP 668 is being overridden for a package apt
cannot supply, not for convenience. `python3-numpy` was already present (2.2.4).

From the Mac, `~/.ssh/config` carries a `prosotype` host entry and the Mac's
ed25519 public key is installed on the Pi, so this needs no password:

```bash
ssh prosotype
```

The Imager password still works as a fallback and is deliberately not recorded
in this repo — it would be unrecoverable from git history.

**The address is DHCP and mDNS does not resolve it.** avahi is not installed,
so `prosotype.local` fails and `dns-sd -B _ssh._tcp local` finds nothing — the
config points at a literal address that a reboot can move. Re-find it by OUI
rather than by guessing, because the other hosts on a phone-hotspot or dorm
network use randomized MACs and the Pi is the only one with a real vendor
prefix:

```bash
for i in $(seq 1 254); do ping -c1 -W 1000 192.168.0.$i >/dev/null 2>&1 & done; wait
arp -an | grep -iE 'e4:5f:1|b8:27:eb|dc:a6:32|d8:3a:dd|28:cd:c1'
```

`sudo apt install -y avahi-daemon` on the Pi removes this step entirely, and is
worth doing before the booth rather than at it.

**An `arp -an` hit is not proof the Pi is up.** ARP entries are a cache: a Pi
that was reachable earlier in the session still shows its OUI at its old
address for minutes after it powers off, so the scan above reports a confident
find for a machine that is gone. Confirm with something that requires the host
to answer *now* — `ping -c3`, `nc -z -G 5 <ip> 22`, or `ssh-keyscan -T 8` —
before concluding the address is good and debugging SSH.

**macOS has no `timeout`.** Wrapping a scan in it fails silently and reads as
"nothing found" — which is exactly how a Pi that was on the network got
reported as absent once. Use `ssh-keyscan -T`, `nc -G`, or a backgrounded PID
you kill yourself.

### 0. Probe the hardware

```bash
# on the Pi, array plugged in
python3 scripts/hw/probe_array.py            # devices, channels, DoA command
sudo python3 scripts/hw/probe_array.py --skip-audio  # USB descriptors need root
python3 scripts/hw/probe_array.py --watch    # stream DoA, check it tracks a voice
python3 scripts/hw/probe_motor.py --wiring   # the circuit, touches nothing
python3 scripts/hw/probe_motor.py --gpio 17  # buzz one motor
python3 scripts/hw/probe_motor.py --ring 17,27,22,23 --sweep
```

Record three things before going further:

| Record | Why |
|---|---|
| The array's **device index** and which **channel** carries processed speech | The XVF3800 exposes beamformed output alongside raw mics; averaging the raw mics undoes the beamforming the board just did |
| The **DoA command and its units** | Not hardcoded anywhere. `probe_array.py` tries candidates and prints what each returned; add the winner to `DOA_COMMANDS` so nobody rediscovers it |
| The **motor pins** and each one's **bearing** | Goes into `haptics.motors` |

**If DoA turns out to be unreadable, stop and say so.** Direction is the whole
point of the motors here, and the fallback (salience without direction) is a
different, smaller feature — not something to discover at the booth.

#### What the board actually reports (measured 2026-08-11)

Stock firmware, nothing customised, plugged into the Pi:

| | |
|---|---|
| USB | `2886:001a` Seeed reSpeaker XVF3800 4-Mic Array, `bcdDevice` 2.06 |
| ALSA | card 1 `Array`, `hw:1,0` |
| Format | **2 ch @ 16 kHz S16_LE, and nothing else offered** |
| Which channel is speech | **NOT YET MEASURED** — see below |

**16 kHz is the only rate the board offers, which is the rate the pipeline
wants.** So there is no resampling on this path, and the "averaging the raw
mics undoes the beamforming" trap above cannot be walked into by accident: in
this mode the raw four mics are not exposed at all. Both channels are already
beamformed.

**Direction does not require customising the array.** The stock descriptors
carry a vendor-specific interface named `reSpeaker Control` — the one
`xvf_host` talks to — alongside `reSpeaker HID` (`/dev/hidraw0`) and the two
DFU interfaces. **DFU is the only interface that would modify the board, and
nothing here goes near it.** So a missing DoA reading means a missing *host
utility on the Pi*, which is an install; it does not mean the array cannot do
it, which would be the stop-and-say-so case. `probe_array.py` now separates
those two questions into sections 2 and 3 rather than inferring one from the
other.

**`lsusb -v` as an ordinary user reads the interface classes but not their
names**, and a verdict keyed on the names then reports "no control interface"
for a board that has one — the stop-the-project answer, reached by lacking
permission to look. The probe detects the partial read and refuses to
conclude. Run section 2 as root: `sudo python3 scripts/hw/probe_array.py
--skip-audio`. It is a separate invocation because **`sudo` loses a `--user`
pip install**, so `sounddevice` disappears under root and the audio section
has to run without it.

#### Direction, measured (2026-08-11) — it reads

**DoA works on the stock board and needs no host binary at all.** It is vendor
control transfers on EP0, which `pyusb` can issue directly; the prebuilt
`xvf_host` in Seeed's `host_control/<platform>/` is one way, but
`python_control/` documents the protocol and that is all that is needed:

| command | resid | cmdid | payload | meaning |
|---|---|---|---|---|
| `VERSION` | 48 | 0 | 3 x uint8 | **2.0.6** here — a reply proves the control lane is open |
| `DOA_VALUE` | 20 | 18 | 2 x uint16 LE | **bearing in degrees**, then **speech-detected** |
| `AEC_AZIMUTH_VALUES` | 33 | 75 | 4 x float32 | per-beam azimuth in **radians**; last = auto-selected beam |

Reads set `cmdid |= 0x80`, request one extra byte, and the **first byte of the
response is status, not data**. Requirements are `pyusb` plus a libusb
(`brew install libusb`, already present on this Mac).

**Decode `DOA_VALUE` as little-endian uint16, not as a byte.** The vendor's own
`respeaker_get_doa.py` prints `response[1]` — a single byte, which wraps at
256 and cannot express 0..359. It looks perfectly correct at the 133 deg this
board reports at rest, and silently renders a talker *behind* the array as
being in front once the bearing passes 255. The compass takes this number
straight into a CSS rotation, so the bug would be a confident wrong claim
about the room.

**`DOA_VALUE` holds its last bearing while `speech_detected` is 0.** It does
not fall back to 0, and it does not blank. So the second uint16 is the gate
that satisfies "never fabricate direction — omit it": publish a bearing when
speech is detected, omit the field when it is not. Without that gate the
compass would keep pointing confidently at wherever the last talker was, for
as long as the room stayed quiet — which is a claim about the room that
nothing measured.

**The bearing tracks — confirmed 2026-08-11** via `probe_array.py --watch`, and
corroborated by a joint capture: of 101 reads, 14 had `speech_detected = 1`,
and across those the bearing moved 157 deg -> 114 -> 104 -> 103 rather than
sitting still. **Phase 0's direction question is answered: DoA reads, gates on
speech, and follows.**

**Not yet recorded: where 0 deg points on the case.** The compass renders this
number straight into a CSS rotation, so a board frame offset from the case's
front puts every arrow at the booth a fixed rotation out — plausible-looking
and wrong. Note it the next time the array is in front of somebody: stand where
the case's front faces you and read the bearing.

**Which of the two audio channels carries the beamformed speech is still
UNMEASURED**, after five captures across the Pi and the Mac. All five agree
weakly — ch0 rises more over its own floor than ch1 every time (+4.7, +6.8,
+7.0, +3.1, +1.0 dB against ch1's +3.4, +3.0, +3.3, -0.1, -0.1) — and ch1 sits
7-8 dB quieter with essentially no response, which is what a reference or
second beam looks like rather than the processed output. `live.py` takes
`indata[:, 0]`, so the shipped default agrees with the evidence. **Treat that
as a supported inference, not a measurement**, and settle it the first time the
array runs against real speech: clean captions mean ch0 is right.

**Measure the channel IN THE VOICE BAND, not wideband.** This board's output
carries a large 100-300 Hz component — averaged over a capture it is the single
loudest band, 4 dB above 300-1000 Hz — so a broadband RMS comparison is mostly
measuring hum and a real voice moves it barely 1 dB. Band-limit to 300-3400 Hz
before comparing channels.

**The board's own VAD is better ground truth than any acoustic guess.**
`DOA_VALUE`'s speech flag identified a 5.1 s speech window inside a 20 s
capture that a whole-capture spectral test had called empty. Poll DoA
alongside the recording and use the flag to window the analysis.

**A capture with no speech in it cannot identify the speech channel, and it
does not look empty — it looks like an answer.** Whole-capture RMS over a room
reports the room on every channel; two 30 s and 60 s captures here differed by
6.6 dB between channels and meant nothing. The probe now scores the loud
frames and gates on whether they are *voice*: a 300–3400 Hz over 20–200 Hz
tilt that is negative is a thump or a hum, and under ~18 dB of dynamic range
is an empty room. Both print **the run is INVALID**. Treat that exactly like
`baseline_probe.py`'s settle guard — it means re-run, not pass.

### 1. Wire the motors

**A GPIO pin cannot drive a coin motor.** A Pi pin sources ~16 mA; a 2.7 mm
coin motor draws 60–100 mA at stall and is inductive, so switching it off
induces a reverse spike. Direct connection browns out the pin at best.

Use a **ULN2803A** darlington array — eight channels with *internal* flyback
diodes, so a four-motor ring needs one chip and no discrete diodes.

```
  Pi 5V  ────────────────┬──────────────┐
                         │              │
                      [MOTOR]        [MOTOR]   ... up to 8
                         │              │
  Pi GPIO17 ──[1B]  ULN2803A  [1C]──────┘
  Pi GPIO27 ──[2B]           [2C]──────────────┘
                    [COM] ───┴── to Pi 5V   (flyback return)
                    [GND] ───── to Pi GND
```

- ULN2803A pin 9 (COM) → 5 V, the same rail as the motors
- ULN2803A pin 10 (GND) → Pi GND. **Common ground is required.**
- Motor + → 5 V, motor − → the matching `[nC]` output

**Power.** Four motors at ~80 mA is ~320 mA on the 5 V rail, on top of the Pi
and the array. Use a supply with real headroom (2.5 A+), or the Pi browns out
mid-demo — which looks exactly like a software crash and will be debugged as
one.

**Intensity.** The Pi Zero 2 W has only two hardware PWM channels, so a ring of
four uses gpiozero's software PWM. If it feels rough under load, install
`pigpio` and set it as gpiozero's pin factory before blaming the motors.

**One motor cannot encode direction**, however it is driven. Two gives
left/right; four gives a usable ring. With one, `bearing_weights` pulses it and
says nothing about where — the honest rendering, enforced in code rather than
left to the caller.

### 2. Configure

```yaml
# config.yaml
haptics:
  emphasis_db: 6.0
  intensity: 0.8
  motors: [17, 27, 22, 23]        # clockwise from the case's front
  # or, for an uneven layout:
  # motors:
  #   - {gpio: 17, angle_deg: 0}
  #   - {gpio: 27, angle_deg: 60}
```

### 3. Run it

```bash
# on the Mac — 0.0.0.0 is required for the Pi to reach it
.venv/bin/python -m autocwi live --node --host 0.0.0.0

# on the Pi
python3 scripts/hw/prosotype_node.py \
    --host 192.168.0.10 \
    --channel 0 \
    --ring 17,27,22,23 \
    --doa-cmd "xvf_host GET_DOA"      # whatever probe_array.py found
```

**`--device` IS A PORTAUDIO INDEX, NOT AN ALSA CARD NUMBER, and on the Pi they
disagree.** `arecord -l` reports the array as `card 1`, PortAudio enumerates it
as **device 0** — it is the Pi's only input — so `--device 1` raises
`PortAudioError: Error querying device 1` from inside `sd.InputStream`, a
traceback that names neither the array nor the mismatch and reads as a broken
board. **Omit `--device` on the Pi**; there is nothing else to choose. If you
must be explicit, pass the name (`--device "reSpeaker"`) or read the index:

```bash
python3 -c "import sounddevice as sd; print(sd.query_devices())"
```

`--channel` is unrelated and still needed: it selects which of the stream's two
channels to take, and 0 is the shipped default.

The Mac waits for the node before capturing. The node retries the connection
forever, so either can be restarted independently — which is what you want at a
booth.

## Verification

| Check | Expect |
|---|---|
| `autocwi live --node --host 0.0.0.0`, speak into the array | Captions, same as a local mic |
| Voice Compass | A degree readout, not `Awaiting array`; it tracks as you move |
| Unplug the array | Returns to `Awaiting array` within ~1.5 s (the DoA TTL) |
| Speak from four positions | The bearing follows; motors fire on the nearest side |
| Count motor pulses vs `speaker_change`/`emphasis` in `out/live_events.jsonl` | **Equal.** More means the "never on every word" rule broke |
| Stream a known clip through the node, diff against `--file` | **Identical transcript.** Any missed word is a losslessness failure |

## What the array can tell speaker attribution

Everything here is readable from a stock board over the control lane, and all
of it is available **without the device present** as a design constraint —
this section exists so diarization work can proceed offline. Verified against
firmware 2.0.6 on 2026-08-11.

| command | resid/cmd | payload | what it is |
|---|---|---|---|
| `DOA_VALUE` | 20/18 | 2 x uint16 | `[0]` bearing **0..359**, `[1]` speech detected |
| `AEC_SPENERGY_VALUES` | 33/80 | 4 x float32 | **speech energy per beam**; >0 means speech |
| `AEC_AZIMUTH_VALUES` | 33/75 | 4 x float32 | azimuth per beam, **radians** |
| `AUDIO_MGR_SELECTED_AZIMUTHS` | 35/11 | 2 x float32 | `[0]` speech-energy-selected DoA, `[1]` auto-beam; **NaN when no fixed beam holds speech** |
| `AEC_FIXEDBEAMSAZIMUTH_VALUES` | 33/81 | 2 x float32 **rw** | **aim two beams at chosen azimuths** |
| `AEC_FIXEDBEAMSGATING` | 33/83 | uint8 **rw** | gate on speech energy; **silences inactive beams** |

Beam order everywhere is **beam 1, beam 2, free-running, auto-select**.

**The single bearing cannot separate overlapping speakers, but the four beams
can carry evidence that it cannot.** `DOA_VALUE` is one dominant direction; a
second person talking over the first does not appear in it at all.
`AEC_SPENERGY_VALUES` reports speech energy on four beams at once, so two
talkers at different bearings light different beams. That is spatial evidence
independent of the embedding and Sortformer lanes — a different failure mode,
which is what makes it worth having, since agreement between two lanes that
fail the same way is not accuracy.

**The writable pair is the interesting one for a booth.** With two speakers at
known positions, `AEC_FIXEDBEAMSAZIMUTH_VALUES` aims a beam at each and
`AEC_FIXEDBEAMSGATING` silences whichever is not carrying speech. That is
hardware-side separation before any model runs. It also hard-codes a seating
plan, so it is a booth-day decision, not a default.

**Nothing here has been tested against two real simultaneous talkers.** Every
reading in this repo was taken in a room with at most one speaker, often
none. The beam layout, the energy scale and whether beams resolve two nearby
people are all unmeasured. Treat the table as a signal inventory, not as
evidence any of it discriminates speakers.

### The read-corruption hazard — read this before consuming any of it

**Reading two DIFFERENT commands in quick succession intermittently returns
one command's data for the other.** Measured: 3/12 corrupt at no gap, 1/12 at
150 ms, 0/12 at both 50 ms and 300 ms. **The corruption does not fall off with
spacing**, so no delay makes it safe and a sleep is not a fix. Speech energies
of **89562** and **228089** appeared where a few units were expected.

Reading the *same* command repeatedly is stable — six back-to-back reads
returned identical values — so the hazard is specific to interleaving.

**Range-check every read, and reject rather than wrap.** `xvf_control` does
this: `beam_speech_energy()` returns None outside `[0, 1000)`, and
`read_bearing()` returns None outside `0..359` instead of taking `% 360`. That
modulo was a real bug: the observed 89562 wraps to **282 degrees**, a
perfectly plausible bearing pointing at nobody. A corrupt read must become an
absent field, never a confident one.

**A four-beam table that alternates is this artifact, not four beams.** The
first capture taken here alternated all-zeros with `0, 2.234, 1.842, 2.234`
on exactly every other read, and azimuth[0] flipped between 128.0 and 0.0.
It looked like clean structured data.

## The Pi captures this array 8x too fast — and the fix

**Applied 2026-08-12; if you re-flash the card you must apply it again.** The Pi
enumerates the XVF3800 at USB high speed, but its descriptors are written for
full speed — `bInterval 1` then means one packet per 125 us microframe instead
of per 1 ms frame, which is exactly 8x. Audio arrives eight times faster than
real time and no recognizer can produce words from it.

```bash
# on the Pi: append to the single line in /boot/firmware/cmdline.txt, then reboot
dwc_otg.speed=1
```

Back the file up first and verify byte for byte before rebooting: it is one line
with no trailing newline and it contains a `;`, so edit it in Python rather than
with shell `echo` — the Pi is headless and a malformed `cmdline.txt` needs a card
reader to recover. Confirm afterwards:

```bash
grep -o dwc_otg.speed=1 /proc/cmdline
cat /sys/bus/usb/devices/1-1/speed      # 12 = full speed. 480 means it did not take
arecord -D hw:1,0 -d 4 /tmp/t.wav       # should take ~4s, not ~0.5s
```

Full speed is ample here: 12 Mbps against 16 kHz stereo 16-bit is 512 kbps, and
the descriptors were written for it. **Resampling on the node is not an
alternative** — the 8x stream is not a clean time-scaling and decimating it
produces a confident, wrong-sounding result.

## Failure modes worth knowing

**The Pi is nowhere on the network** — check the Mac's own subnet first with
`ipconfig getifaddr en0`. A laptop that roams between a phone hotspot
(`172.20.10.0/28`) and a router (`192.168.0.0/24`) will sweep the wrong /24 and
find nothing, which looks identical to a Pi that never joined. This has already
cost one debugging session.

**`ssh: connect to host ... port 22: Connection refused` right after flashing**
— first boot is still applying the Imager customisation and reboots partway
through. It answers ping before it answers SSH. Wait a minute and retry before
concluding SSH was never enabled.

**`[live] node dropped N blocks`** — the Pi could not keep up, or the uplink
stalled. TCP does not lose data mid-stream, so a sequence gap means the *node*
dropped audio. It is surfaced as an `AudioChunk.discontinuity` rather than
concatenated silently, because live capture is lossless by rule. Persistent
drops mean the Pi is overloaded: drop `--channels`, or check WiFi.

**Captions fine, compass says `Awaiting array`** — DoA is not being read.
Direction is deliberately *omitted* rather than defaulted, so this is the
system being honest, not a rendering bug. Check `--doa-cmd` against
`probe_array.py`.

**Motors silent but cues logged** — `gpiozero` failed to open the pins; the
node prints `motors unavailable` at startup and continues, because a dead
haptic link must degrade to no vibration rather than interrupt captions.

**The Pi reboots when motors fire** — power. See above.

## What this changed elsewhere

- **`--host` defaults to `127.0.0.1`.** "Local and offline by default" is a hard
  rule; the node needs a LAN address, so widening the bind is explicit and
  opt-in. It reaches nothing beyond the LAN — no internet, no telemetry.
- **Spatial haptics were marked *Deferred* in `docs/RESEARCH.md`.** Real motors
  and a real array reverse that, but only in the salience-gated form: cues fire
  on `speaker_change`/`emphasis`, never continuously from raw DoA, which is the
  distraction *Tactile Emotions* (CHI '25) measured.
- **"Mono must display `awaiting array`; never fabricate direction"** still
  holds. It is now satisfied by real data when the array is present, and by
  omission when it is not.
