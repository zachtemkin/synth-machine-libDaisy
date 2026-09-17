# Carrier board: changes for the next revision

Running list of things to change when the carrier board is respun. The v0.3
boards in production work with the firmware as of September 2026; everything
here is a nicety or a robustness fix, not a blocker.

## 1. Give MUTE its own transistor and a pull-up

**Problem.** MUTE (D11) and the headphone jack's plug-detect (HP_DET) both
feed the base of Q1 through 10k resistors (R6, R5), and HP_DET's pull-up R3
is 100k. Consequences on the current board:

- Driving MUTE low holds Q1 off and keeps the speakers on even with
  headphones in, because 10k to ground beats the 100k pull-up. Firmware
  therefore never drives it low: "unmute" is tri-state (pin set to input).
- The speakers default to *on* at reset. Firmware mutes as early as it can
  and beats the codec pop, but DFU mode, a crash or a hang leaves the
  speakers live.

**Fix.** A second MMBT3904 for MUTE: 10k base resistor from D11, emitter to
GND, collector on AMP_SD alongside Q1's. Add a 10k pull-up from MUTE to +3V3.
Then:

- the two mute sources are independent open-collector pull-downs, a proper
  wired-OR, and the jack always works regardless of what firmware does;
- firmware can use plain push-pull drive: high = mute, low = run;
- the speakers default to muted at reset, in DFU mode and after a crash, and
  turning them on is a deliberate act.

Two parts. Firmware change: `SpeakerAmp` on the carrier profile becomes
push-pull like the prototype, with inverted sense.

## 2. Let HP_DET reach a digital high (Q1 as a MOSFET)

**Problem.** Measured on a v0.3 board: HP_DET reads about 0.8 V with a plug
in, not 3V3. R3 (100k) pulls the node up through R5 (10k) into Q1's
base-emitter junction, so it can never rise above a diode drop plus a tenth
of the remaining swing. Q1 still turns on, so the hardware speaker mute
works, but D13 reads low either way and the firmware cannot tell a plug is
in. The work-around on v0.3 is a wire from EXP pin 8 to EXP pin 4 and
`make HP_DET=adc`, which reads the node through the ADC.

**Fix.** Make Q1 a small N-MOSFET (2N7002, SOT-23): gate from HP_DET through
R5, source to GND, drain on AMP_SD. A gate draws no current, so HP_DET goes
to the full 3V3 when the jack's contact opens and D13 reads it directly. The
MOSFET's threshold (about 1 to 2 V) is also well clear of the audio peaks on
the node while unplugged, which the BJT's 0.65 V was not. If item 1's second
transistor for MUTE is added, make that a 2N7002 as well and the two drains
form the wired-OR on AMP_SD. Firmware: `HP_DET=adc` becomes unnecessary; the
default D13 path works.

## 3. A display header on a real SPI port

**Problem.** The expansion header J8 brings out D26, D27 and A5..A8, and
none of those form a complete hardware SPI or I2C port. SPI1's clock and
chip-select are there (A7 = PA5, A8 = PA4) but its data-out is PA7, the A3
pot, or PB5, the C4 key. I2C1 is on D11/D12 or D13/D14: the speaker mute,
an unconnected pin, and the headphone detect and mute. So a display on the
current board has to be bit-banged, which is fine for a 128x64 monochrome
OLED (about 1 KB per frame) and too slow for a colour TFT (about 150 KB).

**Fix.** Free SPI1 and give it a header:

- move the A3 pot's wiper to A9 (D24), which is unused, so PA7 (A3) becomes
  SPI1 MOSI;
- add a display header J9 carrying SCK (A7), MOSI (A3), NSS (A8), a
  data/command line and a reset line (D26, D27, or two of A5/A6), +3V3, +5V
  and GND. Keep D26/D27 on J8 as well if they are used for the panel LED;
- firmware: `adcConfig[3]` moves to A9, and libDaisy's `OledDisplay` with
  the `SSD130x4WireSpiTransport` on SPI1 then drives the usual SSD1306 /
  SH1106 modules with DMA, and an ILI9341-class TFT becomes possible.

No second controller is needed for any of this: the Seed's 3V3 rail has a
few hundred milliamps of headroom shared with the headphone amp, an OLED
draws around 20 mA, and a TFT backlight can run from the +5V pin. Only a
large colour UI would justify a display module with its own processor.

