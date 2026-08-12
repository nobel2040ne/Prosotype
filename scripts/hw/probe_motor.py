#!/usr/bin/env python3
"""Phase 0 probe: can a coin motor be driven, and does the ring read as a ring?

Run this ON THE PI. It does three things, in increasing risk order: print the
required circuit, buzz one motor, then sweep the ring so you can feel whether
the directions are actually distinguishable.

    python3 scripts/hw/probe_motor.py --wiring        # circuit only, no GPIO
    python3 scripts/hw/probe_motor.py --gpio 17       # buzz one motor
    python3 scripts/hw/probe_motor.py --ring 17,27,22,23 --sweep

DO NOT CONNECT A MOTOR DIRECTLY TO A GPIO PIN. A Pi GPIO sources about 16 mA;
a 2.7 mm coin motor draws 60-100 mA at stall and is an inductive load, so a
direct connection browns out the pin at best and takes the SoC with it at
worst. The `--wiring` output is the circuit that does work.
"""

from __future__ import annotations

import argparse
import sys
import time

WIRING = """
================================================================
  DRIVING A COIN MOTOR FROM A PI — the circuit
================================================================

  A GPIO pin cannot drive this motor. It sources ~16 mA; the motor
  wants 60-100 mA at stall, and it is inductive, so switching it
  off induces a reverse spike that will damage the pin.

  Use a ULN2803A darlington array. It is the right part here
  because it has EIGHT channels and INTERNAL flyback diodes, so a
  four-motor ring needs one chip and no discrete diodes.

      Pi 5V  ────────────────┬──────────────┐
                             │              │
                          [MOTOR]        [MOTOR]   ... up to 8
                             │              │
      Pi GPIO17 ──[1B]  ULN2803A  [1C]──────┘
      Pi GPIO27 ──[2B]           [2C]──────────────┘
                        [COM] ───┴── to Pi 5V   (flyback return)
                        [GND] ───── to Pi GND

    - ULN2803A pin 9  (COM)  -> 5V, same rail as the motors
    - ULN2803A pin 10 (GND)  -> Pi GND, COMMON GROUND IS REQUIRED
    - Motor +  -> 5V,  Motor -  -> the matching [nC] output pin

  POWER: four motors at ~80 mA is ~320 mA on the 5V rail. A Pi
  Zero 2 W plus the array is already drawing; use a supply with
  real headroom (2.5 A+) or the Pi will brown out mid-demo, which
  looks exactly like a software crash.

  INTENSITY: the Pi Zero 2 W has only TWO hardware PWM channels.
  For more than two motors with intensity control you need software
  PWM (gpiozero's default, which is what this probe and the node
  use) or a PCA9685 expander. Software PWM jitters under load; if
  the ring feels rough, install pigpio and set it as gpiozero's pin
  factory before reaching for different motors.

  ONE MOTOR CANNOT ENCODE DIRECTION. Two gives left/right; four
  gives a usable ring. If you have one, the honest mapping is
  salience only -- pulse on speaker change and emphasis, and say
  nothing about where.
================================================================
"""


def _gpio(pins: list[int]):
    """Open a PWM-capable handle per pin, preferring pigpio.

    gpiozero's PWMOutputDevice works on any pin via software PWM and is what
    Raspberry Pi OS ships, so it is the default. pigpio gives steadier timing
    if the daemon is running, which matters for a smooth ramp.
    """
    try:
        from gpiozero import PWMOutputDevice
    except Exception as e:                                   # noqa: BLE001
        raise SystemExit(
            f"gpiozero unavailable ({e}) — sudo apt install python3-gpiozero"
        ) from e
    return [PWMOutputDevice(p) for p in pins]


def buzz(dev, intensity: float, seconds: float) -> None:
    dev.value = max(0.0, min(1.0, intensity))
    time.sleep(seconds)
    dev.value = 0.0


def probe_one(pin: int) -> None:
    print(f"Driving GPIO{pin}. If nothing moves, check the circuit above.\n")
    dev, = _gpio([pin])
    try:
        for level in (0.35, 0.6, 1.0):
            print(f"  {int(level * 100):3d}% for 0.4s")
            buzz(dev, level, 0.4)
            time.sleep(0.3)

        print("\n  Two pulse shapes the design uses — they must feel DIFFERENT:")
        print("    speaker_change: two short taps")
        for _ in range(2):
            buzz(dev, 0.9, 0.06)
            time.sleep(0.09)
        time.sleep(0.6)
        print("    emphasis:       one soft swell")
        for i in range(20):
            dev.value = 0.7 * (1 - abs(i - 10) / 10)
            time.sleep(0.02)
        dev.value = 0.0
    finally:
        dev.value = 0.0
        dev.close()
    print("\n  If those two are not distinguishable by feel, the mapping needs")
    print("  more contrast — that is a design finding, record it.")


def probe_ring(pins: list[int], sweep: bool) -> None:
    print(f"Ring of {len(pins)} motors on GPIO {pins}.")
    if len(pins) < 2:
        print("\n  WARNING: one motor cannot encode direction. Nothing below")
        print("  will be meaningful as a bearing.")
    step = 360 / max(1, len(pins))
    print(f"  Each motor covers {step:.0f}deg; motor 0 is FRONT (0deg).\n")
    devs = _gpio(pins)
    try:
        for i, dev in enumerate(devs):
            print(f"  motor {i} — {i * step:5.0f}deg")
            buzz(dev, 0.9, 0.35)
            time.sleep(0.35)

        if not sweep:
            return
        print("\n  Sweeping a bearing around the ring. Each position cross-fades")
        print("  between the two nearest motors, which is what makes a 4-motor")
        print("  ring read as continuous rather than as four buzzers.")
        print("  Ctrl-C to stop.\n")
        try:
            angle = 0.0
            while True:
                for i, dev in enumerate(devs):
                    # Angular distance to this motor, wrapped into +/-180.
                    d = abs(((angle - i * step) + 180) % 360 - 180)
                    # Linear cross-fade over one motor spacing.
                    dev.value = max(0.0, 1.0 - d / step) * 0.9
                if int(angle) % 30 == 0:
                    print(f"    {angle:5.0f}deg")
                angle = (angle + 2) % 360
                time.sleep(0.03)
        except KeyboardInterrupt:
            print("\n  stopped")
    finally:
        for dev in devs:
            dev.value = 0.0
            dev.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wiring", action="store_true",
                    help="print the circuit and exit (touches no hardware)")
    ap.add_argument("--gpio", type=int, default=None,
                    help="BCM pin of a single motor to buzz")
    ap.add_argument("--ring", default=None, metavar="P1,P2,...",
                    help="BCM pins of the motor ring, clockwise from front")
    ap.add_argument("--sweep", action="store_true",
                    help="with --ring: sweep a bearing around the ring")
    args = ap.parse_args()

    print(WIRING)
    if args.wiring or (args.gpio is None and args.ring is None):
        print("Nothing driven. Pass --gpio N or --ring P1,P2,... to test motors.")
        return 0

    if args.ring:
        probe_ring([int(p) for p in args.ring.split(",") if p.strip()], args.sweep)
    else:
        probe_one(args.gpio)

    print("\nRecord the working pins in config.yaml under haptics.motors,")
    print("with each motor's angle_deg, and in docs/HARDWARE.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
