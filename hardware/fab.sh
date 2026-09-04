#!/bin/sh
# Produce the fabrication package for synth_machine (JLCPCB / PCBWay).
#   sh hardware/fab.sh            -> hardware/fab/synth_machine_gerbers.zip (+ BOM, position CSV)
# Settings follow JLCPCB's and PCBWay's KiCad guides: Protel extensions, solder mask
# subtracted from silk, no netlist attributes, Excellon drill in mm with PTH+NPTH merged.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
CLI=/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli
OUT="$HERE/fab"
GERB="$OUT/gerbers"
rm -rf "$OUT"; mkdir -p "$GERB"

"$CLI" pcb export gerbers \
  --layers "F.Cu,B.Cu,F.Paste,B.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts" \
  --subtract-soldermask --no-netlist --check-zones \
  -o "$GERB/" "$HERE/synth_machine.kicad_pcb"
"$CLI" pcb export drill --format excellon --excellon-units mm --drill-origin absolute \
  --generate-map --map-format pdf -o "$GERB/" "$HERE/synth_machine.kicad_pcb"
(cd "$GERB" && zip -q -r "../synth_machine_gerbers.zip" .)

"$CLI" pcb export pos --format csv --units mm --side both -o "$OUT/synth_machine_pos.csv" "$HERE/synth_machine.kicad_pcb"
"$CLI" sch export bom --fields "Reference,Value,Footprint,QUANTITY" --labels "Refs,Value,Footprint,Qty" \
  --group-by "Value,Footprint" -o "$OUT/synth_machine_bom.csv" "$HERE/synth_machine.kicad_sch"
echo "fab package in $OUT"
ls -la "$OUT" "$GERB"
