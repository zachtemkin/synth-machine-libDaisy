#!/usr/bin/env python3
"""
Generates the KiCad 9 project for the synthMachine carrier board.

Run with KiCad's bundled Python so the PCB half can use pcbnew:

  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 gen_kicad.py

Outputs (all next to this script):
  synth_machine.kicad_pro / .kicad_sch / .kicad_pcb
  SynthMachine.kicad_sym            project symbol lib (Daisy Seed)
  SynthMachine.pretty/*.kicad_mod   project footprints (Seed, arcade button, amp breakout)
  sym-lib-table / fp-lib-table

The netlist below is the single source of truth; the schematic and the PCB are
both generated from it, and every footprint carries the schematic symbol's UUID
path so "Update PCB from Schematic" keeps working after you edit either side.

Pin usage mirrors synthMachine.cpp:
  matrix columns D4..D9, rows D1..D3, direct C4 key on D10, pots on A0..A4,
  external USB (MIDI) on D29/D30, audio out L/R -> amp + line out.
"""
import os, re, uuid, json, sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = "synth_machine"
KICAD_SHARE = "/Applications/KiCad/KiCad.app/Contents/SharedSupport"
SYMDIR = os.path.join(KICAD_SHARE, "symbols")
FPDIR = os.path.join(KICAD_SHARE, "footprints")

# ---------------------------------------------------------------------------
# Tunables you will probably want to touch
# ---------------------------------------------------------------------------
# Board = same outline as the panel drawing (Sketch 1): 234.95 x 161.925, R6 corners.
BOARD_W, BOARD_H, CORNER_R = 234.95, 161.925, 6.0
# Button grid, derived from the panel drawing (all mm, y measured from the TOP edge).
BTN_D = 23.6                              # panel hole
KEY_X0 = 8.0 + BTN_D / 2                  # 8 mm edge margin -> first white key centre
KEY_PITCH = (BOARD_W - 16.0 - BTN_D) / 7  # 8 white keys across the width  (27.907)
WHITE_Y = BOARD_H - (25.0 + BTN_D / 2)                          # 125.1
BLACK_Y = WHITE_Y - (BTN_D + 1.4)                               # 100.1
TOP_Y = BLACK_Y - (BTN_D + 25.0)                                # 51.5
POT_Y = TOP_Y - BTN_D / 2 - 12.5 - 3.5                          # 23.7  (O7 panel holes)
LED_XY = (KEY_X0 + 3.5 * KEY_PITCH, BOARD_H - 81.2)             # small hole above E/F gap
# Arcade button tabs: 2.8 x 0.5 mm, two tabs side by side.  The drawing gives 9.05 mm
# measured outer-edge to outer-edge (confirmed), tabs 2.8 mm wide.
TAB_PITCH = 9.05 - 2.8     # 9.05 mm outer-to-outer measured, 2.8 mm tabs -> 6.25 centre-to-centre
# Keystone 3534 vertical quick-fit receptacle (accepts .110 tab): two legs 3.7 mm apart,
# 1.65 mm holes, body 4.0 x 2.2 mm, 8 mm above the board, tab inserts 5 mm.
RECEPT_LEG_PITCH, RECEPT_HOLE = 3.7, 1.65

G = 2.54  # schematic grid


def U():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Netlist / component model
# ---------------------------------------------------------------------------
class Part:
    def __init__(self, ref, lib_id, value, footprint, pins, sch=(0, 0, 0), pcb=(0, 0, 0), desc="", lcsc=""):
        self.ref, self.lib_id, self.value, self.footprint = ref, lib_id, value, footprint
        self.lcsc = lcsc              # JLCPCB/LCSC part number for SMT assembly ("" = not assembled)
        self.pins = pins              # {pin_number: net or None}
        self.sch_at = sch             # (x, y, rot) schematic, in G units for x,y
        self.pcb_at = pcb             # (x, y, rot) mm
        self.desc = desc
        self.uuid = U()


PARTS = []


def add(*a, **k):
    p = Part(*a, **k)
    PARTS.append(p)
    return p


# --- Daisy Seed ------------------------------------------------------------
# name, electrical type, net
SEED_PINS = {
    1: ("D0", "bidirectional", None),
    2: ("D1", "bidirectional", "ROW0"),
    3: ("D2", "bidirectional", "ROW1"),
    4: ("D3", "bidirectional", "ROW2"),
    5: ("D4", "bidirectional", "COL0"),
    6: ("D5", "bidirectional", "COL1"),
    7: ("D6", "bidirectional", "COL2"),
    8: ("D7", "bidirectional", "COL3"),
    9: ("D8", "bidirectional", "COL4"),
    10: ("D9", "bidirectional", "COL5"),
    11: ("D10", "bidirectional", "KEY_C4"),
    12: ("D11", "bidirectional", "MUTE"),
    13: ("D12", "bidirectional", None),
    14: ("D13", "bidirectional", "HP_DET"),
    15: ("D14", "bidirectional", "HP_MUTE"),
    16: ("AUDIO_IN_L", "input", None),
    17: ("AUDIO_IN_R", "input", None),
    18: ("AUDIO_OUT_L", "output", "AUDIO_L"),
    19: ("AUDIO_OUT_R", "output", "AUDIO_R"),
    20: ("AGND", "power_in", "GND"),
    21: ("+3V3A", "power_out", "+3.3VA"),
    22: ("A0/D15", "bidirectional", "POT_WAVE"),
    23: ("A1/D16", "bidirectional", "POT_ATTACK"),
    24: ("A2/D17", "bidirectional", "POT_DECAY"),
    25: ("A3/D18", "bidirectional", "POT_SUSTAIN"),
    26: ("A4/D19", "bidirectional", "POT_RELEASE"),
    27: ("A5/D20", "bidirectional", "EXP_A5"),
    28: ("A6/D21", "bidirectional", "EXP_A6"),
    29: ("A7/D22", "bidirectional", "EXP_A7"),
    30: ("A8/D23", "bidirectional", "EXP_A8"),
    31: ("A9/D24", "bidirectional", None),
    32: ("A10/D25", "bidirectional", None),
    33: ("D26", "bidirectional", "EXP_D26"),
    34: ("D27", "bidirectional", "EXP_D27"),
    35: ("A11/D28", "bidirectional", None),
    36: ("D29/USB_D-", "bidirectional", "USB_DM"),
    37: ("D30/USB_D+", "bidirectional", "USB_DP"),
    38: ("+3V3D", "power_out", "+3V3"),
    39: ("VIN", "power_in", "+5V"),
    40: ("GND", "power_in", "GND"),
}

# Seed sits in the gap between the top-row button groups, USB end at the top edge.
add("U1", "SynthMachine:DaisySeed", "Daisy Seed", "SynthMachine:DaisySeed_2x20",
    {str(n): v[2] for n, v in SEED_PINS.items()}, sch=(38, 50, 0), pcb=(98.0, 27.5, 0),
    desc="Electrosmith Daisy Seed (rev 4/5/7), 2x20 0.1in headers on 0.6in centres")


def kx(i):
    return KEY_X0 + i * KEY_PITCH


