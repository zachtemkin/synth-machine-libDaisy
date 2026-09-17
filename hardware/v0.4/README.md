# synthMachine carrier board v0.4

Second revision of the carrier. v0.3 in `../v0.3/` is the board that was
fabricated in September 2026; v0.4 applies everything in `../NEXT_REVISION.md`
and adds onboard battery power. It is a new outline: 160 x 74 mm landscape
instead of 100 x 100, with all 19 key headers in one row along the bottom
edge in panel order. The USB-C, the Seed's own USB and the headphone jack
still share the top edge.

![PCB render](pcb_render.png)

| Change | Parts | Why |
|---|---|---|
| One row of key headers | K1..K19 along the bottom at 7 mm pitch, diode above each, name below | Every button lead is the same length and points the same way. The headers are rotated so the row is 132 mm wide and the corners stay free for mounting holes. |
| Battery power | J17 JST-PH cell, U5 BQ24074 charger with power path, U6 TPS61023 5 V boost, J16 power-switch header, JP2 always-on jumper | Runs from a single LiPo, charges from the USB-C, and runs from USB while charging. See the power section below. |
| Plug detect reaches 3V3 | Q1 is a 2N7002 MOSFET | The v0.3 BJT clamped HP_DET at 0.8 V so D13 never saw a plug. No jumper, no `HP_DET=adc`. |
| Firmware mute on its own transistor | Q2 2N7002, R6 gate, R15 pull-up; MUTE on D0 | Muted at reset, in DFU and after a crash; firmware drives D0 low to run. Wired-OR with Q1. |
| I2C for encoders | J15 STEMMA QT on I2C1 (D11 SCL, D12 SDA); R16/R17 pull-ups DNP | For the seesaw rotary-encoder breakouts. |
| Display header | J9: GND, 3V3, 5V, SCK (A7), MOSI (A3), NSS (A8), D/C (D26), RST (D27) | Hardware SPI1 for an OLED or a Sharp memory LCD. Pot 4 moved to A9 to free A3. |
| USB ESD, SMD fuse | U4 USBLC6-2SC6, F1 1812 PTC on the USB input | Data lines were unprotected; the radial fuse collided with the Seed. |
| Assembly-ready BOM | every part has an MPN or LCSC number | `fab.sh` writes `pcbway_bom.csv` / `pcbway_cpl.csv`. |

The five pot headers stay (VOL on A0, then A1, A2, A9, A4) so the board works
with pots or with encoders on J15.

## Power

```
USB-C J1 -> F1 2.5 A PTC -> VUSB -> U5 BQ24074 IN
                                    U5 BAT  <-> J17 cell (+ C22)
                                    U5 OUT   -> VSYS (4.4 V on USB, else the cell)
VSYS -> L1 1 uH / U6 TPS61023 -> +5V (5.1 V) -> Seed VIN, speaker amp, J8/J9 5V pins
```

- **Charger.** EN2 high and EN1 low select the resistor-programmed input
  limit: R19 1.1k gives 1.5 A, and the charger's input-voltage loop backs off
  automatically on a weak USB port. R18 1.8k sets 0.5 A fast charge, which is
  0.25 C for a 2000 mAh cell and keeps the linear charger under 0.7 W. TMR and
  ITERM are left open for the default 30 min / 5 h safety timers and 10 %
  termination. CE is tied low, TS has the 10k that the part needs when there
  is no pack thermistor. The system runs from OUT while the cell charges, and
  the cell supplements USB on peaks.
- **Boost.** The TPS61023 makes 5.1 V from VSYS (750k/100k on a 0.6 V
  reference). It carries the whole load on USB as well as on battery, which is
  fine: from the charger's 4.4 V it is barely working. From a 3.3 V cell it
  delivers about 1.5 A continuous with the 470 uF C1 covering the amp's
  peaks. Inductor per TI's table (Coilcraft XEL4030-102ME); XGL4030-102MEC is
  the LCSC-stocked equivalent.
- **Switch.** J16 takes a panel SPST. Closed, it pulls the boost's EN up to
  VSYS through R28; open, R27 holds it low and everything downstream of the
  boost is off, while the charger keeps charging. The EN pin draws nothing,
  so any small switch works. JP2 bridges the switch for a bench board.
- **Firmware signals.** A10 reads VBAT/2 (R23/R24, 0 to 2.1 V). A5 reads
  ~CHG (low = charging) and A11 reads ~PGOOD (low = USB present), both
  open-drain with 100k pull-ups. Nothing in the firmware uses them yet.
