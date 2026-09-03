#!/usr/bin/env python3
"""
Autoroute synth_machine.kicad_pcb with Freerouting and add/fill the ground pours.

Run with KiCad's bundled Python (needs pcbnew):

  KICAD_PY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
  $KICAD_PY hardware/route.py --java /path/to/java --jar /path/to/freerouting.jar [--passes 100]
  $KICAD_PY hardware/route.py --pours-only        # keep the tracks, just rebuild the GND pours

Freerouting 2.x needs Java 25 (https://adoptium.net); the jar comes from
https://github.com/freerouting/freerouting/releases.

Pipeline: .kicad_pcb -> Specctra .dsn -> Freerouting -> .ses -> import -> GND pours -> fill -> save.
The pours are removed before export on purpose: KiCad exports zones as Specctra planes and
Freerouting then assumes the plane reaches every GND pad, which the real fill cannot do
between fine-pitch pads.  Without them GND gets proper tracks and vias; the pours are
re-added afterwards as extra copper.

gen_kicad.py overwrites the .kicad_pcb, so re-run this after regenerating.
"""
import argparse, os, subprocess, sys, time, uuid

HERE = os.path.dirname(os.path.abspath(__file__))
BOARD = os.path.join(HERE, "synth_machine.kicad_pcb")
POURS = [("B.Cu", "GND"), ("F.Cu", "GND")]


def add_pours(board_path, pours):
    """Append pour zones to the saved board as text (the ZONE python API is flaky across
    KiCad builds), then reload, fill and save."""
    import pcbnew
    sys.path.insert(0, HERE)
    from gen_kicad import BOARD_W, BOARD_H
    board = pcbnew.LoadBoard(board_path)
    for z in list(board.Zones()):
        board.Remove(z)
    netcodes = {}
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            netcodes.setdefault(pad.GetNetname(), pad.GetNetCode())
    pcbnew.SaveBoard(board_path, board)

    inset = 1.0
    pts = " ".join("(xy %.3f %.3f)" % (x, y) for x, y in
                   ((inset, inset), (BOARD_W - inset, inset), (BOARD_W - inset, BOARD_H - inset), (inset, BOARD_H - inset)))
    zones = []
    for layer, netname in pours:
        zones.append('(zone (net %d) (net_name "%s") (layer "%s") (uuid "%s") (hatch edge 0.5) (connect_pads (clearance 0.25)) '
                     '(min_thickness 0.25) (filled_areas_thickness no) (fill yes (thermal_gap 0.5) (thermal_bridge_width 0.5)) '
                     '(polygon (pts %s)))' % (netcodes[netname], netname, layer, uuid.uuid4(), pts))
    txt = open(board_path).read().rstrip()
    assert txt.endswith(")")
    open(board_path, "w").write(txt[:-1] + "\n" + "\n".join(zones) + "\n)\n")

    board = pcbnew.LoadBoard(board_path)
    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())
    pcbnew.SaveBoard(board_path, board)
    n_tracks = sum(1 for t in board.GetTracks() if t.GetClass() == "PCB_TRACK")
    n_vias = sum(1 for t in board.GetTracks() if t.GetClass() == "PCB_VIA")
    print("saved %s: %d track segments, %d vias, %d pours" % (board_path, n_tracks, n_vias, len(zones)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--java")
    ap.add_argument("--jar")
    ap.add_argument("--passes", type=int, default=100)
    ap.add_argument("--workdir", default=os.path.join(HERE, "route_tmp"))
    ap.add_argument("--pours-only", action="store_true", help="skip routing; just rebuild and fill the GND pours")
    args = ap.parse_args()

    if args.pours_only:
        add_pours(BOARD, POURS)
        return
    if not (args.java and args.jar):
        ap.error("--java and --jar are required for routing")

    import pcbnew
    os.makedirs(args.workdir, exist_ok=True)
    dsn = os.path.join(args.workdir, "synth_machine.dsn")
    ses = os.path.join(args.workdir, "synth_machine.ses")

    board = pcbnew.LoadBoard(BOARD)
    # clean slate: drop tracks, vias and pours so re-routing is repeatable
    for t in list(board.GetTracks()):
        board.Remove(t)
    for z in list(board.Zones()):
        board.Remove(z)
    if not pcbnew.ExportSpecctraDSN(board, dsn):
        sys.exit("DSN export failed")
    print("exported", dsn)

    cmd = [args.java, "-Djava.awt.headless=true", "-jar", args.jar, "-de", dsn, "-do", ses,
           "-mp", str(args.passes), "-l", "en"]
    print(" ".join(cmd))
    t0 = time.time()
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    print("\n".join(l for l in r.stdout.splitlines()[-25:] if "analytics" not in l.lower()))
    print("freerouting exit %d after %.0fs" % (r.returncode, time.time() - t0))
    if not os.path.exists(ses):
        sys.exit("no .ses produced")

    if not pcbnew.ImportSpecctraSES(board, ses):
        sys.exit("SES import failed")
    pcbnew.SaveBoard(BOARD, board)
    del board
    # pours in a fresh interpreter: reloading a board next to the routed one trips SWIG ownership bugs
    subprocess.check_call([sys.executable, os.path.abspath(__file__), "--pours-only"])


if __name__ == "__main__":
    main()
