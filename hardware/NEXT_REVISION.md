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

## 2. A display header on a real SPI port

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

## 3. Worth considering

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