- **Cell.** Single-cell LiPo on J17, pin 1 = +. Use a protected cell (the
  Adafruit and SparkFun packs are); there is no protection on the board.
  2000 mAh or more suits the speakers, which can pull over 1 A at volume.
- **Note.** The Seed's own USB port powers only the Seed; it cannot charge
  the cell or run the amp. That was already true on v0.3.

## Regenerate, route, fab

Same pipeline as v0.3, run from this directory:

```bash
KICAD_PY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
$KICAD_PY hardware/v0.4/gen_kicad.py                       # schematic + placed PCB
$KICAD_PY hardware/v0.4/route.py --java <java25> --jar freerouting-2.4.1.jar
$KICAD_PY hardware/v0.4/route.py --pours-only              # rebuild just the GND pours
sh hardware/v0.4/fab.sh                                    # Gerbers, BOMs, CPLs, test print
```

Freerouting 2.4.1 needs Java 25. Neither is installed system-wide on the
Mac; a portable Temurin JRE from adoptium.net and the jar from the Freerouting
GitHub releases page were used, and both can live anywhere. `PREROUTES` in
the generator carries the audio paths, the MAX98306 fan-out and short stubs
off the boost converter's 0.5 mm pitch pins, which the autorouter cannot reach
with power-width tracks on its own.

## Pin map (what the firmware profile `HW=carrier4` expects)

| Seed pin | Use |
|---|---|
| D0 | MUTE: high = speakers muted (default via R15), low = run |
| D1..D3 | matrix rows |
| D4..D9 | matrix columns |
| D10 | C4 key |
| D11, D12 | I2C1 SCL, SDA (STEMMA QT) |
| D13 | HP_DET, high = headphones plugged in |
| D14 | HP_MUTE, headphone amp ~MUTE, low = muted |
| A0 | volume pot |
| A1, A2, A9, A4 | pots 2, 3, 4, 5 |
| A3, A7, A8 | SPI1 MOSI, SCK, NSS (display) |
| A5 | ~CHG from the charger, low = charging |
| A6 | spare, on J8 (seesaw INT candidate) |
| A10 | battery voltage / 2 |
| A11 | ~PGOOD from the charger, low = USB present |
| D26, D27 | display D/C, RST |
| D29, D30 | USB-C data (MIDI) |

## Headers

| Ref | What | Pins |
|---|---|---|
| K1..K19 | keys, JST-XH 2-pin, bottom row in panel order | row / diode (any way round) |
| J10..J14 | pots, JST-XH 3-pin, right edge | 3V3A, wiper, GND |
| J5, J6 | speakers, JST-PH | + / - |
| J17 | battery, JST-PH | 1 = +, 2 = GND |
| J16 | power switch, JST-XH 2-pin | either way round |
| J15 | STEMMA QT | GND, 3V3, SDA, SCL |
| J9 | display | GND, 3V3, 5V, SCK, MOSI, NSS, D/C, RST |
| J8 | expansion | HP_MUTE, A6, HP_DET, MUTE, VSYS, 3V3, 5V, GND |

## Ordering with assembly (PCBWay)

`fab.sh` writes `fab/pcbway_bom.csv` with an item per line: designators,
quantity, manufacturer part number, LCSC number, value, package and whether it
is SMD or through-hole. `fab/pcbway_cpl.csv` has both sides. Upload the
Gerber zip, the BOM and the CPL; on the quote, tick at least J1 (USB-C), the
19 K headers, J10..J14, J5/J6, J16, J17 and J15 for placement. The Seed
sockets, C1 and the jack can go in the same job or be hand-fitted. The
JLCPCB files are still produced too, for the SMD-only economic route.

## Check before ordering

1. **J17 polarity** against the cell you will use: pin 1 is + here, and the
   silkscreen says so. A reversed cell destroys the charger.
2. **J15's opening** faces the right board edge in the render; confirm pin 1
   (GND) is the pad nearest the top of the board, matching the cable's black
   wire.
3. **Q1/Q2 pinout:** KiCad's `Q_NMOS_GSD` is gate 1, source 2, drain 3, the
   2N7002's SOT-23 order. Check the LCSC part's datasheet agrees.
4. **U5 thermal pad** has vias to the ground pour; make sure the assembler's
   stencil does not flood it.
5. **Enclosure:** the outline changed. The top edge still carries all three
   ports at the same spacing from the left edge as v0.3, but the board is
   60 mm wider and 26 mm shorter, and the mounting holes moved.
