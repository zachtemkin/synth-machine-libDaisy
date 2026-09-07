# Speaker & headphone wiring

Adds a MAX98306 class-D amp ([Adafruit 987](https://www.adafruit.com/product/987)) and the
3 W / 4 Ω enclosed speaker pair ([Adafruit 1669](https://www.adafruit.com/product/1669)) to the
synth, with a headphone jack that automatically silences the speakers when a plug is inserted.

## Signal path

```
Seed AUDIO OUT L/R ──► switched TRS jack ──► MAX98306 (L+/R+) ──► speakers
      (pins 18/19)        │    (tip/ring       (BTL outputs)
                          ▼     switch contacts
                     headphones  open when a plug is in → speakers go silent)

Seed D11 (pin 12) ──► MAX98306 SD   (amp held muted during boot, then released)
USB-C VBUS (5 V) ──► MAX98306 VDD   (never 3v3A / 3v3D)
```

Headphone muting is purely mechanical — the jack's normally-closed contacts feed the
amp, so nothing in firmware has to know a plug went in. The firmware only drives **SD**
to keep the codec's start-up pop off the speakers.

## Parts

Already on hand: Daisy Seed (rev 4/5/7), MAX98306 breakout, 3 W 4 Ω speaker set, USB-C port wired to VIN.

Still needed:

| Part | Why |
|---|---|
| **Stereo 3.5 mm jack with switch contacts on tip *and* ring** (e.g. CUI SJ1-3525N, Thonk PJ366ST) | The NC contacts route audio to the amp only while no plug is inserted. A plain 3-pin jack can't do this. |
| 470–1000 µF electrolytic, ≥ 6.3 V | Bulk cap across amp VDD/GND; class-D current is pulsed and USB cables are thin. |
| 2 × 100 kΩ resistors | Keep the amp inputs from floating (and buzzing) when headphones are in. |
| Optional: dual-gang 10 kΩ audio-taper pot | Master volume in front of the jack, so it controls both headphones and speakers. |

## Net list

Seed numbers are **physical header pins** (1–40), not `Dxx` names.

| # | From | To | Notes |
|---|---|---|---|
| 1 | Seed pin 18 `AUDIO OUT L` | Jack **T** (tip) | Line level, AC-coupled, 100 Ω source |
| 2 | Seed pin 19 `AUDIO OUT R` | Jack **R** (ring) | |
| 3 | Seed pin 20 `AGND` | Jack **S** (sleeve) | Audio ground |
| 4 | Jack **TN** (tip switch, NC) | Amp `L+` | Connected only when no plug is in |
| 5 | Jack **RN** (ring switch, NC) | Amp `R+` | " |
| 6 | Seed pin 20 `AGND` | Amp `L-` **and** `R-` | Single-ended input → tie the – inputs to the *Seed's* analog ground, not the amp's power ground. The amp's differential input then rejects ground noise. |
| 7 | 100 kΩ | Amp `L+` ↔ `L-`, Amp `R+` ↔ `R-` | One per channel, right at the amp header |
| 8 | USB-C **VBUS** (5 V) — same node as Seed pin 39 `VIN` | Amp `VDD` | 2.7–5.5 V max. If VIN ever gets more than 5.5 V, the amp dies. |
| 9 | USB-C **GND** / Seed pin 40 `GND` | Amp `GND` | Power ground. Run it as its own wire back to the USB-C ground; don't daisy-chain through the audio ground. |
| 10 | 470–1000 µF | Amp `VDD` ↔ `GND` | Stripe (–) to GND, as close to the amp as possible |
| 11 | Seed pin 12 `D11` | Amp `SD` | Open-drain in firmware; the breakout's 10 kΩ pull-up to VDD takes it high. D11 is 5 V-tolerant. |
| 12 | Amp `OUTL+ / OUTL-` | Left speaker + / – | Cut the JST-PH plug off the speaker cable, screw the leads into the terminal blocks |
| 13 | Amp `OUTR+ / OUTR-` | Right speaker + / – | Keep polarity the same on both speakers |
| 14 | Seed pin 20 `AGND` | Seed pin 40 `GND` | Datasheet requires AGND tied to DGND — do this once, near the Seed |

Amp breakout header, left to right as silkscreened: `G  G'  R+  R-  L-  L+  SD  GND  VDD`.
Leave `G` / `G'` unconnected.

**Gain jumper: start with no jumper (6 dB).** The Seed's full-scale output is 3.6 Vpp, and
the synth sits at full scale whenever a note is held, so 6 dB already gives ≈ 1.6 W per
channel into 4 Ω. 9 dB is the amp's ceiling (≈ 2.8 W) and will clip on peaks; 12 dB and
up clip hard. Square and saw waves are the loudest — test gain with those.

## Headphones

Headphones are driven straight from the Seed's line outputs. Two consequences:

- **Level:** ≈ 0.3 Vrms into 32 Ω (≈ 3 mW) — loud enough for earbuds and most portable
  headphones, moderate for big over-ears. Higher-impedance headphones get *more* signal.
- **Bass:** the Seed's 4.7 µF output caps form a high-pass with low-impedance headphones —
  about 250 Hz into 32 Ω, 100 Hz into 250 Ω. On 32 Ω headphones the lowest notes of this
  synth (C4 = 262 Hz) will sound thin. Speakers and line-level gear are unaffected.

If headphone sound matters, put a small headphone amp (TPA6132A2 / TPA6130A2 breakout, or
a CMoy-style op-amp board) between the Seed outputs and the jack's T/R pins. Its ~10 kΩ+
input impedance removes the roll-off and it can drive any headphones properly. The jack's
switch contacts still route to the MAX98306 exactly as above.

An existing plain line-out jack can stay wired in parallel with T/R/S — plugging a mixer
into it won't mute the speakers, which is usually what you want.

## Power budget

At 6 dB with every voice held on square waves both channels together draw about 0.75 A
from 5 V; normal playing is far lower. A USB-C wall charger doesn't care. A computer's
USB 2.0 port (500 mA nominal) usually copes but may brown out at full volume — if the Seed
resets when you mash keys, use a charger or turn the gain down. The bulk cap (net 10)
matters here.

## Firmware

This wiring is the **prototype** hardware profile, which is what a plain `make`
builds. `synthMachine.cpp` drives D11 open-drain, holds it low from the first
instruction (before the Seed's own init brings the codec up) until 200 ms after
the audio callback starts, then releases it. Flash with the Seed in DFU mode
(hold BOOT, tap RESET, release BOOT):

```bash
make program-dfu
```

Then press RESET on the Seed: it does not bring USB up after the DFU handoff,
so MIDI only appears after a reset.

`SetSpeakersEnabled(false)` can be used as a software mute if you ever want one.

The carrier board (`hardware/`) wires D11 differently and adds a headphone jack
on D13/D14; build for it with `make HW=carrier`. See `hardware/README.md`.

## First power-up

1. Amp: **no gain jumper**, speakers connected, `SD` wired, nothing in the headphone jack.
2. Double-check that nothing but a speaker touches any `OUT` terminal. The outputs are
   bridge-tied: shorting an output to ground, to the other channel, or into a headphone
   jack will damage the amp.
3. Power from a wall charger first. Measure amp `VDD`: expect 4.8–5.2 V.
4. Play a note. Both speakers should sound and be in phase (bass gets *weaker* if you swap
   one speaker's polarity — fix the wiring if so).
5. Plug headphones in: speakers stop, headphones play. Unplug: speakers return.
6. Only then try 9 dB if you want it louder, and listen for clipping on square/saw.

## Don'ts

- Don't connect amp `OUT` pins to ground, to each other, or to any jack.
- Don't power the amp from the Seed's 3v3A or 3v3D pins.
- Don't feed VIN anything above 5.5 V while the amp shares that rail.
- Don't run the speaker leads bundled with the pot wiring; the amp output is a 360 kHz
  PWM square wave. Twist each speaker pair.
