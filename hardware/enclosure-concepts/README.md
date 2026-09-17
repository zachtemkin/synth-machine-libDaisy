# Enclosure concepts

AI-generated (Gemini "nano banana") mood-board renders for a full enclosure
around the carrier board. They are style studies, not drawings: proportions,
key counts and labels drift, and every image carries a SynthID watermark.

Panel brief given to the generator, from `../README.md` and `../../synthMachine.cpp`:

- 13 chromatic keys C4..C5, laid out as one piano octave (8 naturals, 5 sharps)
- 6 aux buttons in a 2x3 block at the left; left pair = OCT- / OCT+
- 5 pots: WAVE, ATTACK, DECAY, SUSTAIN, RELEASE
- two Adafruit 1669 enclosed speakers, one per front corner
- one rear wall with USB-C, 3.5 mm headphone jack and the Seed's micro-USB
- 100 x 100 mm carrier board anywhere inside, optional panel status LED

| File | Idea |
|---|---|
| `concept-1-walnut-desktop.png` | Walnut cheeks, brushed aluminium top, 12 mm round panel buttons per note. Closest to the real parts (panel-mount buttons on spade leads). |
| `concept-2-pocket-speaker.png` | One-piece moulded off-white shell, silicone key pads, speaker-first proportions. |
| `concept-3-bent-steel.png` | Powder-coated bent steel wedge, chicken-head knobs, perforated grilles. Render shows too few keys. |
| `concept-4-3d-printed.png` | Two-tone 3D print, mechanical switches with keycaps, honeycomb grilles, ports on the side wall. |

Regenerate or iterate with the nano-banana skill, passing the existing PNG
with `--in` and describing the change.
