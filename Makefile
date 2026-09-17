# Project Name
TARGET = synthMachine

# Sources
CPP_SOURCES = synthMachine.cpp

# Build variants. Each combination gets its own build directory so they never
# share stale objects, and `make <flags> program-dfu` flashes that variant.
#
#   HW=prototype   (default) breadboard prototype, see WIRING.md
#   HW=carrier     carrier board v0.3, see hardware/v0.3/
#   HW=carrier4    carrier board v0.4, see hardware/v0.4/
#   KEYLOG=1       diagnostic build: prints key events on the Seed's micro-USB
#                  serial port instead of running MIDI, to find button nodes
#   MIDI_USB=seed  USB MIDI on the Seed's own USB port instead of the board's
#                  USB-C (D29/D30), for a carrier without its USB-C fitted
#   POTS=none      ignore the pots and keep the built-in defaults, for a board
#                  whose pots aren't wired yet (unconnected ADC inputs float)
#   HP_DET=adc     carrier only: read the headphone plug detect through the
#                  ADC on A5, with a wire from EXP pin 8 to EXP pin 4. Needed
#                  on the v0.3 carrier, where HP_DET never reaches a digital
#                  high (see hardware/NEXT_REVISION.md)
#
# After any program-dfu, press RESET on the Seed: it does not bring USB up
# after the DFU handoff, so MIDI or the serial log only appear after a reset.
HW ?= prototype
KEYLOG ?= 0
MIDI_USB ?= board
POTS ?= wired
HP_DET ?= pin
ifeq ($(HW),carrier)
C_DEFS += -DSYNTH_HW_CARRIER
BUILD_SUFFIX = -carrier
else ifeq ($(HW),carrier4)
C_DEFS += -DSYNTH_HW_CARRIER -DSYNTH_HW_CARRIER_V4
BUILD_SUFFIX = -carrier4
else ifeq ($(HW),prototype)
C_DEFS += -DSYNTH_HW_PROTOTYPE
BUILD_SUFFIX =
else
$(error Unknown HW=$(HW); use HW=prototype (default), HW=carrier or HW=carrier4)
endif
ifeq ($(MIDI_USB),seed)
C_DEFS += -DSYNTH_MIDI_USB_SEED
BUILD_SUFFIX := $(BUILD_SUFFIX)-seedusb
else ifneq ($(MIDI_USB),board)
$(error Unknown MIDI_USB=$(MIDI_USB); use MIDI_USB=board (default) or MIDI_USB=seed)
endif
ifeq ($(POTS),none)
C_DEFS += -DSYNTH_NO_POTS
BUILD_SUFFIX := $(BUILD_SUFFIX)-nopots
else ifneq ($(POTS),wired)
$(error Unknown POTS=$(POTS); use POTS=wired (default) or POTS=none)
endif
ifeq ($(HP_DET),adc)
C_DEFS += -DSYNTH_HP_DET_ADC
BUILD_SUFFIX := $(BUILD_SUFFIX)-hpadc
else ifneq ($(HP_DET),pin)
$(error Unknown HP_DET=$(HP_DET); use HP_DET=pin (default) or HP_DET=adc)
endif
ifeq ($(KEYLOG),1)
C_DEFS += -DSYNTH_KEY_LOG=1
BUILD_SUFFIX := $(BUILD_SUFFIX)-keylog
endif
ifneq ($(BUILD_SUFFIX),)
override BUILD_DIR = build$(BUILD_SUFFIX)
endif

# Library Locations
LIBDAISY_DIR = ../DaisyExamples/libDaisy/
DAISYSP_DIR = ../DaisyExamples/DaisySP/
# ReverbSc lives in the LGPL half of DaisySP (DaisySP-LGPL/, built alongside it)
USE_DAISYSP_LGPL = 1

# Core location, and generic Makefile.
SYSTEM_FILES_DIR = $(LIBDAISY_DIR)/core
include $(SYSTEM_FILES_DIR)/Makefile

# Host-side bring-up tool (see tools/README.md)
tools/midimon: tools/midimon.swift
	swiftc -O -o $@ $<
