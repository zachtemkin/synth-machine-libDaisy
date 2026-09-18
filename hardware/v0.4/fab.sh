#!/bin/sh
# Produce the fabrication package for synth_machine v0.4 (JLCPCB / PCBWay).
#   sh hardware/v0.4/fab.sh       -> hardware/v0.4/fab/synth_machine_gerbers.zip (+ BOMs, position CSVs)
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
"$CLI" sch export bom --fields "Reference,Value,Footprint,QUANTITY,LCSC,MPN" --labels "Refs,Value,Footprint,Qty,LCSC,MPN" \
  --group-by "Value,Footprint,LCSC,MPN" --ref-range-delimiter "" --exclude-dnp -o "$OUT/synth_machine_bom.csv" "$HERE/synth_machine.kicad_sch"
# JLCPCB assembly files: BOM (only parts with an LCSC number) and CPL (every such part on the top
# side, through-hole included: the JST headers and sockets are placed on the standard tier)
"$CLI" pcb export pos --format csv --units mm --side front -o "$OUT/_smd_pos.csv" "$HERE/synth_machine.kicad_pcb"
python3 - "$OUT" <<'PYEOF'
import csv, sys, os
out = sys.argv[1]
rows = list(csv.DictReader(open(os.path.join(out, "synth_machine_bom.csv"))))
with open(os.path.join(out, "jlcpcb_bom.csv"), "w", newline="") as f:
    w = csv.writer(f); w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
    for r in rows:
        if r.get("LCSC"):
            w.writerow([r["Value"], r["Refs"], r["Footprint"].split(":")[-1], r["LCSC"]])
assembled = {ref.strip() for r in rows if r.get("LCSC") for ref in r["Refs"].replace("-", ",").split(",")}
pos = list(csv.DictReader(open(os.path.join(out, "_smd_pos.csv"))))
with open(os.path.join(out, "jlcpcb_cpl.csv"), "w", newline="") as f:
    w = csv.writer(f); w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
    # JLCPCB's zero angle for TSSOP/TDFN/QFN/SOIC bodies is 90 deg off KiCad's (their model
    # appears rotated 90 deg CCW in the placement preview), so pre-rotate those by -90.
    import re
    def jlc_rot(pkg, rot):
        if re.search(r"TSSOP|TDFN|QFN|DFN|SOIC|SOP", pkg):
            return (float(rot) - 90.0) % 360.0
        return float(rot)
    for p in pos:
        if p["Ref"] in assembled:
            w.writerow([p["Ref"], p["PosX"], p["PosY"], "Top" if p["Side"] == "top" else "Bottom",
                        "%.1f" % jlc_rot(p["Package"], p["Rot"])])
os.remove(os.path.join(out, "_smd_pos.csv"))
print("jlcpcb_bom.csv / jlcpcb_cpl.csv written")
PYEOF
# PCBWay assembly files: one BOM with every part (SMD and through-hole) carrying an MPN or an
# LCSC number, and a CPL for both sides.  PCBWay quotes from the BOM; tick the lines you want
# placed (the connectors are the point of v0.4's assembly order) and they source the rest.
"$CLI" pcb export pos --format csv --units mm --side both -o "$OUT/_all_pos.csv" "$HERE/synth_machine.kicad_pcb"
python3 - "$OUT" <<'PYEOF'
import csv, sys, os
out = sys.argv[1]
rows = list(csv.DictReader(open(os.path.join(out, "synth_machine_bom.csv"))))
with open(os.path.join(out, "pcbway_bom.csv"), "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["Item", "Designator", "Qty", "Manufacturer Part Number", "LCSC Part #", "Value", "Package", "Type"])
    n = 0
    for r in rows:
        n += 1
        pkg = r["Footprint"].split(":")[-1]
        kind = "THT" if any(k in pkg for k in ("THT", "PinHeader", "JST_XH", "JST_PH", "Radial", "Jack", "DaisySeed")) else "SMD"
        w.writerow([n, r["Refs"], r["Qty"], r.get("MPN", ""), r.get("LCSC", ""), r["Value"], pkg, kind])
wanted = {ref.strip() for r in rows for ref in r["Refs"].replace("-", ",").split(",")}
pos = list(csv.DictReader(open(os.path.join(out, "_all_pos.csv"))))
with open(os.path.join(out, "pcbway_cpl.csv"), "w", newline="") as f:
    w = csv.writer(f); w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation", "Package"])
    for p in pos:
        if p["Ref"] in wanted:
            w.writerow([p["Ref"], p["PosX"], p["PosY"], "Top" if p["Side"] == "top" else "Bottom", p["Rot"], p["Package"]])
os.remove(os.path.join(out, "_all_pos.csv"))
print("pcbway_bom.csv / pcbway_cpl.csv written")
PYEOF
# 1:1 test print on 11x17 (tabloid, landscape): outline, fab layer with pad outlines and actual
# hole sizes, board shifted to the centre of the page so printer margins never clip it.
KPY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
"$KPY" - "$HERE/synth_machine.kicad_pcb" "$OUT/_ledger.kicad_pcb" <<'PYEOF' 2>/dev/null
import sys, pcbnew
src, dst = sys.argv[1], sys.argv[2]
b = pcbnew.LoadBoard(src)
PAGE_W, PAGE_H = 431.8, 279.4                      # 17 x 11 in
xs, ys = [], []
for d in b.GetDrawings():
    if d.GetLayer() == pcbnew.Edge_Cuts:
        for pt in (d.GetStart(), d.GetEnd()):
            xs.append(pcbnew.ToMM(pt.x)); ys.append(pcbnew.ToMM(pt.y))
dx = (PAGE_W - (max(xs) - min(xs))) / 2 - min(xs)
dy = (PAGE_H - (max(ys) - min(ys))) / 2 - min(ys)
v = pcbnew.VECTOR2I(pcbnew.FromMM(dx), pcbnew.FromMM(dy))
for coll in (b.GetFootprints(), b.GetTracks(), b.GetDrawings(), b.Zones()):
    for item in list(coll):
        item.Move(v)
pcbnew.SaveBoard(dst, b)
PYEOF
sed -i '' 's/(paper "[^"]*"[^)]*)/(paper "USLedger")/' "$OUT/_ledger.kicad_pcb"
"$CLI" pcb export pdf --layers "Edge.Cuts,F.Fab,Cmts.User" --sketch-pads-on-fab-layers --exclude-value \
  --black-and-white --drill-shape-opt 2 --scale 1 --mode-single -o "$OUT/synth_machine_1to1_11x17.pdf" "$OUT/_ledger.kicad_pcb"
rm -f "$OUT/_ledger.kicad_pcb"
echo "fab package in $OUT"
ls -la "$OUT" "$GERB"
