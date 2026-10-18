# CAN-Sentinel Makefile (Member 3)
# Builds every ECU from c/ into build/.   Usage:  make | make clean
CC      := gcc
CFLAGS  := -Wall -Wextra -O2 -std=gnu11 -Ic
LDLIBS  := -lm

ECUS    := rpm_ecu speed_ecu steering_ecu temp_ecu
BINS    := $(addprefix build/,$(ECUS))

all: $(BINS)

build:
	mkdir -p build

build/can_common.o: c/can_common.c c/can_common.h | build
	$(CC) $(CFLAGS) -c $< -o $@

build/%: c/%.c build/can_common.o | build
	$(CC) $(CFLAGS) $< build/can_common.o -o $@ $(LDLIBS)

clean:
	rm -rf build

.PHONY: all clean
