# Bring-up tools

## midimon

Prints every MIDI message the Mac receives, from every CoreMIDI source,
including sources that appear after it starts. Use it to check that the synth
enumerates over USB, that notes arrive, and that the note numbers are what the
firmware should be sending (octave shift, for instance).

```bash
make tools/midimon        # needs the Xcode command line tools (swiftc)
tools/midimon 120         # listen for two minutes (default 60 s)
```

Each line is a timestamp, the source name, the raw bytes, and a decode:

```
17:25:38.642 listening to [Daisy Seed Built In]
17:25:53.385 [Daisy Seed Built In] 90 3E 7F  note on  ch1 D4 (62) vel 127
17:25:53.605 [Daisy Seed Built In] 80 3E 00  note off ch1 D4 (62)
```

Remember the Seed does not bring USB up after a DFU flash until you press
RESET, and the prototype's USB-C needs a data cable, not a charge-only one.

## Key log (firmware side)

`make KEYLOG=1 program-dfu` builds a variant that prints every key event on the
Seed's micro-USB as a serial port instead of running MIDI. After the flash,
press RESET, then:

```bash
screen /dev/cu.usbmodem* 115200      # Ctrl-A then K to quit
```

Lines look like `KEY c4 r0  BTN6 down`: matrix column, row, the carrier
board's name for that node, and down or up. Octave and shift changes print too.