# --- Keys ------------------------------------------------------------------
# name, note index in firmware, (col,row) or None for direct, pcb x, pcb y
# Bottom row = white keys, middle row = black keys, top row = 6 spare buttons
# on the 6 unused matrix positions (NOTE_MAPPING == -1 in synthMachine.cpp).
KEYS = [
    ("C4", None, kx(0), WHITE_Y), ("D4", (5, 1), kx(1), WHITE_Y), ("E4", (5, 2), kx(2), WHITE_Y),
    ("F4", (4, 2), kx(3), WHITE_Y), ("G4", (3, 2), kx(4), WHITE_Y), ("A4", (2, 2), kx(5), WHITE_Y),
    ("B4", (1, 2), kx(6), WHITE_Y), ("C5", (0, 2), kx(7), WHITE_Y),
    ("C#4", (5, 0), kx(0.5), BLACK_Y), ("D#4", (4, 1), kx(1.5), BLACK_Y), ("F#4", (3, 1), kx(3.5), BLACK_Y),
    ("G#4", (2, 1), kx(4.5), BLACK_Y), ("A#4", (1, 1), kx(5.5), BLACK_Y),
    ("BTN1", (0, 0), kx(0), TOP_Y), ("BTN2", (0, 1), kx(1), TOP_Y), ("BTN3", (1, 0), kx(4), TOP_Y),
    ("BTN4", (2, 0), kx(5), TOP_Y), ("BTN5", (3, 0), kx(6), TOP_Y), ("BTN6", (4, 0), kx(7), TOP_Y),
]
BTN_FP = "SynthMachine:ArcadeButton_24mm_Keystone3534"
DIODE_FP = "Diode_THT:D_DO-35_SOD27_P7.62mm_Horizontal"
dn = 1
for i, (name, mat, px, py) in enumerate(KEYS):
    row, col_i = divmod(i, 7)
    sx, sy = 78 + col_i * 20, 8 + row * 8
    dy = py + 18 if py == WHITE_Y else (py - 24 if py == BLACK_Y else py - 17)   # diodes in the free bands
    if mat is None:
        add("SW%d" % (i + 1), "Switch:SW_Push", "KEY %s (direct D10) - 2x Keystone 3534" % name, BTN_FP,
            {"1": "KEY_C4", "2": "GND"}, sch=(sx, sy, 0), pcb=(px, py, 0))
    else:
        c, r = mat
        mid = "K%s_D" % name.replace("#", "s")
        add("SW%d" % (i + 1), "Switch:SW_Push", "%s [c%d r%d] - 2x Keystone 3534" % (name, c, r), BTN_FP,
            {"1": "ROW%d" % r, "2": mid}, sch=(sx, sy, 0), pcb=(px, py, 0))
        # diode: anode (pin 2) to switch, cathode (pin 1) to column (columns are driven low)
        add("D%d" % dn, "Device:D", "1N4148", DIODE_FP,
            {"2": mid, "1": "COL%d" % c}, sch=(sx + 6, sy, 180), pcb=(px, dy, 0))
        dn += 1

# --- Pots: panel-mount, wired to 3-pin headers at the panel's O7 hole positions ---
# (the PCB sits ~31 mm below the panel because of the button receptacles, too far for
#  board-mounted 9 mm pots to reach the panel)
HDR3 = "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical"
POTS = [("J10", "POT_WAVE", "Wave", kx(0)), ("J11", "POT_ATTACK", "Attack", kx(4)), ("J12", "POT_DECAY", "Decay", kx(5)),
        ("J13", "POT_SUSTAIN", "Sustain", kx(6)), ("J14", "POT_RELEASE", "Release", kx(7))]
for i, (ref, net, label, px) in enumerate(POTS):
    add(ref, "Connector_Generic:Conn_01x03", "Pot %s (10k lin, panel mount)" % label, HDR3,
        {"1": "+3.3VA", "2": net, "3": "GND"}, sch=(78 + i * 12, 36, 0), pcb=(px - 2.54, POT_Y, 90))

# --- USB-C: MIDI data on D29/D30 (libDaisy EXTERNAL) and the only power input ------
add("J1", "Connector:USB_C_Receptacle_USB2.0_16P", "USB-C (MIDI + 5V power)",
    "Connector_USB:USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal",
    {"S1": "GND", "SH": "GND", "A1": "GND", "A12": "GND", "B1": "GND", "B12": "GND",   # shield pad is S1 (KiCad 9 lib) or SH (KiCad 10)
     "A4": "VBUS", "A9": "VBUS", "B4": "VBUS", "B9": "VBUS",
     "A5": "CC1", "B5": "CC2", "A6": "USB_DP", "B6": "USB_DP", "A7": "USB_DM", "B7": "USB_DM",
     "A8": None, "B8": None},
    sch=(20, 100, 0), pcb=(114.0, 3.675, 180))   # footprint "PCB Edge" line lands on y=0
R_FP = "Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal"
R_SMD = "Resistor_SMD:R_0805_2012Metric"
C_SMD = "Capacitor_SMD:C_0805_2012Metric"
add("R1", "Device:R", "5k1", R_SMD, {"1": "CC1", "2": "GND"}, sch=(40, 96, 0), pcb=(140.0, 18.0, 0), lcsc="C27834")
add("R2", "Device:R", "5k1", R_SMD, {"1": "CC2", "2": "GND"}, sch=(46, 96, 0), pcb=(140.0, 23.0, 0), lcsc="C27834")
add("F1", "Device:Polyfuse", "2A hold PTC (MF-R200)", "Fuse:Fuse_Bourns_MF-RG300",
    {"1": "VBUS", "2": "+5V"}, sch=(60, 100, 0), pcb=(140.0, 12.0, 0))
add("C1", "Device:C_Polarized", "470u 10V", "Capacitor_THT:CP_Radial_D8.0mm_P3.50mm",
    {"1": "+5V", "2": "GND"}, sch=(90, 100, 0), pcb=(92.0, 66.0, 0))
add("C6", "Device:C", "100n", "Capacitor_THT:C_Disc_D5.0mm_W2.5mm_P2.50mm",
    {"1": "+5V", "2": "GND"}, sch=(98, 100, 0), pcb=(92.0, 74.0, 0))

# --- Speaker amp: MAX98306 (TDFN-14, exposed pad) straight on the board ---------------
# Same circuit as Adafruit #987: 1u on every input (single-ended: the - inputs go to GND
# through their cap), 10u + 100n on PVDD, 100k pull-up on ~SHDN (Q1 pulls it low to mute),
# gain by the GAIN pin: R13 100k to PVDD = 9 dB.  JP1 lets you strap GAIN to PVDD (12 dB)
# or GND (18 dB) instead; leave R13 off and JP1 open for 6 dB.  EP + thermal vias to GND.
add("U3", "SynthMachine:MAX98306", "MAX98306ETD+T", "Package_DFN_QFN:TDFN-14-1EP_3x3mm_P0.4mm_EP1.78x2.35mm_ThermalVias",
    {"1": "GND", "8": "GND", "15": "GND", "2": "AMP_SD", "3": "AMP_INL", "4": "AMP_INLN", "5": "AMP_GAIN",
     "6": "AMP_INRN", "7": "AMP_INR", "9": "SPK_RN", "10": "SPK_RP", "11": "+5V", "12": "+5V", "13": "SPK_LP", "14": "SPK_LN"},
    sch=(120, 100, 0), pcb=(72.0, 20.0, 0), lcsc="C124549",
    desc="Analog Devices MAX98306 stereo 3.7W class-D amplifier, TDFN-14 3x3 EP")
