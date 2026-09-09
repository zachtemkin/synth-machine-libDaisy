# Project Name
TARGET = synthMachine

# Sources
CPP_SOURCES = synthMachine.cpp

# Build variants. Each combination gets its own build directory so they never
# share stale objects, and `make <flags> program-dfu` flashes that variant.
#
#   HW=prototype   (default) breadboard prototype, see WIRING.md
#   HW=carrier     carrier board, see hardware/
#   KEYLOG=1       diagnostic build: prints key events on the Seed's micro-USB
#                  serial port instead of running MIDI, to find button nodes
#
# After any program-dfu, press RESET on the Seed: it does not bring USB up
# after the DFU handoff, so MIDI or the serial log only appear after a reset.
HW ?= prototype
KEYLOG ?= 0
ifeq ($(HW),carrier)
C_DEFS += -DSYNTH_HW_CARRIER
BUILD_SUFFIX = -carrier
else ifeq ($(HW),prototype)
C_DEFS += -DSYNTH_HW_PROTOTYPE
BUILD_SUFFIX =
else
$(error Unknown HW=$(HW); use HW=prototype (default) or HW=carrier)
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
