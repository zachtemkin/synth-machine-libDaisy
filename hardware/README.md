# synthMachine carrier board

One directory per board revision, each self-contained: a `gen_kicad.py` that
writes the schematic and placed PCB, `route.py` for Freerouting and the GND
pours, `fab.sh` for Gerbers and assembly files, and a README with the
details and the pin map.

| Directory | Status |
|---|---|
| `v0.3/` | Fabricated September 2026. The bench unit. Needs the HP_DET jumper and `HP_DET=adc`; see its README. |
| `v0.4/` | Next revision, generated and routed, not yet ordered. MOSFET mute and plug detect, STEMMA QT for encoders, SPI display header, USB ESD, SMD fuse, PCBWay BOM. |

`NEXT_REVISION.md` is the running list of changes across revisions: what
v0.4 fixed and what is still open. `enclosure-concepts/` holds enclosure
renders.

Firmware profiles: `make HW=carrier` targets v0.3, `make HW=carrier4`
targets v0.4 (see `../Makefile`).
