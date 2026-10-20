# CAN-Sentinel Makefile (Member 3) - lives in c/
# Usage (from repo root):  make -C c all   |   make -C c clean
# Programs are built into c/build/
# No -std=c99/c11 on purpose: clock_nanosleep and M_PI need GNU/POSIX features.
CC      := gcc
CFLAGS  := -Wall -Wextra -O2 -I.
LDLIBS  := -lm

ECUS    := rpm_ecu speed_ecu steering_ecu temp_ecu brake_ecu
TOOLS   := can_attacker
BINS    := $(addprefix build/,$(ECUS) $(TOOLS))

all: $(BINS)

build:
	mkdir -p build

build/can_common.o: can_common.c can_common.h | build
	$(CC) $(CFLAGS) -c $< -o $@

build/%: %.c build/can_common.o | build
	$(CC) $(CFLAGS) $< build/can_common.o -o $@ $(LDLIBS)

clean:
	rm -rf build

.PHONY: all clean