add("C16", "Device:C", "1u", C_SMD, {"1": "AUDIO_L", "2": "AMP_INL"}, sch=(104, 94, 90), pcb=(65.0, 16.0, 0), lcsc="C28323")
add("C18", "Device:C", "1u", C_SMD, {"1": "GND", "2": "AMP_INLN"}, sch=(110, 94, 90), pcb=(65.0, 18.5, 0), lcsc="C28323")
add("C19", "Device:C", "1u", C_SMD, {"1": "GND", "2": "AMP_INRN"}, sch=(110, 106, 90), pcb=(65.0, 21.5, 0), lcsc="C28323")
add("C17", "Device:C", "1u", C_SMD, {"1": "AUDIO_R", "2": "AMP_INR"}, sch=(104, 106, 90), pcb=(65.0, 24.0, 0), lcsc="C28323")
add("C14", "Device:C", "10u", C_SMD, {"1": "+5V", "2": "GND"}, sch=(134, 94, 90), pcb=(82.0, 19.6, 0), lcsc="C15850")
add("C15", "Device:C", "100n", C_SMD, {"1": "+5V", "2": "GND"}, sch=(140, 94, 90), pcb=(82.0, 22.0, 0), lcsc="C49678")
add("R13", "Device:R", "100k", R_SMD, {"1": "AMP_GAIN", "2": "+5V"}, sch=(134, 106, 90), pcb=(72.0, 30.0, 0), lcsc="C17407")
add("R14", "Device:R", "100k", R_SMD, {"1": "AMP_SD", "2": "+5V"}, sch=(140, 106, 90), pcb=(79.0, 30.0, 0), lcsc="C17407")
add("JP1", "Jumper:SolderJumper_3_Open", "GAIN: 1-2 = 18dB, open = R13, 2-3 = 12dB",
    "Jumper:SolderJumper-3_P1.3mm_Open_RoundedPad1.0x1.5mm",
    {"1": "GND", "2": "AMP_GAIN", "3": "+5V"}, sch=(128, 112, 0), pcb=(72.0, 33.0, 0))
# Speaker outputs -> ferrite bead + 220p EMI filter (MAX98306 datasheet) -> JST-PH plugs.
FB_FP = "Inductor_THT:L_Axial_L5.3mm_D2.2mm_P7.62mm_Horizontal_Vishay_IM-1"
for i, sig in enumerate(["RN", "RP", "LP", "LN"]):   # order chosen so the B.Cu bus needs no crossings
    add("FB%d" % (i + 1), "Device:FerriteBead", "600R@100MHz", FB_FP,
        {"1": "SPK_" + sig, "2": "SPKF_" + sig}, sch=(150 + i * 8, 96, 90), pcb=(72.0, 46.0 + 4 * i, 0))
    add("C%d" % (i + 2), "Device:C", "220p", C_SMD,
        {"1": "SPKF_" + sig, "2": "GND"}, sch=(150 + i * 8, 106, 0), pcb=(63.5, 46.0 + 4 * i, 0), lcsc="C53172")
JST_FP = "Connector_JST:JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical"
add("J5", "Connector_Generic:Conn_01x02", "Speaker L (JST-PH)", JST_FP,
    {"1": "SPKF_LP", "2": "SPKF_LN"}, sch=(190, 96, 0), pcb=(72.0, 66.0, 0))
add("J6", "Connector_Generic:Conn_01x02", "Speaker R (JST-PH)", JST_FP,
    {"1": "SPKF_RP", "2": "SPKF_RN"}, sch=(190, 106, 0), pcb=(82.0, 66.0, 0))

# --- Headphone jack on the Seed line out, with plug detect that mutes the amp --------
# Tip/ring carry AUDIO_L/R.  TN is shorted to T while nothing is plugged in, so HP_DET
# sits at ~0 V (R4 pull-down) and rises to 3V3 (R3 pull-up) when a plug opens the contact.
# Q1 then pulls the amp's SD low -> speakers off, headphones on.  D11 (MUTE) can do the same
# from firmware; D13 reads HP_DET.
add("J7", "Connector_Audio:AudioJack3_SwitchTR", "Headphones 3.5mm (CUI SJ1-3515N)",
    "Connector_Audio:Jack_3.5mm_CUI_SJ1-3515N_Horizontal",
    {"S": "GND", "T": "HP_L", "R": "HP_R", "TN": "HP_DET", "RN": None},
    sch=(20, 130, 0), pcb=(6.1, 76.0, 0))
add("R3", "Device:R", "100k", R_SMD, {"1": "+3V3", "2": "HP_DET"}, sch=(36, 126, 0), pcb=(64.0, 84.0, 0), lcsc="C17407")
add("R4", "Device:R", "10k", R_SMD, {"1": "HP_L", "2": "GND"}, sch=(42, 126, 0), pcb=(30.0, 84.0, 0), lcsc="C17414")
add("R5", "Device:R", "10k", R_SMD, {"1": "HP_DET", "2": "Q1_B"}, sch=(52, 126, 0), pcb=(78.0, 80.0, 0), lcsc="C17414")
add("R6", "Device:R", "10k", R_SMD, {"1": "MUTE", "2": "Q1_B"}, sch=(58, 126, 0), pcb=(78.0, 84.0, 0), lcsc="C17414")
add("Q1", "Transistor_BJT:Q_NPN_EBC", "2N3904", "Package_TO_SOT_THT:TO-92_Inline",
    {"1": "GND", "2": "Q1_B", "3": "AMP_SD"}, sch=(68, 128, 0), pcb=(96.0, 82.0, 0))

# --- Headphone amp: TI TPA6138A2 (TSSOP-14), DirectPath ground-centred outputs ---------
# Inverting stage per channel, gain = -Rfb/Rin = -1 (10k/10k), 1u input caps (fc ~16 Hz),
# 47p across Rfb, 1u charge-pump flying cap CP-CN, 1u on VSS, 2.2u on VDD.  Runs from the
# Seed's 3V3 rail (14-25 mA).  Mute is active-low: R12 pulls it up so it runs by default,
# D14 can pull it low from firmware.  UVP has an internal pull-up and is left open.
add("U2", "SynthMachine:TPA6138A2", "TPA6138A2PWR", "Package_SO:TSSOP-14_4.4x5mm_P0.65mm",
    {"14": "GND", "13": "HP_INL", "1": "GND", "2": "HP_INR", "5": "HP_MUTE", "11": None, "9": "+3V3",
     "12": "HP_L", "3": "HP_R", "8": "HP_CP", "7": "HP_CN", "6": "HP_VSS", "4": "GND", "10": "GND"},
    sch=(146, 128, 0), pcb=(23.0, 84.0, 0), lcsc="C183097",
    desc="TI TPA6138A2 40mW DirectPath stereo headphone amplifier, TSSOP-14, 3.3V")
HP_COL = {"L": 21.0, "R": 25.0}
for ch, y_s in (("L", 122), ("R", 134)):
    col = HP_COL[ch]
    # input caps stand vertical (rot 270 -> pad 1 on top) so the audio traces can drop straight in
    add("C%d" % (7 if ch == "L" else 8), "Device:C", "1u", C_SMD, {"1": "AUDIO_" + ch, "2": "HP_IN%s_C" % ch},
        sch=(108, y_s, 90), pcb=(col, 65.5, 270), lcsc="C28323")
    add("R%d" % (8 if ch == "L" else 10), "Device:R", "10k", R_SMD, {"1": "HP_IN%s_C" % ch, "2": "HP_IN" + ch},
        sch=(116, y_s, 90), pcb=(col, 68.5, 0), lcsc="C17414")
    add("R%d" % (9 if ch == "L" else 11), "Device:R", "10k", R_SMD, {"1": "HP_IN" + ch, "2": "HP_" + ch},
        sch=(124, y_s, 90), pcb=(col, 71.0, 0), lcsc="C17414")
    add("C%d" % (9 if ch == "L" else 10), "Device:C", "47p", C_SMD, {"1": "HP_IN" + ch, "2": "HP_" + ch},
        sch=(132, y_s, 90), pcb=(col, 73.5, 0), lcsc="C14857")
add("C11", "Device:C", "1u", C_SMD, {"1": "HP_CP", "2": "HP_CN"}, sch=(166, 122, 90), pcb=(21.0, 76.0, 0), lcsc="C28323")
add("C12", "Device:C", "1u", C_SMD, {"1": "HP_VSS", "2": "GND"}, sch=(172, 122, 90), pcb=(25.0, 76.0, 0), lcsc="C28323")
add("C13", "Device:C", "10u", C_SMD, {"1": "+3V3", "2": "GND"}, sch=(178, 122, 90), pcb=(21.0, 78.5, 0), lcsc="C15850")
add("R12", "Device:R", "100k", R_SMD, {"1": "+3V3", "2": "HP_MUTE"}, sch=(184, 122, 90), pcb=(25.0, 78.5, 0), lcsc="C17407")