**Sharp memory display (Adafruit 4694, 2.7" 400x240).** The other candidate,
and the one that reads best across a panel in room light. It needs only
clock, data and an active-high chip select plus power, its own clock ceiling
is 2 MHz, and it is line-addressed, so bit-banging from today's EXP header
(D26, D27, A5) is as fast as hardware SPI would be. It therefore works the
same on v0.3 and on the next revision, and the display header above should
carry its three lines too so either display can plug in. Things to plan for
in firmware rather than hardware: a 12 KB frame buffer, redraws spread over
several main-loop passes (a full frame is 50 to 100 ms on the wire, changed
lines only are quick), and a VCOM toggle at least once a second even when
nothing changes, which the breakout expects from software by default. It is
reflective with no backlight, so it is invisible in the dark; that is the
one case for the OLED instead.

## 4. Rotary encoders over I2C in place of pots 2 to 5

**Idea.** Keep the leftmost pot as an absolute master volume and replace the
other four with rotary encoders on Adafruit seesaw breakouts, connected over
STEMMA QT. Do this together with the display (item 3): an encoder has no
visible position, so it needs a screen or per-knob lighting to be usable.

**Why it fits this design.**

- Encoders are relative, so each pot bank keeps its own values and a turn
  nudges the current one. The takeover mechanism in the firmware goes away
  for those four controls, and switching banks can never make a sound jump.
- Every Adafruit encoder has a push button: select the bank, reset a value,
  or toggle coarse/fine. The four mode buttons then become free for other
  jobs (LFO retrigger, tap tempo).
- Each seesaw encoder has an RGB LED under the knob, which gives a colour
  per bank and level or LFO feedback before the display exists.

**Seesaw rather than direct encoders.** The breakout's own MCU does the
quadrature decoding and button debounce, so fast spins never drop steps, and
the panel wiring is one 4-wire cable. Direct encoders would take 12 Seed
pins and need polling at about 1 kHz, which the 10 ms main loop cannot do
without moving it into the audio callback or a timer.

**Which breakout.** The quad board (Adafruit 5752) is one part and one I2C
address, but its four encoders sit on the breakout at a fixed spacing, so it
dictates the knob layout. Four single boards (Adafruit 4991) chain over
STEMMA QT with jumper-selectable addresses and let the knobs go anywhere on
the panel. Prefer the singles unless the quad's spacing happens to fit.

**Board changes.**

- Free an I2C port: none is free on v0.3. Move the speaker mute from D11 to
  the unused D0, which frees D11/D12 as I2C1 SCL/SDA. A1..A4 then become
  spare, which also helps item 3.
- A STEMMA QT connector (JST SH 1.0 mm 4-pin, SMD) on a board edge, in the
  PCBWay assembly order. Footprints for 4.7k pull-ups on SCL/SDA, DNP by
  default since the breakouts carry their own.
- Optionally the seesaw INT line to a spare GPIO so firmware polls only when
  something moved; polling every 10 ms works without it.

**Firmware.** Reading four counts and four buttons at 400 kHz takes well
under a millisecond per pass. Add acceleration so a fast spin sweeps a
parameter across its range while a slow one gives fine steps; 24 detents
per turn is coarse on its own. The callback-side smoothing the effects
already have hides the stepped feel of detents on slow filter sweeps.

**Cautions.** Keep the I2C cable short and away from the speaker wires; the
class-D amp is a noise source and I2C has no tolerance for glitches. Wave
shape, which lives on the volume pot behind shift today, needs a new home,
probably an encoder bank or an encoder button.

## 5. Assembly and fit

- **Have PCBWay place the USB-C receptacle and the JST connectors.** The
  GCT USB4105 (J1) has 0.5 mm pitch pads and a pair of through-hole shell
  tabs, and hand-soldering it on the v0.3 board did not go well; the first
  unit runs from a USB-C breakout wired to F1 and the Seed socket instead.
  The 19 JST-XH key headers, the 5 pot headers and the 2 JST-PH speaker
  headers are simple but numerous. Order the next run with assembly for at
  least J1 and all the JST headers (K1..K19, J10..J14, J5/J6); the Seed
  sockets, C1, the jack and the fuse can go in the same job or stay hand
  fitted.
- **F1 collides with the Seed.** The Bourns MF-R250 radial PTC at (22, 12)
  overlaps the Seed's socket, so on v0.3 it cannot be fitted with the Seed
  in place. Either move F1 clear of the socket outline, toward the USB-C
  and away from U1 by at least the disc's radius plus a few millimetres, or
  change it to an SMD PTC of the same rating, for example the Bourns
  MF-MSMF250 (1812, 2.5 A hold), which is low enough to sit anywhere next to
  the port and can be placed by the assembler along with J1.

## 6. Worth considering

- **ESD protection on the USB-C data lines.** There is none today; the
  STM32's pins are left to absorb whatever a plug or a finger delivers. A
  USBLC6-2SC6 (SOT-23-6, low capacitance, LCSC C7519) next to J1: D+ and D-
  from the connector pass through its I/O pins on the way to the Seed, VBUS
  on its VBUS pin, GND on GND. Cheap insurance if the synth is plugged and
  unplugged often or handled by other people; the USB-C port checks out
  electrically without it.
- **Panel status LED.** The Seed's onboard LED now shows boot status (solid
  once running, three blinks if entered from DFU), but on the carrier the
  Seed is inside the enclosure. A panel LED on D26 or D27 from the expansion
  header, with a 1k series resistor, would make that visible.
- **HP_DET while unplugged.** The jack's tip switch ties HP_DET to the
  headphone amp's left output while nothing is plugged in, so audio peaks
  above about 0.65 V would gate the speaker amp through Q1. Firmware avoids
  this by keeping the headphone amp muted until a plug is detected, which
  works; a hardware alternative (RC on HP_DET before R5) would slow the
  plug-in mute, so it is not recommended unless the firmware approach proves
  troublesome.

## Not hardware problems (for the record)

- The prototype's USB-C MIDI failing was a charge-only cable plus data lines
  one header pin off. The carrier's USB-C has the CC pull-downs (R1/R2) and
  routes D29/D30 correctly.
- The Seed does not bring USB up after the ROM bootloader's DFU handoff.
  Press RESET after flashing. A firmware self-reset on boot was tried and
  made the board unbootable; leave it as a manual step.
