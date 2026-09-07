# Project Name
TARGET = synthMachine

# Sources
CPP_SOURCES = synthMachine.cpp

# Hardware profile. `make` builds for the breadboard prototype (WIRING.md);
# `make HW=carrier` builds for the carrier board (hardware/). The carrier build
# lands in build-carrier/ so the two never share stale objects, and
# `make HW=carrier program-dfu` flashes it.
HW ?= prototype
ifeq ($(HW),carrier)
C_DEFS += -DSYNTH_HW_CARRIER
override BUILD_DIR = build-carrier
else ifeq ($(HW),prototype)
C_DEFS += -DSYNTH_HW_PROTOTYPE
else
$(error Unknown HW=$(HW); use HW=prototype (default) or HW=carrier)
endif

# Library Locations
LIBDAISY_DIR = ../DaisyExamples/libDaisy/
DAISYSP_DIR = ../DaisyExamples/DaisySP/

# Core location, and generic Makefile.
SYSTEM_FILES_DIR = $(LIBDAISY_DIR)/core
include $(SYSTEM_FILES_DIR)/Makefile