# Hand-routed nets, locked before the autorouter runs (see route.py).  Endpoints are
# either (x, y) in mm or ("REF", "pad") resolved to that pad's centre.
# Seed line out (U1.18/19, left column) -> amp header on F.Cu, nested L shapes;
# same pins -> headphone amp input caps on B.Cu, via up next to the cap.
PREROUTES = [
    ("AUDIO_L", "F.Cu", [("U1", "18"), (86.0, None), (86.0, 13.5), (62.5, 13.5), (62.5, "C16:1"), ("C16", "1")]),
    ("AUDIO_R", "F.Cu", [("U1", "19"), (84.5, None), (84.5, 26.5), (62.5, 26.5), (62.5, "C17:1"), ("C17", "1")]),
    ("AUDIO_L", "B.Cu", [("U1", "18"), (87.5, None), (87.5, 60.7), (21.0, 60.7), (21.0, 62.4)]),
    ("AUDIO_L", "VIA", (21.0, 62.4)),
    ("AUDIO_L", "F.Cu", [(21.0, 62.4), ("C7", "1")]),
    ("AUDIO_R", "B.Cu", [("U1", "19"), (88.5, None), (88.5, 61.5), (25.0, 61.5), (25.0, 62.9)]),
    ("AUDIO_R", "VIA", (25.0, 62.9)),
    ("AUDIO_R", "F.Cu", [(25.0, 62.9), ("C8", "1")]),
    # MAX98306 right-side fan-out (pins top->bottom: 14 13 12 11 10 9 8).  The 0.4 mm pitch
    # pads take 0.2 mm stubs only, so the four speaker outputs go straight into vias and run
    # as a 0.3 mm bus on B.Cu down to the ferrite beads; PVDD pins go to the decoupling caps.
    ("SPK_LN", "F.Cu", [("U3", "14"), (75.0, None), (76.5, 17.0)], 0.2),
    ("SPK_LN", "VIA", (76.5, 17.0)),
    ("SPK_LN", "B.Cu", [(76.5, 17.0), (83.4, 17.0), (83.4, 56.5), (72.0, 56.5), ("FB4", "1")], 0.3),
    ("SPK_LP", "F.Cu", [("U3", "13"), (75.6, None), (77.3, 18.2)], 0.2),
    ("SPK_LP", "VIA", (77.3, 18.2)),
    ("SPK_LP", "B.Cu", [(77.3, 18.2), (82.6, 18.2), (82.6, 52.5), (72.0, 52.5), ("FB3", "1")], 0.3),
    ("+5V", "F.Cu", [("U3", "12"), ("C14", "1")], 0.2),
    ("+5V", "F.Cu", [("U3", "11"), (79.0, None), (80.3, "C15:1"), ("C15", "1")], 0.2),
    ("+5V", "F.Cu", [("C14", "1"), ("C15", "1")], 0.3),
    ("SPK_RP", "F.Cu", [("U3", "10"), (75.6, None), (77.3, 21.4)], 0.2),
    ("SPK_RP", "VIA", (77.3, 21.4)),
    ("SPK_RP", "B.Cu", [(77.3, 21.4), (81.8, 21.4), (81.8, 48.5), (72.0, 48.5), ("FB2", "1")], 0.3),
    ("SPK_RN", "F.Cu", [("U3", "9"), (75.0, None), (76.5, 22.6)], 0.2),
    ("SPK_RN", "VIA", (76.5, 22.6)),
    ("SPK_RN", "B.Cu", [(76.5, 22.6), (81.0, 22.6), (81.0, 44.5), (72.0, 44.5), ("FB1", "1")], 0.3),
    ("GND", "F.Cu", [("U3", "8"), (None, 22.4), (72.0, 22.4), (72.0, 21.0)], 0.2),   # into the exposed pad
]
PREROUTE_WIDTH = 0.3

# --- Expansion header (spare Seed pins) -------------------------------------
add("J8", "Connector_Generic:Conn_01x12", "Expansion",
    "Connector_PinHeader_2.54mm:PinHeader_1x12_P2.54mm_Vertical",
    {"1": "HP_MUTE", "2": "EXP_D26", "3": "EXP_D27", "4": "EXP_A5", "5": "EXP_A6",
     "6": "EXP_A7", "7": "EXP_A8", "8": "HP_DET", "9": "MUTE", "10": "+3V3", "11": "+5V", "12": "GND"},
    sch=(200, 40, 0), pcb=(20.0, 152.0, 90))

# --- Mounting holes ----------------------------------------------------------
for i, (hx, hy) in enumerate([(8, 8), (150, 8), (BOARD_W - 8, 8), (8, BOARD_H - 8), (150, BOARD_H - 8), (BOARD_W - 8, BOARD_H - 8)]):
    add("H%d" % (i + 1), "Mechanical:MountingHole", "M3", "MountingHole:MountingHole_3.2mm_M3", {},
        sch=(200 + i * 8, 120, 0), pcb=(float(hx), float(hy), 0))

# Power symbols / flags (schematic only).  (net, position)
POWER_SYMS = []


def power(net, x, y, rot=0):
    POWER_SYMS.append((net, x, y, rot))


# ---------------------------------------------------------------------------
# s-expression helpers
# ---------------------------------------------------------------------------
def extract_symbol(lib_text, name):
    """Return the raw text of (symbol "name" ...) from a .kicad_sym file."""
    i = lib_text.find('(symbol "%s"' % name)
    if i < 0:
        raise KeyError(name)
    d, j = 0, i
    while True:
        c = lib_text[j]
        if c == "(":
            d += 1
        elif c == ")":
            d -= 1
            if d == 0:
                break
        j += 1
    return lib_text[i:j + 1]


def symbol_pins(sym_text):
    """[(number, x, y, rot)] for every pin in a lib symbol (lib coords, y up)."""
    pins = []
    for m in re.finditer(r'\(pin\s+\w+\s+\w+\s*\(at\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\)', sym_text):
        tail = sym_text[m.end():m.end() + 600]
        n = re.search(r'\(number\s+"([^"]*)"', tail)
        pins.append((n.group(1), float(m.group(1)), float(m.group(2)), float(m.group(3))))
    return pins


_lib_cache = {}


def lib_symbol_text(lib_id):
    lib, name = lib_id.split(":", 1)
    if lib == "SynthMachine":
        text = PROJECT_SYMBOLS[name]
    else:
        if lib not in _lib_cache:
            _lib_cache[lib] = open(os.path.join(SYMDIR, lib + ".kicad_sym")).read()
        text = extract_symbol(_lib_cache[lib], name)
    if "(extends " in text:
        raise RuntimeError("%s extends another symbol; pick a base symbol instead" % lib_id)
    return text


def fmt(v):
    s = ("%.4f" % v).rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


# ---------------------------------------------------------------------------
# Daisy Seed symbol (project library)
# ---------------------------------------------------------------------------
def build_seed_symbol():
    body_w, half_h = 20.32, 27.94
    lines = ['(symbol "DaisySeed" (pin_names (offset 1.016)) (exclude_from_sim no) (in_bom yes) (on_board yes)']
    props = [("Reference", "U", (0, 29.21), False), ("Value", "Daisy Seed", (0, -29.21), False),
             ("Footprint", "SynthMachine:DaisySeed_2x20", (0, -31.75), True),
             ("Datasheet", "https://daisy.audio/hardware/Seed/", (0, 0), True),
             ("Description", "Electrosmith Daisy Seed SOM, 2x20 pin", (0, 0), True)]
    for k, v, (px, py), hide in props:
        lines.append('  (property "%s" "%s" (at %s %s 0) (effects (font (size 1.27 1.27))%s))'
                     % (k, v, fmt(px), fmt(py), " (hide yes)" if hide else ""))
    lines.append('  (symbol "DaisySeed_0_1" (rectangle (start %s %s) (end %s %s) (stroke (width 0.254) (type default)) (fill (type background))))'
                 % (fmt(-body_w), fmt(half_h), fmt(body_w), fmt(-half_h)))
    lines.append('  (symbol "DaisySeed_1_1"')
    for n in range(1, 41):
        name, etype, _ = SEED_PINS[n]
        if n <= 20:
            x, y, rot = -(body_w + 2.54), 25.4 - (n - 1) * 2.54, 0
        else:
            x, y, rot = body_w + 2.54, 25.4 - (40 - n) * 2.54, 180
        lines.append('    (pin %s line (at %s %s %d) (length 2.54) (name "%s" (effects (font (size 1.27 1.27)))) (number "%d" (effects (font (size 1.27 1.27)))))'
                     % (etype, fmt(x), fmt(y), rot, name, n))
    lines.append("  )")
    lines.append(")")
    return "\n".join(lines)


