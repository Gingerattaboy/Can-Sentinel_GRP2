#!/usr/bin/env bash
# packet_loss_audit.sh - run the packet-loss test twice, with the attacker idle and then active,
# and write the comparison table to docs/packet_loss_results.md.
#
# Usage (repo root, ECUs already running):
#   ./scripts/packet_loss_audit.sh [interface] [seconds] [tolerance_percent]
# Options through environment variables:
#   ATTACKER=./can_attacker  ATTACK_MODE=flood|insert  ATTACK_SECS=20  ATTACK_DELAY=10

set -euo pipefail
cd "$(dirname "$0")/.."

IFACE="${1:-vcan0}"
DURATION="${2:-60}"
TOLERANCE="${3:-2}"
ATTACKER="${ATTACKER:-./can_attacker}"
ATTACK_MODE="${ATTACK_MODE:-flood}"
ATTACK_SECS="${ATTACK_SECS:-20}"
ATTACK_DELAY="${ATTACK_DELAY:-10}"
OUT="docs/packet_loss_results.md"

if [ ! -x "$ATTACKER" ]; then
    echo "ERROR: attacker not found or not executable: $ATTACKER"; exit 1
fi
if [ $(( ATTACK_DELAY + ATTACK_SECS )) -ge "$DURATION" ]; then
    echo "ERROR: ATTACK_DELAY + ATTACK_SECS must be shorter than the test duration"; exit 1
fi
case "$ATTACK_MODE" in
    flood)  EXTRA="500:$(( 1000 * ATTACK_SECS ))" ;;   # 1 frame per ms on 0x500
    insert) EXTRA="100:$(( 200 * ATTACK_SECS ))" ;;    # 1 extra frame per 5 ms on 0x100
    *) echo "ERROR: ATTACK_MODE must be flood or insert"; exit 1 ;;
esac

idle="$(mktemp)"; active="$(mktemp)"
trap 'rm -f "$idle" "$active"' EXIT
status=0

echo "=== Phase 1: attacker idle ==="
./scripts/packet_loss_test.sh "$IFACE" "$DURATION" "$TOLERANCE" | tee "$idle" || status=1

echo; echo "=== Phase 2: attacker active ($ATTACK_MODE for ${ATTACK_SECS}s, starting ${ATTACK_DELAY}s in) ==="
( sleep "$ATTACK_DELAY"; "$ATTACKER" -m "$ATTACK_MODE" -d "$ATTACK_SECS" > /dev/null ) &
attacker_pid=$!
./scripts/packet_loss_test.sh "$IFACE" "$DURATION" "$TOLERANCE" "$EXTRA" | tee "$active" || status=1
wait "$attacker_pid" || true

rows() { grep -E '^0x' "$1"; }
mkdir -p docs
{
    echo "# Packet-loss audit"
    echo
    echo "Date: $(date '+%Y-%m-%d %H:%M')  |  Interface: $IFACE  |  Window: ${DURATION}s  |  Tolerance: ${TOLERANCE}%"
    echo "Kernel: $(uname -r)  |  Attacker: $ATTACK_MODE for ${ATTACK_SECS}s (expected extra frames: $EXTRA)"
    echo
    echo "| CAN ID | ECU | Expected (idle) | Received (idle) | Loss % (idle) | Expected (active) | Received (active) | Loss % (active) | Result idle / active |"
    echo "|--------|-----|-----------------|-----------------|---------------|-------------------|-------------------|-----------------|----------------------|"
    paste -d'|' <(rows "$idle") <(rows "$active") | awk -F'|' '{
        split($1, a, " "); split($2, b, " ");
        printf "| %s | %s | %s | %s | %s | %s | %s | %s | %s / %s |\n", a[1], a[2], a[3], a[4], a[6], b[3], b[4], b[6], a[7], b[7] }'
} > "$OUT"

echo; echo "Results table written to $OUT"
cat "$OUT"
exit "$status"
