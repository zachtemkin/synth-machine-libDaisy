# synthMachine carrier board v0.4

Revision of the carrier in `../v0.3/` (the boards that were fabricated in
September 2026). Same 100 x 100 mm outline, same Seed position, same key,
pot, speaker and jack headers, so the v0.3 panel wiring and enclosure cutouts
carry over. What changed comes straight from `../NEXT_REVISION.md`:

| Change | Parts | Why |
|---|---|---|
| Plug detect reaches 3V3 | Q1 is a 2N7002 MOSFET instead of the MMBT3904 | The BJT's base clamped HP_DET at 0.8 V so D13 never saw a plug. A gate draws no current. No more jumper, no `HP_DET=adc`. |
| Firmware mute on its own transistor | Q2 2N7002, R6 10k gate, R15 10k pull-up on MUTE; MUTE moves from D11 to D0 | Q1 and Q2 drains form a wired-OR on the amp's ~SHDN. The pull-up means the speakers are muted at reset, in DFU mode and after a crash; firmware drives D0 low to run them (push-pull, no tri-state trick). |
| I2C for encoders | J15 STEMMA QT (JST SH 4-pin) on I2C1: D11 SCL, D12 SDA; R16/R17 4k7 pull-ups, DNP | For the seesaw rotary-encoder breakouts. The breakouts carry pull-ups; the footprints are there if a long chain needs more. |
| Display header on real SPI | J9 1x8: GND, 3V3, 5V, SCK (A7), MOSI (A3), NSS (A8), D/C (D26), RST (D27) | SSD1306/SH1106 OLEDs with libDaisy's driver and DMA, or a Sharp memory LCD (CLK/DI/CS on the same three lines). |
| Pot 4 on A9 | J13 wiper -> A9 instead of A3 | A3 is SPI1 MOSI. The other four pots keep their pins. |
| USB ESD | U4 USBLC6-2SC6 behind the USB-C | Data lines were unprotected. |
| SMD fuse | F1 MF-MSMF250/16X-2, 1812 | The radial MF-R250 collided with the Seed socket. |
| Smaller expansion header | J8 1x10: HP_MUTE, A5, A6, A10, A11, HP_DET, MUTE, 3V3, 5V, GND | D26/D27/A7/A8 went to the display header. A6 is the suggested pin for the seesaw INT line. |
| Assembly-ready BOM | every part has an MPN or LCSC number | `fab.sh` writes `pcbway_bom.csv` / `pcbway_cpl.csv` so PCBWay can place the USB-C and the JST headers. |

Pot headers J11..J14 stay even though the plan is encoders on J15: they cost
nothing and keep the pot firmware usable on this board.

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
GitHub releases page were used, and both can live anywhere. The KiCad
Freerouting plugin's bundled jar (2.1.0) is older and untested here.

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
| D26, D27 | display D/C, RST |
| A5, A6, A10, A11 | spare, on J8 |
| D29, D30 | USB-C data (MIDI) |

## Ordering with assembly (PCBWay)

`fab.sh` writes `fab/pcbway_bom.csv` with an item per line: designators,
quantity, manufacturer part number, LCSC number, value, package and whether it
is SMD or through-hole. `fab/pcbway_cpl.csv` has both sides. Upload the
Gerber zip, the BOM and the CPL; on the quote, tick at least J1 (USB-C), the
19 K headers, J10..J14, J5/J6 and J15 for placement. The Seed sockets, C1 and
the jack can go in the same job or be hand-fitted. The v0.3 JLCPCB files are
still produced too, for the SMD-only economic route.

## Still to verify before ordering

1. J15's opening faces the right board edge in the render; confirm against
   the connector drawing that pin 1 (GND) is the pad nearest the top of the
   board, matching the STEMMA QT cable's black wire.
2. Q1/Q2 pinout: KiCad's `Q_NMOS_GSD` is gate 1, source 2, drain 3, which is
   the 2N7002's SOT-23 order. Check the LCSC part's datasheet agrees.
3. The 1812 fuse sits between the USB-C and the Seed socket; check the
   clearance against a real Seed3 in its sockets.