DAISY_SEED_SYMBOL = build_seed_symbol()


def build_box_symbol(name, left, right, value, footprint, desc, datasheet="~"):
    """Simple rectangular symbol. left/right = [(number, name, etype)] top to bottom."""
    n = max(len(left), len(right))
    half_h = (n + 1) * 2.54 / 2 + 1.27
    body_w = 12.7
    lines = ['(symbol "%s" (pin_names (offset 1.016)) (exclude_from_sim no) (in_bom yes) (on_board yes)' % name]
    props = [("Reference", "U", (0, half_h + 1.27), False), ("Value", value, (0, -half_h - 1.27), False),
             ("Footprint", footprint, (0, -half_h - 3.81), True), ("Datasheet", datasheet, (0, 0), True), ("Description", desc, (0, 0), True)]
    for k, v, (px, py), hide in props:
        lines.append('  (property "%s" "%s" (at %s %s 0) (effects (font (size 1.27 1.27))%s))' % (k, v, fmt(px), fmt(py), " (hide yes)" if hide else ""))
    lines.append('  (symbol "%s_0_1" (rectangle (start %s %s) (end %s %s) (stroke (width 0.254) (type default)) (fill (type background))))'
                 % (name, fmt(-body_w), fmt(half_h), fmt(body_w), fmt(-half_h)))
    lines.append('  (symbol "%s_1_1"' % name)
    for side, rot, x in ((left, 0, -(body_w + 2.54)), (right, 180, body_w + 2.54)):
        for i, (num, pname, etype) in enumerate(side):
            y = half_h - 2.54 * (i + 1)
            lines.append('    (pin %s line (at %s %s %d) (length 2.54) (name "%s" (effects (font (size 1.27 1.27)))) (number "%s" (effects (font (size 1.27 1.27)))))'
                         % (etype, fmt(x), fmt(y), rot, pname, num))
    lines.append("  )")
    lines.append(")")
    return "\n".join(lines)


TPA6138A2_SYMBOL = build_box_symbol(
    "TPA6138A2",
    [("14", "+INL", "input"), ("13", "-INL", "input"), ("1", "+INR", "input"), ("2", "-INR", "input"),
     ("5", "~{MUTE}", "input"), ("11", "UVP", "input"), ("9", "VDD", "power_in")],
    [("12", "OUTL", "output"), ("3", "OUTR", "output"), ("8", "CP", "passive"), ("7", "CN", "passive"),
     ("6", "VSS", "passive"), ("4", "GND", "power_in"), ("10", "GND", "power_in")],
    "TPA6138A2", "Package_SO:TSSOP-14_4.4x5mm_P0.65mm",
    "TI TPA6138A2 DirectPath stereo headphone amplifier, adjustable gain, TSSOP-14",
    "https://www.ti.com/lit/ds/symlink/tpa6138a2.pdf")
MAX98306_SYMBOL = build_box_symbol(
    "MAX98306",
    [("3", "INL+", "input"), ("4", "INL-", "input"), ("7", "INR+", "input"), ("6", "INR-", "input"),
     ("5", "GAIN", "input"), ("2", "~{SHDN}", "input"), ("11", "PVDD", "power_in"), ("12", "PVDD", "power_in")],
    [("13", "OUTL+", "output"), ("14", "OUTL-", "output"), ("10", "OUTR+", "output"), ("9", "OUTR-", "output"),
     ("1", "PGND", "power_in"), ("8", "PGND", "power_in"), ("15", "EP", "power_in")],
    "MAX98306", "Package_DFN_QFN:TDFN-14-1EP_3x3mm_P0.4mm_EP1.78x2.35mm_ThermalVias",
    "Analog Devices MAX98306 stereo 3.7W class-D amplifier, TDFN-14 EP",
    "https://www.analog.com/media/en/technical-documentation/data-sheets/MAX98306.pdf")
PROJECT_SYMBOLS = {"DaisySeed": DAISY_SEED_SYMBOL, "TPA6138A2": TPA6138A2_SYMBOL, "MAX98306": MAX98306_SYMBOL}

# ---------------------------------------------------------------------------
# Footprints (project library)
# ---------------------------------------------------------------------------
def fp_header(name, descr, tags):
    return ['(footprint "%s" (version 20240108) (generator "synth_machine_gen") (generator_version "8.0") (layer "F.Cu")' % name,
            '  (descr "%s")' % descr, '  (tags "%s")' % tags, '  (attr through_hole)']


def fp_props(ref_y, val_y):
    out = []
    for k, v, y, layer, hide in [("Reference", "REF**", ref_y, "F.SilkS", False), ("Value", "VAL", val_y, "F.Fab", False),
                                 ("Footprint", "", 0, "F.Fab", True), ("Datasheet", "", 0, "F.Fab", True), ("Description", "", 0, "F.Fab", True)]:
        out.append('  (property "%s" "%s" (at 0 %s 0) (layer "%s") %s(uuid "%s") (effects (font (size 1 1) (thickness 0.15))%s))'
                   % (k, v, fmt(y), layer, "(hide yes) " if hide else "", U(), " (hide yes)" if hide else ""))
    return out


def fp_circle(r, layer, w=0.1):
    return '  (fp_circle (center 0 0) (end %s 0) (stroke (width %s) (type default)) (fill none) (layer "%s") (uuid "%s"))' % (fmt(r), w, layer, U())


def fp_rect(x1, y1, x2, y2, layer, w=0.1):
    return '  (fp_rect (start %s %s) (end %s %s) (stroke (width %s) (type default)) (fill none) (layer "%s") (uuid "%s"))' % (fmt(x1), fmt(y1), fmt(x2), fmt(y2), w, layer, U())


def fp_text(txt, x, y, layer="F.Fab", size=1.0):
    return '  (fp_text user "%s" (at %s %s 0) (layer "%s") (uuid "%s") (effects (font (size %s %s) (thickness 0.15))))' % (txt, fmt(x), fmt(y), layer, U(), size, size)


def pad_tht(num, x, y, size, drill, shape="circle", rot=0):
    if isinstance(drill, tuple):
        d = "(drill oval %s %s)" % (fmt(drill[0]), fmt(drill[1]))
    else:
        d = "(drill %s)" % fmt(drill)
    sz = "(size %s %s)" % (fmt(size[0]), fmt(size[1])) if isinstance(size, tuple) else "(size %s %s)" % (fmt(size), fmt(size))
    return '  (pad "%s" thru_hole %s (at %s %s %s) %s %s (layers "*.Cu" "*.Mask") (remove_unused_layers no) (uuid "%s"))' % (num, shape, fmt(x), fmt(y), rot, sz, d, U())


