#!/usr/bin/env python3
"""
Generates the KiCad project for the synthMachine carrier board, revision 0.4.

v0.4 changes against v0.3 (see ../NEXT_REVISION.md):
  - Q1 (headphone plug detect -> speaker mute) is a 2N7002 MOSFET, so HP_DET
    reaches 3V3 and D13 can read it.  The firmware mute has its own MOSFET Q2
    on D0, pulled up so the speakers default to muted at reset.
  - I2C1 (D11 SCL, D12 SDA) on a STEMMA QT connector for seesaw encoders.
  - Display header on hardware SPI1 (A7 SCK, A3 MOSI, A8 NSS) + D26 D/C, D27 RST.
  - Only the volume pot stays; the four bank pots are I2C encoders on the STEMMA
    QT connector, and A1/A2/A4/A9 go to the expansion header.
  - USBLC6-2SC6 ESD protection on the USB-C data lines.
  - F1 is an SMD 1812 PTC (the radial one collided with the Seed).
  - Every part carries an MPN for PCBWay assembly (fab.sh writes the BOM).
  - 160 x 74 mm landscape board with all 19 key headers in one row along the
    bottom edge, in panel order, so every button lead is the same length.
  - Onboard single-cell LiPo power: BQ24074 charger with power path from the
    USB-C, TPS61023 5 V boost for the Seed VIN and the speaker amp, panel
    power switch header (or solder jumper), battery voltage divider to A10,
    charge and USB-present status to A5 / A11.  Rails: VBUS -> F1 -> VUSB ->
    charger -> VSYS -> boost -> +5V.  Use a protected cell.

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

Pin usage mirrors synthMachine.cpp (HW=carrier4):
  matrix columns D4..D9, rows D1..D3, direct C4 key on D10, volume pot on A0,
  MUTE on D0, HP_DET D13, HP_MUTE D14, I2C1 on D11/D12 (encoders), SPI1 on
  A7/A3/A8 with D26/D27, external USB (MIDI) on D29/D30, audio out L/R,
  battery: A10 = VBAT/2, A5 = ~CHG, A11 = ~PGOOD (USB present).
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
# Landscape carrier: nothing has to line up with the panel (buttons and pots come in on JST-XH
# leads), but the 19 key headers sit in one row along the bottom edge in panel order so every
# lead is the same length and points the same way.  160 x 74 mm; the Seed stands vertical with
# its USB on the top edge next to the board's USB-C and the headphone jack.
BOARD_W, BOARD_H, CORNER_R = 160.0, 74.0, 3.0
# Legacy arcade-button-on-board footprint (kept in the project lib, unused): tabs 2.8 mm wide,
# 9.05 mm outer-to-outer -> 6.25 mm centre-to-centre; Keystone 3534 receptacles.
TAB_PITCH = 9.05 - 2.8
BTN_D = 23.6
RECEPT_LEG_PITCH, RECEPT_HOLE = 3.7, 1.65

G = 2.54  # schematic grid


def U():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Netlist / component model
# ---------------------------------------------------------------------------
class Part:
    def __init__(self, ref, lib_id, value, footprint, pins, sch=(0, 0, 0), pcb=(0, 0, 0), desc="", lcsc="", mpn="", dnp=False):
        self.ref, self.lib_id, self.value, self.footprint = ref, lib_id, value, footprint
        self.lcsc = lcsc              # JLCPCB/LCSC part number for SMT assembly ("" = not assembled)
        self.mpn = mpn                # manufacturer part number for the PCBWay BOM ("" = generic by value)
        self.dnp = dnp                # footprint only, not fitted (I2C pull-ups)
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
    1: ("D0", "bidirectional", "MUTE"),
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
    12: ("D11", "bidirectional", "I2C_SCL"),
    13: ("D12", "bidirectional", "I2C_SDA"),
    14: ("D13", "bidirectional", "HP_DET"),
    15: ("D14", "bidirectional", "HP_MUTE"),
    16: ("AUDIO_IN_L", "input", None),
    17: ("AUDIO_IN_R", "input", None),
    18: ("AUDIO_OUT_L", "output", "AUDIO_L"),
    19: ("AUDIO_OUT_R", "output", "AUDIO_R"),
    20: ("AGND", "power_in", "GND"),
    21: ("+3V3A", "power_out", "+3.3VA"),
    22: ("A0/D15", "bidirectional", "POT_VOL"),
    23: ("A1/D16", "bidirectional", "EXP_A1"),
    24: ("A2/D17", "bidirectional", "EXP_A2"),
    25: ("A3/D18", "bidirectional", "SPI_MOSI"),    # SPI1 MOSI (PA7) for the display
    26: ("A4/D19", "bidirectional", "EXP_A4"),
    27: ("A5/D20", "bidirectional", "CHG_STAT"),     # ~CHG from the charger, low = charging
    28: ("A6/D21", "bidirectional", "EXP_A6"),
    29: ("A7/D22", "bidirectional", "SPI_SCK"),     # SPI1 SCK (PA5)
    30: ("A8/D23", "bidirectional", "SPI_NSS"),     # SPI1 NSS (PA4)
    31: ("A9/D24", "bidirectional", "EXP_A9"),
    32: ("A10/D25", "bidirectional", "VBAT_SENSE"),  # battery voltage / 2
    33: ("D26", "bidirectional", "DISP_DC"),
    34: ("D27", "bidirectional", "DISP_RST"),
    35: ("A11/D28", "bidirectional", "USB_PGOOD"),   # ~PGOOD from the charger, low = USB present
    36: ("D29/USB_D-", "bidirectional", "USB_DM"),
    37: ("D30/USB_D+", "bidirectional", "USB_DP"),
    38: ("+3V3D", "power_out", "+3V3"),
    39: ("VIN", "power_in", "+5V"),
    40: ("GND", "power_in", "GND"),
}

# Seed (Seed rev5 / Seed3: same pinout and outline, Seed3 has USB-C) with its USB end on the
# top board edge, next to the board's own USB-C and the headphone jack, so one enclosure wall
# carries all three ports.
SEED_X, SEED_Y = 38.0, 26.5
add("U1", "SynthMachine:DaisySeed", "Daisy Seed / Seed3", "SynthMachine:DaisySeed_2x20",
    {str(n): v[2] for n, v in SEED_PINS.items()}, sch=(38, 50, 0), pcb=(SEED_X, SEED_Y, 0),
    desc="Electrosmith Daisy Seed (rev 4/5/7 or Seed3), 2x20 0.1in headers on 0.6in centres",
    mpn="PPTC201LFBN-RC x2 (sockets; the Seed itself is fitted by hand)")

# --- Keys: one JST-XH 2-pin header per button, buttons live on the panel ------------------
# (name, (col,row) or None for the direct C4 key).  All 19 in one row along the bottom edge in
# panel order, headers rotated so the row is 7 mm pitch, each diode directly above its header
# and the key name below it.  Matrix as scanButtonMatrix(): columns D4..D9 driven low, rows
# D1..D3 read with pull-ups; diode anode to the switch, cathode to the column.
KEYS = [
    ("C4", None), ("C#4", (5, 0)), ("D4", (5, 1)), ("D#4", (4, 1)), ("E4", (5, 2)),
    ("F4", (4, 2)), ("F#4", (3, 1)), ("G4", (3, 2)), ("G#4", (2, 1)), ("A4", (2, 2)),
    ("A#4", (1, 1)), ("B4", (1, 2)), ("C5", (0, 2)),
    ("BTN1", (0, 0)), ("BTN2", (0, 1)), ("BTN3", (1, 0)), ("BTN4", (2, 0)), ("BTN5", (3, 0)), ("BTN6", (4, 0)),
]
XH2_FP = "Connector_JST:JST_XH_B2B-XH-A_1x02_P2.50mm_Vertical"
XH3_FP = "Connector_JST:JST_XH_B3B-XH-A_1x03_P2.50mm_Vertical"
XH2_MPN, XH3_MPN = "B2B-XH-A(LF)(SN)", "B3B-XH-A(LF)(SN)"
DIODE_FP = "Diode_SMD:D_SOD-123"
KEY_X0, KEY_PITCH, KEY_Y = 16.0, 7.0, 69.5     # header pin 1, rot 90 (pins run up), pin 2 at KEY_Y - 2.5
KEY_DIODE_Y, KEY_LABEL_Y = 61.5, 73.2          # diode above the header, name below it
KEY_POS = {}   # name -> x of the header, for silkscreen
dn = 1
for i, (name, mat) in enumerate(KEYS):
    hx, hy, hrot = KEY_X0 + i * KEY_PITCH, KEY_Y, 90
    dx, dy, drot = hx, KEY_DIODE_Y, 90
    KEY_POS[name] = hx
    row, col_i = divmod(i, 7)
    sx, sy = 78 + col_i * 20, 8 + row * 8
    if mat is None:
        add("K%d" % (i + 1), "Connector_Generic:Conn_01x02", "KEY %s (direct D10) JST-XH" % name, XH2_FP,
            {"1": "KEY_C4", "2": "GND"}, sch=(sx, sy, 0), pcb=(hx, hy, hrot), mpn=XH2_MPN)
    else:
        c, r = mat
        mid = "K%s_D" % name.replace("#", "s")
        add("K%d" % (i + 1), "Connector_Generic:Conn_01x02", "%s [c%d r%d] JST-XH" % (name, c, r), XH2_FP,
            {"1": "ROW%d" % r, "2": mid}, sch=(sx, sy, 0), pcb=(hx, hy, hrot), mpn=XH2_MPN)
        add("D%d" % dn, "Device:D", "1N4148W", DIODE_FP,
            {"2": mid, "1": "COL%d" % c}, sch=(sx + 6, sy, 180), pcb=(dx, dy, drot), lcsc="C81598")
        dn += 1

# --- Pot: master volume only, JST-XH 3-pin on the right edge --------------------------------
# The four bank pots of v0.3 are replaced by I2C rotary encoders on J15 (STEMMA QT).  Their
# ADC pins (A1, A2, A4, A9) go to the expansion header instead.
POTS = [("J10", "POT_VOL", "VOL")]
POT_X, POT_Y0, POT_PITCH = 5.5, 16.0, 8.5        # left edge, up by the USB-C, where the pot sits on the panel
for i, (ref, net, label) in enumerate(POTS):
    add(ref, "Connector_Generic:Conn_01x03", "Pot %s (10k lin, panel) JST-XH" % label, XH3_FP,
        {"1": "+3.3VA", "2": net, "3": "GND"}, sch=(78 + i * 12, 36, 0), pcb=(POT_X, POT_Y0 + i * POT_PITCH, 90), mpn=XH3_MPN)

# --- USB-C: MIDI data on D29/D30 (libDaisy EXTERNAL) and the charger's input ---------
add("J1", "Connector:USB_C_Receptacle_USB2.0_16P", "USB-C (MIDI + 5V power)",
    "Connector_USB:USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal",
    {"S1": "GND", "SH": "GND", "A1": "GND", "A12": "GND", "B1": "GND", "B12": "GND",   # shield pad is S1 (KiCad 9 lib) or SH (KiCad 10)
     "A4": "VBUS", "A9": "VBUS", "B4": "VBUS", "B9": "VBUS",
     "A5": "CC1", "B5": "CC2", "A6": "USB_DP", "B6": "USB_DP", "A7": "USB_DM", "B7": "USB_DM",
     "A8": None, "B8": None},
    sch=(20, 100, 0), pcb=(16.0, 3.675, 180), mpn="USB4105-GF-A", lcsc="C3020560")   # footprint "PCB Edge" line lands on y=0
# ESD on the data pair: USBLC6-2SC6 (SOT-23-6) right behind the receptacle.  Both I/O pins of
# each pair carry the same net, so it sits on the lines rather than in series with them.
add("U4", "Power_Protection:USBLC6-2P6", "USBLC6-2SC6", "Package_TO_SOT_SMD:SOT-23-6",
    {"1": "USB_DP", "6": "USB_DP", "3": "USB_DM", "4": "USB_DM", "5": "VBUS", "2": "GND"},
    sch=(32, 108, 0), pcb=(17.5, 14.0, 0), lcsc="C7519", mpn="USBLC6-2SC6",
    desc="ST USBLC6-2SC6 USB 2.0 ESD protection, SOT-23-6")
R_FP = "Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal"
R_SMD = "Resistor_SMD:R_0805_2012Metric"
C_SMD = "Capacitor_SMD:C_0805_2012Metric"
add("R1", "Device:R", "5k1", R_SMD, {"1": "CC1", "2": "GND"}, sch=(40, 96, 0), pcb=(24.0, 18.0, 0), lcsc="C27834")
add("R2", "Device:R", "5k1", R_SMD, {"1": "CC2", "2": "GND"}, sch=(46, 96, 0), pcb=(24.0, 21.0, 0), lcsc="C27834")
# SMD PTC on the USB input (the v0.3 radial MF-R250 collided with the Seed socket).  VUSB is
# the charger's input; the +5V rail is made by the boost converter further down.
add("F1", "Device:Polyfuse", "MF-MSMF250/16X-2 2.5A PTC", "Fuse:Fuse_1812_4532Metric",
    {"1": "VBUS", "2": "VUSB"}, sch=(60, 100, 0), pcb=(23.0, 11.5, 90), lcsc="C210838", mpn="MF-MSMF250/16X-2")
# Bulk on the +5V rail next to the Seed VIN pin, for the amp's peaks
add("C1", "Device:C_Polarized", "470u 10V", "Capacitor_THT:CP_Radial_D8.0mm_P3.50mm",
    {"1": "+5V", "2": "GND"}, sch=(90, 100, 0), pcb=(54.0, 12.0, 0), mpn="EEU-FR1A471")
add("C6", "Device:C", "100n", C_SMD, {"1": "+5V", "2": "GND"}, sch=(98, 100, 0), pcb=(50.0, 5.0, 0), lcsc="C49678")

# --- Speaker amp: MAX98306 (TDFN-14, exposed pad) ------------------------------------------
# Same circuit as Adafruit #987: 1u on every input (single-ended: the - inputs go to GND
# through their cap), 10u + 100n on PVDD, 100k pull-up on ~SHDN (Q1 pulls it low to mute),
# gain by the GAIN pin: R13 100k to PVDD = 9 dB.  JP1 straps GAIN to PVDD (12 dB) or GND
# (18 dB) instead; no R13 and JP1 open = 6 dB.  EP + thermal vias to GND.
U3X, U3Y = 60.0, 46.0
add("U3", "SynthMachine:MAX98306", "MAX98306ETD+T", "Package_DFN_QFN:TDFN-14-1EP_3x3mm_P0.4mm_EP1.78x2.35mm_ThermalVias",
    {"1": "GND", "8": "GND", "15": "GND", "2": "AMP_SD", "3": "AMP_INL", "4": "AMP_INLN", "5": "AMP_GAIN",
     "6": "AMP_INRN", "7": "AMP_INR", "9": "SPK_RN", "10": "SPK_RP", "11": "+5V", "12": "+5V", "13": "SPK_LP", "14": "SPK_LN"},
    sch=(120, 100, 0), pcb=(U3X, U3Y, 0), lcsc="C124549", mpn="MAX98306ETD+T",
    desc="Analog Devices MAX98306 stereo 3.7W class-D amplifier, TDFN-14 3x3 EP")
add("C16", "Device:C", "1u", C_SMD, {"1": "AUDIO_L", "2": "AMP_INL"}, sch=(104, 94, 90), pcb=(53.0, U3Y - 4.0, 0), lcsc="C28323")
add("C18", "Device:C", "1u", C_SMD, {"1": "GND", "2": "AMP_INLN"}, sch=(110, 94, 90), pcb=(53.0, U3Y - 1.5, 0), lcsc="C28323")
add("C19", "Device:C", "1u", C_SMD, {"1": "GND", "2": "AMP_INRN"}, sch=(110, 106, 90), pcb=(53.0, U3Y + 1.5, 0), lcsc="C28323")
add("C17", "Device:C", "1u", C_SMD, {"1": "AUDIO_R", "2": "AMP_INR"}, sch=(104, 106, 90), pcb=(53.0, U3Y + 4.0, 0), lcsc="C28323")
add("C14", "Device:C", "10u", C_SMD, {"1": "+5V", "2": "GND"}, sch=(134, 94, 90), pcb=(68.0, U3Y - 0.4, 0), lcsc="C15850")
add("C15", "Device:C", "100n", C_SMD, {"1": "+5V", "2": "GND"}, sch=(140, 94, 90), pcb=(68.0, U3Y + 2.0, 0), lcsc="C49678")
add("R13", "Device:R", "100k", R_SMD, {"1": "AMP_GAIN", "2": "+5V"}, sch=(134, 106, 90), pcb=(57.0, U3Y + 6.0, 0), lcsc="C149504")
add("R14", "Device:R", "100k", R_SMD, {"1": "AMP_SD", "2": "+5V"}, sch=(140, 106, 90), pcb=(63.0, U3Y + 6.0, 0), lcsc="C149504")
add("JP1", "Jumper:SolderJumper_3_Open", "GAIN: 1-2 = 18dB, open = R13, 2-3 = 12dB",
    "Jumper:SolderJumper-3_P1.3mm_Open_RoundedPad1.0x1.5mm",
    {"1": "GND", "2": "AMP_GAIN", "3": "+5V"}, sch=(128, 112, 0), pcb=(66.0, 57.0, 0))   # in the channel above the key diodes
# Speaker outputs -> 0805 ferrite bead + 220p EMI filter (MAX98306 datasheet) -> JST-PH plugs.
# Bead rows top->bottom follow the hand-routed fan-out below: LN, LP, RP, RN.
FB_FP = "Inductor_SMD:L_0805_2012Metric"
FB_ROWS = {"LN": U3Y - 6.5, "LP": U3Y - 4.0, "RP": U3Y + 4.0, "RN": U3Y + 6.5}
for i, sig in enumerate(["LN", "LP", "RP", "RN"]):
    add("FB%d" % (i + 1), "Device:FerriteBead", "100R@100MHz 0805", FB_FP,
        {"1": "SPK_" + sig, "2": "SPKF_" + sig}, sch=(150 + i * 8, 96, 90), pcb=(74.0, FB_ROWS[sig], 0), lcsc="C1015")
    add("C%d" % (i + 2), "Device:C", "220p", C_SMD,
        {"1": "SPKF_" + sig, "2": "GND"}, sch=(150 + i * 8, 106, 0), pcb=(78.0, FB_ROWS[sig], 0), lcsc="C53172")
JST_FP = "Connector_JST:JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical"
add("J5", "Connector_Generic:Conn_01x02", "Speaker L (JST-PH)", JST_FP,
    {"1": "SPKF_LP", "2": "SPKF_LN"}, sch=(190, 96, 0), pcb=(85.0, U3Y - 4.0, 0), mpn="B2B-PH-K-S(LF)(SN)")
add("J6", "Connector_Generic:Conn_01x02", "Speaker R (JST-PH)", JST_FP,
    {"1": "SPKF_RP", "2": "SPKF_RN"}, sch=(190, 106, 0), pcb=(85.0, U3Y + 4.0, 0), mpn="B2B-PH-K-S(LF)(SN)")

# --- Headphone jack on the top edge, plug detect mutes the speaker amp ----------------------
# Tip/ring from U2.  TN is shorted to T while nothing is plugged in, so HP_DET sits at ~0 V
# (R4 pull-down on HP_L) and rises to 3V3 (R3 pull-up) when a plug opens the contact.  Q1, a
# 2N7002, then pulls the amp's SD low -> speakers off, headphones on.  A MOSFET gate draws
# no current, so unlike v0.3's BJT it does not clamp HP_DET, and D13 reads the plug directly.
# Its 1-2 V threshold also clears the audio peaks on the node while unplugged.
# The firmware mute (D0) has its own MOSFET Q2 with the same drain: two independent
# open-drain pull-downs, a proper wired-OR.  R15 pulls MUTE up, so the speakers are muted
# at reset, in DFU mode and after a crash; firmware drives D0 low to run them.
add("J7", "Connector_Audio:AudioJack3_SwitchTR", "Headphones 3.5mm (CUI SJ1-3515N)",
    "Connector_Audio:Jack_3.5mm_CUI_SJ1-3515N_Horizontal",
    {"S": "GND", "T": "HP_L", "R": "HP_R", "TN": "HP_DET", "RN": None},
    sch=(20, 130, 0), pcb=(78.0, 4.6, 270), mpn="SJ1-3515N")   # opening faces the top edge; nose 1.5 mm proud of it
add("R3", "Device:R", "100k", R_SMD, {"1": "+3V3", "2": "HP_DET"}, sch=(36, 126, 0), pcb=(52.0, 32.0, 0), lcsc="C149504")
add("R4", "Device:R", "10k", R_SMD, {"1": "HP_L", "2": "GND"}, sch=(42, 126, 0), pcb=(80.0, 36.0, 0), lcsc="C17414")
add("R5", "Device:R", "10k", R_SMD, {"1": "HP_DET", "2": "Q1_G"}, sch=(52, 126, 0), pcb=(52.0, 27.0, 0), lcsc="C17414")
add("Q1", "Transistor_FET:Q_NMOS_GSD", "2N7002", "Package_TO_SOT_SMD:SOT-23",
    {"1": "Q1_G", "2": "GND", "3": "AMP_SD"}, sch=(68, 128, 0), pcb=(56.5, 29.0, 0), lcsc="C8545", mpn="2N7002",
    desc="N-MOSFET 60V 115mA SOT-23, headphone plug detect -> speaker amp shutdown")
add("R6", "Device:R", "10k", R_SMD, {"1": "MUTE", "2": "Q2_G"}, sch=(58, 138, 0), pcb=(52.0, 34.5, 0), lcsc="C17414")
add("R15", "Device:R", "10k", R_SMD, {"1": "+3V3", "2": "MUTE"}, sch=(46, 138, 0), pcb=(52.0, 37.0, 0), lcsc="C17414")
add("Q2", "Transistor_FET:Q_NMOS_GSD", "2N7002", "Package_TO_SOT_SMD:SOT-23",
    {"1": "Q2_G", "2": "GND", "3": "AMP_SD"}, sch=(68, 140, 0), pcb=(56.5, 34.0, 0), lcsc="C8545", mpn="2N7002",
    desc="N-MOSFET 60V 115mA SOT-23, firmware speaker mute (D0, high = mute)")

# --- Headphone amp: TI TPA6138A2 (TSSOP-14), DirectPath ground-centred outputs ---------
# Inverting stage per channel, gain = -Rfb/Rin = -1 (10k/10k), 1u input caps (fc ~16 Hz),
# 47p across Rfb, 1u charge-pump flying cap CP-CN, 1u on VSS, 10u on VDD.  Runs from the
# Seed's 3V3 rail (14-25 mA).  Mute is active-low: R12 pulls it up so it runs by default,
# D14 can pull it low from firmware.  UVP has an internal pull-up and is left open.
add("U2", "SynthMachine:TPA6138A2", "TPA6138A2PWR", "Package_SO:TSSOP-14_4.4x5mm_P0.65mm",
    {"14": "GND", "13": "HP_INL", "1": "GND", "2": "HP_INR", "5": "HP_MUTE", "11": None, "9": "+3V3",
     "12": "HP_L", "3": "HP_R", "8": "HP_CP", "7": "HP_CN", "6": "HP_VSS", "4": "GND", "10": "GND"},
    sch=(146, 128, 0), pcb=(83.0, 30.0, 0), lcsc="C183097", mpn="TPA6138A2PWR",
    desc="TI TPA6138A2 40mW DirectPath stereo headphone amplifier, TSSOP-14, 3.3V")
HP_COL = {"L": 75.0, "R": 70.0}   # 1 mm left of v0.3: room for the router between R9 and U2
for ch, y_s in (("L", 122), ("R", 134)):
    col = HP_COL[ch]
    # input caps stand vertical (rot 270 -> pad 1 on top) so the audio vias can drop straight in
    add("C%d" % (7 if ch == "L" else 8), "Device:C", "1u", C_SMD, {"1": "AUDIO_" + ch, "2": "HP_IN%s_C" % ch},
        sch=(108, y_s, 90), pcb=(col, 22.5, 270), lcsc="C28323")
    add("R%d" % (8 if ch == "L" else 10), "Device:R", "10k", R_SMD, {"1": "HP_IN%s_C" % ch, "2": "HP_IN" + ch},
        sch=(116, y_s, 90), pcb=(col, 26.0, 0), lcsc="C17414")
    add("R%d" % (9 if ch == "L" else 11), "Device:R", "10k", R_SMD, {"1": "HP_IN" + ch, "2": "HP_" + ch},
        sch=(124, y_s, 90), pcb=(col, 29.5, 0), lcsc="C17414")
    add("C%d" % (9 if ch == "L" else 10), "Device:C", "47p", C_SMD, {"1": "HP_IN" + ch, "2": "HP_" + ch},
        sch=(132, y_s, 90), pcb=(col, 33.0, 0), lcsc="C14857")
add("C11", "Device:C", "1u", C_SMD, {"1": "HP_CP", "2": "HP_CN"}, sch=(166, 122, 90), pcb=(70.0, 36.5, 0), lcsc="C28323")
add("C12", "Device:C", "1u", C_SMD, {"1": "HP_VSS", "2": "GND"}, sch=(172, 122, 90), pcb=(75.0, 36.5, 0), lcsc="C28323")
add("C13", "Device:C", "10u", C_SMD, {"1": "+3V3", "2": "GND"}, sch=(178, 122, 90), pcb=(86.0, 36.0, 0), lcsc="C15850")
add("R12", "Device:R", "100k", R_SMD, {"1": "+3V3", "2": "HP_MUTE"}, sch=(184, 122, 90), pcb=(66.0, 36.0, 0), lcsc="C149504")

# --- Expansion header (spare Seed pins) -------------------------------------
add("J8", "Connector_Generic:Conn_01x12", "Expansion",
    "Connector_PinHeader_2.54mm:PinHeader_1x12_P2.54mm_Vertical",
    {"1": "HP_MUTE", "2": "EXP_A1", "3": "EXP_A2", "4": "EXP_A4", "5": "EXP_A6", "6": "EXP_A9",
     "7": "HP_DET", "8": "MUTE", "9": "VSYS", "10": "+3V3", "11": "+5V", "12": "GND"},
    sch=(200, 40, 0), pcb=(93.0, 10.0, 90), mpn="PPTC121LFBN-RC")

# --- Display header: hardware SPI1 + D/C + reset -------------------------------------------
# SSD1306/SH1106 OLED (4-wire SPI) or a Sharp memory LCD (CLK = SCK, DI = MOSI, CS = NSS,
# active high, driven as a GPIO) both plug in here.  5V is for a TFT backlight.
add("J9", "Connector_Generic:Conn_01x08", "Display (SPI1)",
    "Connector_PinHeader_2.54mm:PinHeader_1x08_P2.54mm_Vertical",
    {"1": "GND", "2": "+3V3", "3": "+5V", "4": "SPI_SCK", "5": "SPI_MOSI", "6": "SPI_NSS", "7": "DISP_DC", "8": "DISP_RST"},
    sch=(200, 62, 0), pcb=(126.0, 10.0, 90), mpn="PPTC081LFBN-RC")

# --- STEMMA QT / Qwiic: I2C1 for the seesaw encoder breakouts ------------------------------
# JST SH 4-pin, Adafruit/SparkFun pinout: 1 GND, 2 3V3, 3 SDA, 4 SCL.  The breakouts carry
# their own pull-ups; R16/R17 are footprints only (DNP) in case a chain needs stronger ones.
add("J15", "Connector_Generic:Conn_01x04", "STEMMA QT (I2C1)",
    "Connector_JST:JST_SH_BM04B-SRSS-TB_1x04-1MP_P1.00mm_Vertical",
    {"1": "GND", "2": "+3V3", "3": "I2C_SDA", "4": "I2C_SCL"},
    sch=(200, 80, 0), pcb=(150.0, 11.0, 0), lcsc="C160390", mpn="BM04B-SRSS-TB(LF)(SN)")   # top entry, cable leaves upward
add("R16", "Device:R", "4k7 (DNP)", R_SMD, {"1": "+3V3", "2": "I2C_SDA"}, sch=(210, 88, 90), pcb=(150.0, 16.5, 0), dnp=True)
add("R17", "Device:R", "4k7 (DNP)", R_SMD, {"1": "+3V3", "2": "I2C_SCL"}, sch=(216, 88, 90), pcb=(150.0, 20.5, 0), dnp=True)

# --- Battery: BQ24074 charger with power path, TPS61023 5 V boost --------------------------
# VBUS -> F1 -> VUSB -> U5 IN.  U5 OUT (VSYS) is 4.4 V regulated while USB is present and the
# battery otherwise, with the battery supplementing USB on peaks (DPPM).  VSYS feeds the boost,
# which makes the +5V rail for the Seed VIN and the speaker amp; so the boost carries the whole
# load on USB too, which its 3.7 A switch handles at that easy ratio.
# Charger settings: EN2 = high, EN1 = low -> input limit from R19 (1.1k: 1.5 A, VIN-DPM backs it
# off on a weak port); R18 1.8k -> 0.5 A fast charge (0.25 C for a 2000 mAh cell, and only
# 0.65 W in the QFN); TMR and ITERM open -> default 30 min / 5 h timers and 10 % termination;
# CE low -> charging enabled; TS 10k to VSS (no pack thermistor).  ~CHG and ~PGOOD are open
# drain, pulled up to 3V3, read by A5 / A11.  Use a protected cell (Adafruit/SparkFun LiPos).
add("J17", "Connector_Generic:Conn_01x02", "Battery 1S LiPo (JST-PH, 1 = +)", JST_FP,
    {"1": "VBAT", "2": "GND"}, sch=(16, 152, 0), pcb=(100.0, 22.0, 0), mpn="B2B-PH-K-S(LF)(SN)")
add("U5", "Battery_Management:BQ24074RGT", "BQ24074RGTR",
    "Package_DFN_QFN:VQFN-16-1EP_3x3mm_P0.5mm_EP1.6x1.6mm_ThermalVias",
    {"1": "TS", "2": "VBAT", "3": "VBAT", "4": "GND", "5": "VSYS", "6": "GND", "7": "USB_PGOOD", "8": "GND",
     "9": "CHG_STAT", "10": "VSYS", "11": "VSYS", "12": "ILIM", "13": "VUSB", "14": None, "15": None, "16": "ISET", "17": "GND"},
    sch=(44, 154, 0), pcb=(113.0, 24.0, 0), lcsc="C54313", mpn="BQ24074RGTR",
    desc="TI BQ24074 1.5 A single-cell Li-ion charger with power path, VQFN-16 3x3")
add("C20", "Device:C", "1u", C_SMD, {"1": "VUSB", "2": "GND"}, sch=(28, 148, 90), pcb=(107.0, 20.0, 90), lcsc="C28323")
add("C21", "Device:C", "10u", C_SMD, {"1": "VSYS", "2": "GND"}, sch=(60, 148, 90), pcb=(119.0, 20.0, 90), lcsc="C15850")
add("C22", "Device:C", "10u", C_SMD, {"1": "VBAT", "2": "GND"}, sch=(28, 158, 90), pcb=(107.0, 28.0, 90), lcsc="C15850")
add("R18", "Device:R", "1k8 (ISET 0.5A)", R_SMD, {"1": "ISET", "2": "GND"}, sch=(60, 158, 90), pcb=(119.0, 28.0, 90), mpn="0805 1% 1.8k")
add("R19", "Device:R", "1k1 (ILIM 1.5A)", R_SMD, {"1": "ILIM", "2": "GND"}, sch=(66, 158, 90), pcb=(122.5, 28.0, 90), mpn="0805 1% 1.1k")
add("R20", "Device:R", "10k", R_SMD, {"1": "TS", "2": "GND"}, sch=(34, 158, 90), pcb=(107.5, 32.0, 90), lcsc="C17414")
add("R21", "Device:R", "100k", R_SMD, {"1": "+3V3", "2": "USB_PGOOD"}, sch=(72, 150, 90), pcb=(111.0, 32.0, 90), lcsc="C149504")
add("R22", "Device:R", "100k", R_SMD, {"1": "+3V3", "2": "CHG_STAT"}, sch=(78, 150, 90), pcb=(114.5, 32.0, 90), lcsc="C149504")
# Battery voltage to the ADC: VBAT/2, 0 to 2.1 V, 21 uA drain
add("R23", "Device:R", "100k", R_SMD, {"1": "VBAT", "2": "VBAT_SENSE"}, sch=(84, 150, 90), pcb=(118.0, 32.0, 90), lcsc="C149504")
add("R24", "Device:R", "100k", R_SMD, {"1": "VBAT_SENSE", "2": "GND"}, sch=(90, 150, 90), pcb=(121.5, 32.0, 90), lcsc="C149504")
add("C26", "Device:C", "100n", C_SMD, {"1": "VBAT_SENSE", "2": "GND"}, sch=(96, 150, 90), pcb=(125.0, 32.0, 90), lcsc="C49678")
# Power switch: a panel SPST on J16 pulls the boost's EN up to VSYS (through R28); R27 holds it
# off otherwise.  JP2 bridges the switch for a bench board with no panel switch.  The charger
# keeps charging with the switch off, and the boost's EN pin draws nothing, so any small switch
# will do.
add("J16", "Connector_Generic:Conn_01x02", "Power switch (panel SPST) JST-XH", XH2_FP,
    {"1": "SW_HI", "2": "BOOST_EN"}, sch=(16, 160, 0), pcb=(5.5, 40.0, 90), mpn=XH2_MPN)   # left edge, mid-height, like the panel switch
add("JP2", "Jumper:SolderJumper_2_Open", "always on (bridges the power switch)",
    "Jumper:SolderJumper-2_P1.3mm_Open_RoundedPad1.0x1.5mm",
    {"1": "SW_HI", "2": "BOOST_EN"}, sch=(24, 164, 0), pcb=(17.0, 40.0, 90))   # beside J16, room for an iron and the label
add("R28", "Device:R", "10k", R_SMD, {"1": "VSYS", "2": "SW_HI"}, sch=(30, 164, 90), pcb=(124.5, 36.5, 0), lcsc="C17414")
add("R27", "Device:R", "100k", R_SMD, {"1": "BOOST_EN", "2": "GND"}, sch=(36, 164, 90), pcb=(124.5, 39.0, 0), lcsc="C149504")
# Boost: TPS61023, 1 uH, 10 uF in, 2 x 22 uF + C1 out, 750k/100k -> 5.1 V (VREF 0.6 V).  About
# 1.5 A continuous at 5 V from a 3.3 V cell, more from USB's 4.4 V.  Inductor per TI's table;
# XGL4030-102MEC (LCSC C6336766) is the stocked equivalent.
add("U6", "SynthMachine:TPS61023", "TPS61023DRLR", "Package_TO_SOT_SMD:SOT-563",
    {"1": "BOOST_FB", "2": "BOOST_EN", "3": "VSYS", "4": "GND", "5": "BOOST_SW", "6": "+5V"},
    sch=(110, 156, 0), pcb=(132.0, 40.0, 0), lcsc="C919459", mpn="TPS61023DRLR",
    desc="TI TPS61023 3.7 A boost converter, SOT-563")
add("L1", "Device:L", "1u 4x4 (XEL4030-102ME)", "Inductor_SMD:L_Coilcraft_XxL4030",
    {"1": "VSYS", "2": "BOOST_SW"}, sch=(100, 152, 0), pcb=(132.5, 46.5, 0), mpn="XEL4030-102MEC")
add("C23", "Device:C", "10u", C_SMD, {"1": "VSYS", "2": "GND"}, sch=(100, 160, 90), pcb=(128.2, 44.5, 270), lcsc="C15850")   # rot 270: pad 1 (VSYS) on top
C_1210 = "Capacitor_SMD:C_1210_3225Metric"
add("C24", "Device:C", "22u 25V", C_1210, {"1": "+5V", "2": "GND"}, sch=(122, 150, 90), pcb=(137.5, 39.5, 270), lcsc="C52306", mpn="CL32A226KAJNNNE")
add("C25", "Device:C", "22u 25V", C_1210, {"1": "+5V", "2": "GND"}, sch=(128, 150, 90), pcb=(137.5, 44.5, 270), lcsc="C52306", mpn="CL32A226KAJNNNE")
add("R25", "Device:R", "750k (FB, 5.1V)", R_SMD, {"1": "+5V", "2": "BOOST_FB"}, sch=(122, 160, 90), pcb=(128.0, 39.0, 0), mpn="0805 1% 750k")
add("R26", "Device:R", "100k", R_SMD, {"1": "BOOST_FB", "2": "GND"}, sch=(128, 160, 90), pcb=(128.0, 36.5, 0), lcsc="C149504")

# --- Mounting holes ----------------------------------------------------------
for i, (hx, hy) in enumerate([(5, 4), (155, 4), (5, 70), (155, 70)]):
    add("H%d" % (i + 1), "Mechanical:MountingHole", "M3", "MountingHole:MountingHole_3.2mm_M3", {},
        sch=(200 + i * 8, 120, 0), pcb=(float(hx), float(hy), 0))

# Hand-routed nets, locked before the autorouter runs (see route.py).  Endpoints are
# either (x, y) in mm or ("REF", "pad") resolved to that pad's centre; 4th element = width.
# Seed line out (U1.18/19, left column) -> amp input caps on F.Cu as nested L shapes running
# under the Seed's lower edge; same pins -> headphone amp on B.Cu, threading between the
# Seed's pad rows, via up next to each input cap.
_R = U3X + 1.49   # MAX98306 right-side pad column; pins 14..8 top->bottom at 0.4 mm pitch
PREROUTES = [
    # AUDIO_L threads between the Seed's pad rows (y 46.82 sits between pins 23 and 22) and
    # comes up to C16; AUDIO_R loops under the Seed's lower edge to C17.  No crossings.
    ("AUDIO_L", "F.Cu", [("U1", "18"), (31.5, 46.82), (47.5, 46.82), (47.5, "C16:1"), ("C16", "1")]),
    ("AUDIO_R", "F.Cu", [("U1", "19"), (28.0, None), (28.0, 52.5), (51.0, 52.5), (51.0, "C17:1"), ("C17", "1")]),
    ("AUDIO_L", "B.Cu", [("U1", "18"), (31.5, 46.82), (47.5, 46.82), (47.5, 19.4), (75.0, 19.4)]),
    ("AUDIO_L", "VIA", (75.0, 19.4)),
    ("AUDIO_L", "F.Cu", [(75.0, 19.4), ("C7", "1")]),
    ("AUDIO_R", "B.Cu", [("U1", "19"), (31.5, 49.36), (48.3, 49.36), (48.3, 20.5), (70.0, 20.5)]),
    ("AUDIO_R", "VIA", (70.0, 20.5)),
    ("AUDIO_R", "F.Cu", [(70.0, 20.5), ("C8", "1")]),
    # MAX98306 right-side fan-out (pins top->bottom: 14 13 12 11 10 9 8): 0.2 mm stubs from the
    # 0.4 mm pitch pads straight to the ferrite beads / decoupling caps on F.Cu.
    ("SPK_LN", "F.Cu", [("U3", "14"), (U3X + 3.0, None), (U3X + 4.8, U3Y - 3.0), (U3X + 4.8, FB_ROWS["LN"]), ("FB1", "1")], 0.2),
    ("SPK_LP", "F.Cu", [("U3", "13"), (U3X + 3.6, None), (U3X + 5.4, U3Y - 2.6), (U3X + 5.4, FB_ROWS["LP"]), ("FB2", "1")], 0.2),
    ("+5V", "F.Cu", [("U3", "12"), ("C14", "1")], 0.2),
    ("+5V", "F.Cu", [("U3", "11"), (U3X + 4.5, None), (U3X + 5.8, "C15:1"), ("C15", "1")], 0.2),
    ("+5V", "F.Cu", [("C14", "1"), ("C15", "1")], 0.3),
    # the decoupling-cap +5V island is boxed in by the speaker stubs; give the autorouter a
    # 0.5 mm exit to the open area right of the caps
    ("+5V", "F.Cu", [("C14", "1"), (None, U3Y - 2.4), (70.5, U3Y - 2.4)], 0.5),
    ("+5V", "VIA", (70.5, U3Y - 2.4)),      # ...and a via so the feed can arrive on B.Cu
    ("SPK_RP", "F.Cu", [("U3", "10"), (U3X + 3.6, None), (U3X + 5.4, U3Y + 2.6), (U3X + 5.4, FB_ROWS["RP"]), ("FB3", "1")], 0.2),
    ("SPK_RN", "F.Cu", [("U3", "9"), (U3X + 3.0, None), (U3X + 4.8, U3Y + 3.0), (U3X + 4.8, FB_ROWS["RN"]), ("FB4", "1")], 0.2),
    ("GND", "F.Cu", [("U3", "8"), (None, U3Y + 2.4), (U3X, U3Y + 2.4), (U3X, U3Y + 1.0)], 0.2),   # into the exposed pad
    # TPS61023 (SOT-563, 0.5 mm pitch): 0.25 mm stubs off the power pins, because the 0.6 mm
    # Power-class tracks cannot land on 0.3 mm pads.  Pins 1-3 left (FB, EN, VIN), 4-6 right
    # (GND, SW, VOUT); the router picks the stubs up from their far ends.
    ("VSYS", "F.Cu", [("U6", "3"), (128.2, None), ("C23", "1")], 0.25),          # VIN -> input cap (top pad)
    ("VSYS", "F.Cu", [("C23", "1"), (131.3, "C23:1"), ("L1", "1")], 0.4),         # input cap -> inductor (L1 pad 1 x)
    ("BOOST_SW", "F.Cu", [("U6", "5"), (134.6, None)], 0.25),                    # thin off the 0.35 mm pad
    ("BOOST_SW", "F.Cu", [(134.6, 40.0), (134.6, 43.6), (133.7, 43.6), ("L1", "2")], 0.4),
    ("+5V", "F.Cu", [("U6", "6"), (136.0, None), (136.0, "C24:1"), ("C24", "1")], 0.25),   # VOUT -> output cap (top pad)
    ("GND", "F.Cu", [("U6", "4"), (None, 42.4)], 0.25),
    ("+5V", "F.Cu", [("C24", "1"), (139.6, "C24:1"), (139.6, "C25:1"), ("C25", "1")], 0.6),   # both output caps, around C24's GND pad
    ("VSYS", "F.Cu", [("R28", "1"), (122.3, None), (122.3, 40.95), (128.2, 40.95)], 0.4),      # switch pull-up -> boost input, under R27/R25
    ("VSYS", "F.Cu", [("U5", "11"), (116.25, None)], 0.2),                                       # charger OUT (0.5 mm pitch) ...
    ("VSYS", "F.Cu", [(116.25, "U5:11"), (116.25, 36.5), (122.3, 36.5)], 0.4),                  # ... down between the resistor rows to R28
    ("VSYS", "F.Cu", [("U5", "5"), (None, 27.5)], 0.2),                                          # EN2 (bottom row) = VSYS: stub down ...
    ("+5V", "F.Cu", [("R25", "1"), (128.0, None), (128.0, 34.5), (136.0, 34.5), (136.0, 37.9)], 0.25),   # FB divider top -> +5V, threading between R25/R26 pads
    ("+5V", "F.Cu", [(136.0, 34.5), (136.0, 13.5), (131.08, 13.5), ("J9", "3")], 0.6),                  # +5V trunk from the boost up to the display header
    ("VSYS", "F.Cu", [(112.25, 27.5), (116.25, 27.5)], 0.4),                                     # ... and across to the same rail
    # GND stitching vias in open areas, so the two pours stay one net wherever the
    # autorouter's GND tracks leave a front-side island
    *[("GND", "VIA", xy) for xy in ((10.0, 30.0), (10.0, 50.0), (26.5, 62.0), (66.0, 14.0), (91.0, 30.0),
                                    (100.0, 47.0), (116.0, 44.0), (110.0, 50.0), (148.0, 64.0))],
]
PREROUTE_WIDTH = 0.3

# --- Expansion header (spare Seed pins) -------------------------------------
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
TPS61023_SYMBOL = build_box_symbol(
    "TPS61023",
    [("3", "VIN", "power_in"), ("2", "EN", "input"), ("1", "FB", "input")],
    [("6", "VOUT", "power_out"), ("5", "SW", "passive"), ("4", "GND", "power_in")],
    "TPS61023", "Package_TO_SOT_SMD:SOT-563",
    "TI TPS61023 3.7 A valley-current boost converter, 0.5 V start-up, SOT-563",
    "https://www.ti.com/lit/ds/symlink/tps61023.pdf")
PROJECT_SYMBOLS = {"DaisySeed": DAISY_SEED_SYMBOL, "TPA6138A2": TPA6138A2_SYMBOL, "MAX98306": MAX98306_SYMBOL,
                   "TPS61023": TPS61023_SYMBOL}

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
    lines = ['  (symbol (lib_id "%s") (at %s %s %d) (unit 1) (exclude_from_sim no) (in_bom %s) (on_board yes) (dnp %s) (fields_autoplaced yes)'
             % (p.lib_id, fmt(X), fmt(Y), R, "no" if p.ref.startswith(("H", "#")) else "yes", "yes" if getattr(p, "dnp", False) else "no"),
             '    (uuid "%s")' % p.uuid]
    rx, ry = ref_prop_pos
    props = [("Reference", p.ref, rx, ry, False), ("Value", p.value, rx, ry + 1.27, False),
             ("Footprint", p.footprint, X, Y, True), ("Datasheet", "~", X, Y, True), ("Description", p.desc, X, Y, True)]
    if getattr(p, "lcsc", ""):
        props.append(("LCSC", p.lcsc, X, Y, True))
    if getattr(p, "mpn", ""):
        props.append(("MPN", p.mpn, X, Y, True))
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
           '  (title_block (title "synthMachine carrier board") (rev "0.4") (company "") (comment 1 "Generated by hardware/v0.4/gen_kicad.py - edit freely, or edit the generator and re-run"))']
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
    # (+5V is driven by U6's VOUT, a power output, so it needs no flag)
    for net, x, y in (("GND", 106 * G, 92 * G), ("VBUS", 118 * G, 92 * G), ("VUSB", 126 * G, 92 * G)):
        if net in POWER_NETS:
            place_power(net, x, y)
        else:
            out.extend(sch_global_label(net, x, y, 270))
        place_power(net, x, y, flag=True)

    notes = [
        ("KEY MATRIX: columns D4-D9 driven low one at a time, rows D1-D3 read with pull-ups (see scanButtonMatrix). Diode anode to switch, cathode to column.", 78, 3),
        ("C4 is a direct key on D10 to GND (firmware uses internal pull-up).  BTN1-6 = top-row buttons on the 6 unused matrix slots (NOTE_MAPPING -1 entries).", 78, 5),
        ("POT: master volume, 10k linear on JST-XH 3-pin: 1 = +3V3A, 2 = wiper -> A0, 3 = AGND. The four bank controls are I2C encoders on J15. KEYS: panel buttons on JST-XH 2-pin, one per key.", 78, 32),
        ("POWER: VBUS -> F1 2.5A PTC -> VUSB -> U5 charger (power path) -> VSYS -> U6 boost -> +5V for Seed VIN and the amp. 5.1k CC pull-downs advertise a 1.5A sink. U4 = ESD on D+/D-.", 20, 88),
        ("USB-C data to D29/D30 = Daisy 'external' USB. In firmware use MidiUsbTransport::Config::EXTERNAL.", 20, 90),
        ("AMP: MAX98306 on board, single-ended inputs (1u caps, - inputs to GND). Gain: R13 100k to PVDD = 9 dB, JP1 straps GAIN to GND (18 dB) or PVDD (12 dB). Outputs -> ferrite + 220p EMI filter -> JST-PH.", 120, 90),
        ("Outputs are bridge-tied: NO series caps on the speakers, never join L- and R-.", 120, 92),
        ("HEADPHONES: TPA6138A2 (gain -1, ground-centred output, no output caps) drives the jack. TN contact = plug detect (HP_DET, reaches 3V3: Q1 is a MOSFET). Q1 pulls the speaker amp SD low when plugged. D13 reads HP_DET, D14 = headphone mute (pulled up).", 20, 118),
        ("MUTE: D0 -> R6 -> Q2 (2N7002) -> AMP_SD, pulled up by R15 so the speakers are muted until firmware drives D0 low. Q1 and Q2 drains are a wired-OR on AMP_SD.", 20, 120),
        ("BATTERY: BQ24074, EN2=1/EN1=0 -> 1.5A input limit (R19), 0.5A charge (R18), default timers, 10% termination, TS = 10k. VSYS = 4.4V on USB, else VBAT. ~CHG -> A5, ~PGOOD -> A11 (100k pull-ups). VBAT/2 -> A10.", 16, 144),
        ("BOOST: TPS61023 5.1V (750k/100k), 1uH, 10uF in, 2x22uF out + C1. EN from the panel switch on J16 (or JP2 bridged) via R28, R27 pull-down = off. Use a protected LiPo cell; J17 pin 1 = +.", 16, 146),
        ("EXPANSION: spare Seed GPIO/ADC + 3V3/5V/GND.  DISPLAY: SPI1 (A7 SCK, A3 MOSI, A8 NSS) + D26 D/C + D27 RST.  STEMMA QT: I2C1 (D11 SCL, D12 SDA) for seesaw encoders.", 78, 30),
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
        if re.match(r"^(H\d+|D\d+|K\d+|J(1|5|6|7|8|9|10|11|12|13|14|15|16|17))$", p.ref):
            fp.Reference().SetVisible(False)     # functional silkscreen labels are added separately
        if getattr(p, "dnp", False):
            try:
                fp.SetDNP(True)
            except AttributeError:
                pass
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
    def text(txt, x, y, size=2.0, layer=pcbnew.F_SilkS, angle=0):
        t = pcbnew.PCB_TEXT(board)
        t.SetText(txt)
        t.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
        t.SetTextSize(pcbnew.VECTOR2I(mm(size), mm(size)))
        t.SetTextThickness(mm(size * 0.15))
        t.SetLayer(layer)
        if angle:
            try:
                t.SetTextAngleDegrees(angle)
            except AttributeError:
                t.SetTextAngle(pcbnew.EDA_ANGLE(angle, pcbnew.DEGREES_T))
        board.Add(t)

    text("synthMachine carrier v0.4", 118, 53.0, 1.5)
    for name, kx_ in KEY_POS.items():
        text(name, kx_, KEY_LABEL_Y, 0.8)          # key name under its header, along the board edge
    for i, (ref, netname, label) in enumerate(POTS):
        text(label, POT_X + 4.7, POT_Y0 + i * POT_PITCH - 1.25, 0.8, angle=90)   # beside the header, reads bottom-up
    text("USB-C", 16, 9.8, 1.0)
    text("BAT 1=+", 100, 17.5, 0.8)
    text("PWR SW", 10.2, 38.75, 0.8, angle=90)
    text("CHG", 113, 17.0, 0.8)
    text("BOOST", 132.5, 36.0, 0.8)
    text("HP", 78, 21.0, 1.0)
    text("SPK L", 85, U3Y - 8.0, 0.9)
    text("SPK R", 85, U3Y + 8.0, 0.9)
    text("AMP", U3X, U3Y - 5.0, 0.9)
    text("GAIN", 70.5, 57.0, 0.8)
    text("HP AMP", 83, 25.0, 0.9)
    text("EXP", 93, 7.2, 0.9)
    text("DISP", 126, 7.2, 0.9)
    text("I2C ENC", 150.0, 24.0, 0.8)
    text("ESD", 17.5, 17.0, 0.8)

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
        pwr.SetClearance(mm(0.15)); pwr.SetTrackWidth(mm(0.6)); pwr.SetViaDiameter(mm(0.9)); pwr.SetViaDrill(mm(0.5))   # 0.15: the boost's SOT-563 pads are 0.2 apart
        ns.SetNetclass("Power", pwr)
        usb = pcbnew.NETCLASS("USB_Power")   # narrower so it can escape the USB-C's 0.5 mm pitch pads
        usb.SetClearance(mm(0.15)); usb.SetTrackWidth(mm(0.4)); usb.SetViaDiameter(mm(0.8)); usb.SetViaDrill(mm(0.4))
        ns.SetNetclass("USB_Power", usb)
        spk = pcbnew.NETCLASS("Speaker")     # amp pins -> ferrite beads: pad-limited, short
        spk.SetClearance(mm(0.15)); spk.SetTrackWidth(mm(0.3)); spk.SetViaDiameter(mm(0.8)); spk.SetViaDrill(mm(0.4))
        ns.SetNetclass("Speaker", spk)
        ns.SetNetclassPatternAssignment("SPK_*", "Speaker")
        # GND stays in the default class: the tracks only guarantee connectivity, the pours carry current
        # +3V3 / +3.3VA carry tens of mA at most and have to reach TSSOP pads: default class
        for pat in ("+5V", "+5V_SW", "SPKF_*"):
            ns.SetNetclassPatternAssignment(pat, "Power")
        for pat in ("VSYS", "VBAT", "VUSB", "BOOST_SW"):
            ns.SetNetclassPatternAssignment(pat, "USB_Power")   # 0.4 mm: the battery rails
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
