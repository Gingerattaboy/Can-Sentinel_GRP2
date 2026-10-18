#!/usr/bin/env bash
# Build and start all four ECUs together. Press Ctrl+C to stop them all.
set -euo pipefail
cd "$(dirname "$0")/.."

if ! ip link show vcan0 >/dev/null 2>&1; then
    echo "vcan0 not found. Run: sudo ./scripts/setup_vcan.sh" >&2
    exit 1
fi

# Makefile lives in c/ and builds the programs into c/build/
make -C c all

PIDS=()
cleanup() {
    trap - INT TERM EXIT
    echo; echo "Stopping ECUs..."
    for pid in "${PIDS[@]}"; do kill "$pid" 2>/dev/null || true; done
    wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

for ecu in rpm_ecu speed_ecu steering_ecu temp_ecu; do
    ./c/build/"$ecu" &
    PIDS+=($!)
done

echo "All ECUs running (PIDs: ${PIDS[*]}). Check with: candump vcan0"
wait