def footprint_arcade_button():
    L = fp_header("ArcadeButton_24mm_Keystone3534",
                  "24mm snap-in arcade pushbutton (2.8mm tabs) plugging into 2x Keystone 3534 vertical quick-fit receptacles. VERIFY TAB_PITCH.",
                  "arcade button 24mm snap-in keystone 3534 quick-fit")
    L += fp_props(-15, 15)
    L.append(fp_circle(BTN_D / 2 - 0.05, "F.Fab"))       # 23.5 body
    L.append(fp_circle(BTN_D / 2 + 0.25, "F.CrtYd", 0.05))
    L.append(fp_circle(13.55, "Cmts.User"))              # 27.1 cap (above the panel)
    L.append(fp_text("Keystone 3534 x2, 8mm tall", 0, -8, "Cmts.User", 0.8))
    L.append(fp_text("${REFERENCE}", 0, 8, "F.Fab", 1.0))
    for num, tx in (("1", -TAB_PITCH / 2), ("2", TAB_PITCH / 2)):
        for lx in (-RECEPT_LEG_PITCH / 2, RECEPT_LEG_PITCH / 2):
            L.append(pad_tht(num, tx + lx, 0, RECEPT_HOLE + 0.55, RECEPT_HOLE))
        L.append(fp_rect(tx - 2.0, -1.1, tx + 2.0, 1.1, "F.Fab"))
        L.append(fp_rect(tx - 2.3, -1.4, tx + 2.3, 1.4, "F.SilkS", 0.12))
    L.append(")")
    return "\n".join(L)


def footprint_daisy_seed():
    L = fp_header("DaisySeed_2x20", "Electrosmith Daisy Seed landing pattern: 2 x 20 pins 2.54mm, rows 15.24mm apart, board 18 x 51.15mm",
                  "daisy seed electrosmith som")
    L += fp_props(-20, 28)
    # pin 1 top-left, 20 bottom-left, 21 bottom-right, 40 top-right
    y0 = -48.26 / 2
    for n in range(1, 41):
        if n <= 20:
            x, y = -7.62, y0 + (n - 1) * 2.54
        else:
            x, y = 7.62, y0 + (40 - n) * 2.54
        L.append(pad_tht(str(n), x, y, 1.7, 1.0, "rect" if n == 1 else "circle"))
    L.append(fp_rect(-9, -25.575, 9, 25.575, "F.Fab"))
    L.append(fp_rect(-9.25, -25.825, 9.25, 25.825, "F.CrtYd", 0.05))
    L.append(fp_rect(-9.1, -25.675, 9.1, 25.675, "F.SilkS", 0.12))
    L.append(fp_text("USB", 0, -22, "F.Fab", 1.0))
    L.append(fp_text("${REFERENCE}", 0, 0, "F.Fab", 1.0))
    L.append(")")
    return "\n".join(L)


def footprint_amp_breakout():
    # From Adafruit Eagle .brd: 24.13 x 27.94mm, 1x9 header 2.54mm along left edge, pin1 at bottom-left;
    # two 2.5mm plated mounting holes on the right edge.  Pin 1 (G) is the origin here.
    L = fp_header("Adafruit_MAX98306_Breakout", "Adafruit #987 MAX98306 stereo class-D amp breakout, mounted on 1x9 header (pin1 = G, 9 = VDD). Verify pin 1 end against silkscreen.",
                  "adafruit max98306 amplifier breakout")
    L += fp_props(-27, 6)
    for n in range(1, 10):
        L.append(pad_tht(str(n), 0, -(n - 1) * 2.54, 1.7, 1.0, "rect" if n == 1 else "circle"))
    for x, y in ((19.05, 1.27), (19.05, -21.717)):
        L.append(pad_tht("MH", x, y, 4.0, 2.6))
    L.append(fp_rect(-2.54, 3.81, 21.59, -24.13, "F.Fab"))
    L.append(fp_rect(-2.79, 4.06, 21.84, -24.38, "F.CrtYd", 0.05))
    L.append(fp_rect(-2.6, 3.87, 21.65, -24.19, "F.SilkS", 0.12))
    for n, nm in enumerate(["G", "G'", "R+", "R-", "L-", "L+", "SD", "GND", "VDD"]):
        L.append(fp_text(nm, 3.0, -n * 2.54, "F.Fab", 0.8))
    L.append(fp_text("${REFERENCE}", 10, -12, "F.Fab", 1.0))
    L.append(")")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# Schematic writer
# ---------------------------------------------------------------------------
def rot_vec(x, y, deg):
    """Rotate (x,y) (y-up frame) counter-clockwise by deg."""
    deg %= 360
    if deg == 0:
        return x, y
    if deg == 90:
        return -y, x
    if deg == 180:
        return -x, -y
    if deg == 270:
        return y, -x
    raise ValueError(deg)


def pin_world(sym_at, pin):
    """Schematic (screen, y-down) position and outward direction (deg, y-up frame) of a pin."""
    X, Y, R = sym_at
    _, px, py, prot = pin
    rx, ry = rot_vec(px, py, R)
    outward = (prot + R + 180) % 360
    return X + rx, Y - ry, outward


def sch_symbol_instance(p, root_uuid, pins, ref_prop_pos):
    X, Y, R = p.sch_at
    lines = ['  (symbol (lib_id "%s") (at %s %s %d) (unit 1) (exclude_from_sim no) (in_bom %s) (on_board yes) (dnp no) (fields_autoplaced yes)'
             % (p.lib_id, fmt(X), fmt(Y), R, "no" if p.ref.startswith(("H", "#")) else "yes"),
             '    (uuid "%s")' % p.uuid]
    rx, ry = ref_prop_pos
    props = [("Reference", p.ref, rx, ry, False), ("Value", p.value, rx, ry + 1.27, False),
             ("Footprint", p.footprint, X, Y, True), ("Datasheet", "~", X, Y, True), ("Description", p.desc, X, Y, True)]
    if getattr(p, "lcsc", ""):
        props.append(("LCSC", p.lcsc, X, Y, True))
    for k, v, x, y, hide in props:
        lines.append('    (property "%s" "%s" (at %s %s 0) (effects (font (size 1.27 1.27)) (justify left)%s))'
                     % (k, v.replace('"', "'"), fmt(x), fmt(y), " (hide yes)" if hide else ""))
    for num, *_ in pins:
        lines.append('    (pin "%s" (uuid "%s"))' % (num, U()))
    lines.append('    (instances (project "%s" (path "/%s" (reference "%s") (unit 1))))' % (PROJECT, root_uuid, p.ref))
    lines.append("  )")
    return lines


def sch_global_label(net, x, y, outward):
    justify = "left" if outward in (0, 90) else "right"
    return ['  (global_label "%s" (shape passive) (at %s %s %d) (fields_autoplaced yes) (effects (font (size 1.27 1.27)) (justify %s))'
            % (net, fmt(x), fmt(y), outward, justify),
            '    (uuid "%s")' % U(),
            '    (property "Intersheetrefs" "${INTERSHEET_REFS}" (at %s %s 0) (effects (font (size 1.27 1.27)) (hide yes)))' % (fmt(x), fmt(y)),
            "  )"]


def sch_text(txt, x, y, size=1.5):
    return ['  (text "%s" (exclude_from_sim no) (at %s %s 0) (effects (font (size %s %s)) (justify left bottom)) (uuid "%s"))'
            % (txt.replace('"', "'"), fmt(x), fmt(y), size, size, U())]


POWER_NETS = ("GND", "+5V", "+3V3", "+3.3VA")
WIRE_NETS = re.compile(r"^K.*_D$")  # nets drawn as a plain wire between their two pins


