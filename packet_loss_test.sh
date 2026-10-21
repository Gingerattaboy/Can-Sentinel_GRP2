#!/usr/bin/env bash
# packet_loss_test.sh - record vcan0 traffic for a fixed time and compare the
# number of frames received per CAN ID with the number expected from the
# contract (docs/contract.md).
#
# Usage:   ./scripts/packet_loss_test.sh [interface] [seconds] [tolerance_percent]
# Example: ./scripts/packet_loss_test.sh vcan0 60 2
#
# Start the ECUs first (e.g. ./scripts/run_all_ecus.sh), then run this script.
# Exit code: 0 if every ID is within tolerance, 1 otherwise.

set -euo pipefail

IFACE="${1:-vcan0}"
DURATION="${2:-60}"
TOLERANCE="${3:-2}"     # allowed shortfall in percent

# Expected send period per CAN ID in ms (from the contract, sections 2 and 12).
# Keys are the hex IDs as candump prints them for standard frames.
# NOTE: 0x500 (Brake) added per contract section 12 - "All five ECUs run
# together from now on." Without this, every run (including an idle one)
# falsely reported 0x500 as an "unexpected CAN ID".
declare -A PERIOD_MS=( [100]=10 [200]=20 [300]=50 [400]=100 [500]=20 )
declare -A NAME=( [100]=RPM [200]=Speed [300]=Steering [400]=Temperature [500]=Brake )

# --- sanity checks ---------------------------------------------------------
if ! command -v candump > /dev/null 2>&1; then
    echo "ERROR: candump not found. Install it: sudo apt install -y can-utils"
    exit 1
fi
if ! ip link show "$IFACE" > /dev/null 2>&1; then
    echo "ERROR: interface $IFACE does not exist. Run ./scripts/setup_vcan.sh first."
    exit 1
fi

LOGFILE="$(mktemp /tmp/can_loss_XXXXXX)"
trap 'rm -f "$LOGFILE"' EXIT

# --- record ----------------------------------------------------------------
echo "Recording $IFACE for ${DURATION}s (make sure the ECUs are running)..."
# timeout sends SIGINT after DURATION seconds; candump exits cleanly and
# flushes its output. timeout returns 124 in that case, which is expected.
timeout --signal=INT "$DURATION" candump -L "$IFACE" > "$LOGFILE" || true

TOTAL=$(wc -l < "$LOGFILE")
if [ "$TOTAL" -eq 0 ]; then
    echo "ERROR: no frames received. Are the ECUs running on $IFACE?"
    exit 1
fi

# --- count frames per CAN ID ----------------------------------------------
# candump -L line format: (timestamp) vcan0 100#0BB8010000000000
declare -A COUNTS
while read -r count id; do
    COUNTS[$id]=$count
done < <(awk '{split($3, a, "#"); print a[1]}' "$LOGFILE" | sort | uniq -c)

# --- compare with expectation ---------------------------------------------
echo
printf "%-6s %-12s %9s %9s %9s %8s  %s\n" "ID" "ECU" "Expected" "Received" "Lost" "Loss %" "Result"
printf "%-6s %-12s %9s %9s %9s %8s  %s\n" "------" "------------" "---------" "---------" "---------" "--------" "------"

STATUS=0
for id in 100 200 300 400 500; do
    expected=$(( DURATION * 1000 / PERIOD_MS[$id] ))
    received="${COUNTS[$id]:-0}"
    lost=$(( expected - received ))
    loss_pct=$(awk -v e="$expected" -v r="$received" 'BEGIN { printf "%.2f", (e - r) * 100 / e }')

    if awk -v l="$loss_pct" -v t="$TOLERANCE" 'BEGIN { exit !(l <= t) }'; then
        result="PASS"
    else
        result="FAIL"
        STATUS=1
    fi

    printf "0x%-4s %-12s %9d %9d %9d %7s%%  %s\n" \
        "$id" "${NAME[$id]}" "$expected" "$received" "$lost" "$loss_pct" "$result"
done

# Warn about any ID that is not in the contract.
for id in "${!COUNTS[@]}"; do
    if [ -z "${PERIOD_MS[$id]:-}" ]; then
        echo "WARNING: unexpected CAN ID 0x$id seen ${COUNTS[$id]} times"
    fi
done

echo
echo "Total frames recorded: $TOTAL   Tolerance: ${TOLERANCE}%"
echo "Note: a negative 'Lost' value (a few extra frames) is normal at the window edges."
if [ "$STATUS" -eq 0 ]; then
    echo "OVERALL: PASS"
else
    echo "OVERALL: FAIL (an ID is below its expected rate; check the owner's ECU timing)"
fi
exit "$STATUS"