def write_schematic():
    root_uuid = U()
    out = ['(kicad_sch (version 20231120) (generator "synth_machine_gen") (generator_version "8.0")',
           '  (uuid "%s")' % root_uuid, '  (paper "A2")',
           '  (title_block (title "synthMachine carrier board") (rev "0.1-stub") (company "") (comment 1 "Generated by hardware/gen_kicad.py - edit freely, or edit the generator and re-run"))']
    # lib_symbols
    libs = {}
    for p in PARTS:
        libs[p.lib_id] = lib_symbol_text(p.lib_id)
    for net in POWER_NETS + ("PWR_FLAG",):
        libs["power:" + net] = lib_symbol_text("power:" + net)
    out.append("  (lib_symbols")
    for lib_id, text in sorted(libs.items()):
        name = lib_id.split(":", 1)[1]
        text = text.replace('(symbol "%s"' % name, '(symbol "%s"' % lib_id, 1)
        text = re.sub(r'\(embedded_fonts \w+\)', "", text)
        out.append("    " + text.replace("\n", "\n    "))
    out.append("  )")

    pwr_n = [0]

    def place_power(net, x, y, rot=0, flag=False):
        pwr_n[0] += 1
        lib_id = "power:PWR_FLAG" if flag else "power:" + net
        pins = symbol_pins(libs[lib_id])
        p = Part("#PWR%03d" % pwr_n[0] if not flag else "#FLG%03d" % pwr_n[0], lib_id, "PWR_FLAG" if flag else net, "", {}, sch=(x, y, rot))
        out.extend(sch_symbol_instance(p, root_uuid, pins, (x + 1.27, y - 1.27)))

    wire_ends = {}
    for p in PARTS:
        X, Y, R = p.sch_at
        p.sch_at = (X * G, Y * G, R)
        pins = symbol_pins(libs[p.lib_id])
        out.extend(sch_symbol_instance(p, root_uuid, pins, (p.sch_at[0] + 6.35, p.sch_at[1] - 6.35)))
        for pin in pins:
            net = p.pins.get(pin[0])
            x, y, outward = pin_world(p.sch_at, pin)
            if net is None:
                out.append('  (no_connect (at %s %s) (uuid "%s"))' % (fmt(x), fmt(y), U()))
            elif net in POWER_NETS:
                place_power(net, x, y)
            elif WIRE_NETS.match(net):
                wire_ends.setdefault(net, []).append((x, y))
            else:
                out.extend(sch_global_label(net, x, y, outward))

    for net, ends in wire_ends.items():
        assert len(ends) == 2, (net, ends)
        (x1, y1), (x2, y2) = ends
        out.append('  (wire (pts (xy %s %s) (xy %s %s)) (stroke (width 0) (type default)) (uuid "%s"))' % (fmt(x1), fmt(y1), fmt(x2), fmt(y2), U()))

    # Power flags + a PWR_FLAG-driven stub for the rails no power_out pin drives.
    for net, x, y in (("+5V", 100 * G, 92 * G), ("GND", 106 * G, 92 * G), ("VBUS", 118 * G, 92 * G)):
        if net in POWER_NETS:
            place_power(net, x, y)
        else:
            out.extend(sch_global_label(net, x, y, 270))
        place_power(net, x, y, flag=True)

    notes = [
        ("KEY MATRIX: columns D4-D9 driven low one at a time, rows D1-D3 read with pull-ups (see scanButtonMatrix). Diode anode to switch, cathode to column.", 78, 3),
        ("C4 is a direct key on D10 to GND (firmware uses internal pull-up).  BTN1-6 = top-row buttons on the 6 unused matrix slots (NOTE_MAPPING -1 entries).", 78, 5),
        ("POTS: panel-mount 10k linear pots wired to 3-pin headers: 1 = +3V3A, 2 = wiper -> A0..A4, 3 = AGND.", 78, 32),
        ("POWER: USB-C only. VBUS -> 2A polyfuse -> +5V rail for Seed VIN and the amp. 5.1k CC pull-downs advertise a 1.5A sink.", 20, 88),
        ("USB-C data to D29/D30 = Daisy 'external' USB. In firmware use MidiUsbTransport::Config::EXTERNAL.", 20, 90),
        ("AMP: MAX98306 on board, single-ended inputs (1u caps, - inputs to GND). Gain: R13 100k to PVDD = 9 dB, JP1 straps GAIN to GND (18 dB) or PVDD (12 dB). Outputs -> ferrite + 220p EMI filter -> JST-PH.", 120, 90),
        ("Outputs are bridge-tied: NO series caps on the speakers, never join L- and R-.", 120, 92),
        ("HEADPHONES: TPA6138A2 (gain -1, ground-centred output, no output caps) drives the jack. TN contact = plug detect (HP_DET). Q1 pulls the speaker amp SD low when plugged. D11 = speaker mute, D13 reads HP_DET, D14 = headphone mute (pulled up).", 20, 118),
        ("EXPANSION: spare Seed GPIO/ADC + 3V3/5V/GND for a future display, encoder, MIDI DIN, etc.", 200, 34),
    ]
    for txt, x, y in notes:
        out.extend(sch_text(txt, x * G, y * G))
    out.append('  (sheet_instances (path "/" (page "1")))')
    out.append(")")
    with open(os.path.join(HERE, PROJECT + ".kicad_sch"), "w") as f:
        f.write("\n".join(out) + "\n")
    return root_uuid


# ---------------------------------------------------------------------------
# PCB writer (pcbnew)
# ---------------------------------------------------------------------------
def write_pcb(root_uuid):
    try:
        import pcbnew
    except ImportError:
        print("pcbnew not importable - run this with KiCad's bundled python to generate the PCB")
        return False
    mm = pcbnew.FromMM
    board = pcbnew.BOARD()
    nets = {}

    def net(name):
        if name not in nets:
            n = pcbnew.NETINFO_ITEM(board, name)
            board.Add(n)
            nets[name] = n
        return nets[name]

    for p in PARTS:
        lib, name = p.footprint.split(":", 1)
        libpath = os.path.join(HERE, "SynthMachine.pretty") if lib == "SynthMachine" else os.path.join(FPDIR, lib + ".pretty")
        fp = pcbnew.FootprintLoad(libpath, name)
        if fp is None:
            raise RuntimeError("footprint not found: " + p.footprint)
        fp.SetReference(p.ref)
        fp.SetValue(p.value)
        fp.SetPath(pcbnew.KIID_PATH("/" + p.uuid))
        board.Add(fp)
        x, y, rot = p.pcb_at
        fp.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
        fp.SetOrientationDegrees(rot)
        padnames = set()
        for pad in fp.Pads():
            padnames.add(pad.GetNumber())
            n = p.pins.get(pad.GetNumber())
            if n:
                pad.SetNet(net(n))
        missing = [k for k in p.pins if k not in padnames]
        if missing:
            print("WARNING %s (%s): schematic pins with no pad: %s ; pads=%s" % (p.ref, p.footprint, missing, sorted(padnames)))

    # Outline: rectangle with R6 corners, same as the panel
    W, H, R = BOARD_W, BOARD_H, CORNER_R
    def seg(x1, y1, x2, y2):
        sh = pcbnew.PCB_SHAPE(board)
        sh.SetShape(pcbnew.SHAPE_T_SEGMENT)
        sh.SetStart(pcbnew.VECTOR2I(mm(x1), mm(y1)))
        sh.SetEnd(pcbnew.VECTOR2I(mm(x2), mm(y2)))
        sh.SetLayer(pcbnew.Edge_Cuts)
        sh.SetWidth(mm(0.1))
        board.Add(sh)

    def arc(cx, cy, a0, a1):
        import math
        sh = pcbnew.PCB_SHAPE(board)
        sh.SetShape(pcbnew.SHAPE_T_ARC)
        pts = [pcbnew.VECTOR2I(mm(cx + R * math.cos(math.radians(a))), mm(cy + R * math.sin(math.radians(a)))) for a in (a0, (a0 + a1) / 2, a1)]
        sh.SetArcGeometry(pts[0], pts[1], pts[2])
        sh.SetLayer(pcbnew.Edge_Cuts)
        sh.SetWidth(mm(0.1))
        board.Add(sh)

    seg(R, 0, W - R, 0)
    seg(W, R, W, H - R)
    seg(W - R, H, R, H)
    seg(0, H - R, 0, R)
    arc(W - R, R, -90, 0)      # top-right   (screen angles: -90 = up, 0 = right, 90 = down)
    arc(W - R, H - R, 0, 90)   # bottom-right
    arc(R, H - R, 90, 180)     # bottom-left
    arc(R, R, 180, 270)        # top-left

    # Silkscreen labels
    def text(txt, x, y, size=2.0, layer=pcbnew.F_SilkS):
        t = pcbnew.PCB_TEXT(board)
        t.SetText(txt)
        t.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
        t.SetTextSize(pcbnew.VECTOR2I(mm(size), mm(size)))
        t.SetTextThickness(mm(size * 0.15))
        t.SetLayer(layer)
        board.Add(t)

    text("synthMachine carrier v0.2 (stub)", 175, 150, 2.5)
    for (name, mat, px, py) in KEYS:
        text(name, px, py + (14 if py == WHITE_Y else -14), 1.5)
    for (ref, netname, label, px) in POTS:
        text(label, px, POT_Y - 5, 1.2)
    text("USB-C MIDI/5V", 114, 12, 1.0)
    text("AMP MAX98306", 72, 8, 1.2)
    text("GAIN", 76.5, 33, 0.8)
    text("SPK L", 72, 71, 1.0)
    text("SPK R", 82, 71, 1.0)
    text("HP", 10, 67.5, 1.2)
    text("HP AMP", 30.5, 80.0, 1.0)
    text("EXP", 14, 152, 1.0)

    # GND pours (unfilled; press B in pcbnew)
    for layer in (pcbnew.B_Cu, pcbnew.F_Cu):
        try:
            z = pcbnew.ZONE(board)
            z.SetLayer(layer)
            z.SetNet(net("GND"))
            ol = z.Outline()
            ol.NewOutline()
            for (x, y) in [(1, 1), (BOARD_W - 1, 1), (BOARD_W - 1, BOARD_H - 1), (1, BOARD_H - 1)]:
                ol.Append(mm(x), mm(y))
            z.SetIsFilled(False)
            board.Add(z)
        except Exception as e:  # zone API drifts between versions; a stub can live without it
            print("zone skipped:", e)

    # Design rules / net classes (the autorouter reads these from the DSN export)
    try:
        ds = board.GetDesignSettings()
        ds.m_MinClearance = mm(0.15)      # 0.4 mm pitch TDFN pads need 0.2 track / 0.15 clearance
        ds.m_TrackMinWidth = mm(0.15)
        ds.m_ViasMinSize = mm(0.6)
        ds.m_MinThroughDrill = mm(0.2)   # the TDFN thermal vias are 0.2 mm; JLC/PCBWay allow 0.2 on 2-layer
        ns = ds.m_NetSettings
        dflt = ns.GetDefaultNetclass()
        dflt.SetClearance(mm(0.15)); dflt.SetTrackWidth(mm(0.2)); dflt.SetViaDiameter(mm(0.7)); dflt.SetViaDrill(mm(0.35))
        pwr = pcbnew.NETCLASS("Power")
        pwr.SetClearance(mm(0.2)); pwr.SetTrackWidth(mm(0.6)); pwr.SetViaDiameter(mm(0.9)); pwr.SetViaDrill(mm(0.5))
        ns.SetNetclass("Power", pwr)
        usb = pcbnew.NETCLASS("USB_Power")   # narrower so it can escape the USB-C's 0.5 mm pitch pads
        usb.SetClearance(mm(0.2)); usb.SetTrackWidth(mm(0.4)); usb.SetViaDiameter(mm(0.8)); usb.SetViaDrill(mm(0.4))
        ns.SetNetclass("USB_Power", usb)
        spk = pcbnew.NETCLASS("Speaker")     # amp pins -> ferrite beads: pad-limited, short
        spk.SetClearance(mm(0.15)); spk.SetTrackWidth(mm(0.3)); spk.SetViaDiameter(mm(0.8)); spk.SetViaDrill(mm(0.4))
        ns.SetNetclass("Speaker", spk)
        ns.SetNetclassPatternAssignment("SPK_*", "Speaker")
        # GND stays in the default class: the tracks only guarantee connectivity, the pours carry current
        # +3V3 / +3.3VA carry tens of mA at most and have to reach TSSOP pads: default class
        for pat in ("+5V", "+5V_SW", "SPKF_*"):
            ns.SetNetclassPatternAssignment(pat, "Power")
        ns.SetNetclassPatternAssignment("VBUS", "USB_Power")
        print("netclasses set")
    except Exception as e:
        print("netclass setup skipped:", e)

    pcbnew.SaveBoard(os.path.join(HERE, PROJECT + ".kicad_pcb"), board)
    return True


# ---------------------------------------------------------------------------
def write_project_files():
    pretty = os.path.join(HERE, "SynthMachine.pretty")
    os.makedirs(pretty, exist_ok=True)
    for name, text in (("ArcadeButton_24mm_Keystone3534", footprint_arcade_button()),
                       ("DaisySeed_2x20", footprint_daisy_seed()),
                       ("Adafruit_MAX98306_Breakout", footprint_amp_breakout())):
        with open(os.path.join(pretty, name + ".kicad_mod"), "w") as f:
            f.write(text + "\n")
    with open(os.path.join(HERE, "SynthMachine.kicad_sym"), "w") as f:
        f.write('(kicad_symbol_lib (version 20231120) (generator "synth_machine_gen") (generator_version "8.0")\n'
                + "\n".join(PROJECT_SYMBOLS.values()) + "\n)\n")
    with open(os.path.join(HERE, "sym-lib-table"), "w") as f:
        f.write('(sym_lib_table (version 7)\n  (lib (name "SynthMachine")(type "KiCad")(uri "${KIPRJMOD}/SynthMachine.kicad_sym")(options "")(descr "Project symbols"))\n)\n')
    with open(os.path.join(HERE, "fp-lib-table"), "w") as f:
        f.write('(fp_lib_table (version 7)\n  (lib (name "SynthMachine")(type "KiCad")(uri "${KIPRJMOD}/SynthMachine.pretty")(options "")(descr "Project footprints"))\n)\n')
    pro = {
        "meta": {"filename": PROJECT + ".kicad_pro", "version": 1},
        "board": {"design_settings": {"defaults": {}, "rules": {"min_clearance": 0.15, "min_track_width": 0.15, "min_via_diameter": 0.4, "min_via_annular_width": 0.1, "min_through_hole_diameter": 0.2},
                                      "rule_severities": {"starved_thermal": "warning"}}},
        "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []},
        "net_settings": {"classes": [{"name": "Default", "clearance": 0.2, "track_width": 0.3, "via_diameter": 0.8, "via_drill": 0.4,
                                      "wire_width": 6, "bus_width": 12, "pcb_color": "rgba(0, 0, 0, 0.000)", "schematic_color": "rgba(0, 0, 0, 0.000)"}]},
        "pcbnew": {"page_layout_descr_file": ""},
        "schematic": {"legacy_lib_dir": "", "legacy_lib_list": []},
        "sheets": [],
        "text_variables": {},
    }
    with open(os.path.join(HERE, PROJECT + ".kicad_pro"), "w") as f:
        json.dump(pro, f, indent=2)


def main():
    write_project_files()
    root = write_schematic()
    ok = write_pcb(root)
    # BOM-ish summary
    print("Generated %d parts, PCB %s" % (len(PARTS), "written" if ok else "SKIPPED"))
    nets = {}
    for p in PARTS:
        for pin, n in p.pins.items():
            if n:
                nets.setdefault(n, []).append("%s.%s" % (p.ref, pin))
    single = [n for n, v in nets.items() if len(v) < 2]
    if single:
        print("Single-ended nets (check):", single)


if __name__ == "__main__":
    main()
