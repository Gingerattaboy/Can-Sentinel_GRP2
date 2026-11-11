#!/usr/bin/env bash
# scripts/demo_defense.sh - CAN-Sentinel Week 4 (Member 2)
# Runs the SAME flood attack twice on vcan0: A) without the defence, B) with it.
# The defence is a SIMULATION at application level (victim_ecu rate limiter),
# not a real CAN error-frame defence.
#
# Run from anywhere:  scripts/demo_defense.sh
# Options (environment variables):
#   BIN=c/build        folder with the compiled C programs
#   ATTACK_SECONDS=15  length of each attack
#   TAG_BYTE=7         data byte that carries the 0xA5 tag (must match the attacker)
set -u
cd "$(dirname "$0")/.." || exit 1

BIN="${BIN:-c/build}"
ATTACK_SECONDS="${ATTACK_SECONDS:-15}"
TAG_BYTE="${TAG_BYTE:-7}"
OUT="data/defense_demo"
ECUS="rpm_ecu speed_ecu steering_ecu temp_ecu brake_ecu"
PIDS=""

die() { echo "ERROR: $*" >&2; exit 1; }

cleanup() {
    for p in $PIDS; do kill "$p" 2>/dev/null; done
    sleep 0.5
    rm -f /tmp/can_sentinel_frames.sock /tmp/can_sentinel_events.sock
    PIDS=""
}
trap cleanup EXIT
trap 'echo; echo "stopped"; exit 130' INT TERM

start() { "$@" >/dev/null 2>&1 & PIDS="$PIDS $!"; }

# ---- checks, so nothing starts half-way ----
ip link show vcan0 >/dev/null 2>&1 || die "vcan0 not found. Create it first (scripts/setup_vcan.sh)."
for b in $ECUS victim_ecu can_attacker sniffer; do
    [ -x "$BIN/$b" ] || die "missing $BIN/$b - build it first"
done
[ -f inference_service.py ] || [ -f python/inference_service.py ] || die "inference_service.py not found"
[ -f python/defender.py ] || [ -f defender.py ] || die "defender.py not found"
[ -f models/iforest.joblib ] || die "models/iforest.joblib not found"
mkdir -p "$OUT" data

SERVICE=inference_service.py;  [ -f "$SERVICE" ] || SERVICE=python/inference_service.py
DEFENDER=python/defender.py;   [ -f "$DEFENDER" ] || DEFENDER=defender.py

rm -f "$OUT"/*.csv

start_ecus() { for e in $ECUS; do start "$BIN/$e"; done; sleep 3; }

summary() {  # $1 = label, $2 = victim csv
    awk -F, -v label="$1" 'NR>1 { acc+=$3; drop+=$4; sp+=$5; ld+=$6; q+=$2 }
        END { printf "%-12s attacker_frames_accepted=%d  legit_frames_dropped=%d  all_dropped=%d  quarantine_seconds=%d\n",
                     label, sp, ld, drop, q }' "$2"
}

echo "=== Run A: attack WITHOUT the defence (${ATTACK_SECONDS}s) ==="
start "$BIN/victim_ecu" -o "$OUT/victim_nodefence.csv" -b "$TAG_BYTE"
start_ecus
"$BIN/can_attacker" -m flood -i vcan0 -d "$ATTACK_SECONDS" -l "$OUT/attack_log_nodefence.csv" 2>&1 | tail -1
sleep 2
cleanup

echo
echo "=== Run B: attack WITH the simulated defence (${ATTACK_SECONDS}s) ==="
start python3 "$SERVICE"
sleep 2
start "$BIN/sniffer"
start "$BIN/victim_ecu" -o "$OUT/victim_defence.csv" -b "$TAG_BYTE"
start_ecus
start python3 "$DEFENDER" --log "$OUT/defense_log.csv"
sleep 3
"$BIN/can_attacker" -m flood -i vcan0 -d "$ATTACK_SECONDS" -l "$OUT/attack_log_defence.csv" 2>&1 | tail -1
echo "attack finished; waiting for the defender to release the quarantine..."
sleep 6
cleanup

echo
echo "=== Results (one-second resolution) ==="
summary "no defence" "$OUT/victim_nodefence.csv"
summary "with defence" "$OUT/victim_defence.csv"

python3 - "$OUT" <<'PY'
import csv, sys
out = sys.argv[1]
try:
    start = float(list(csv.DictReader(open(f"{out}/attack_log_defence.csv")))[-1]["start_ts"])
    rows = [r for r in csv.DictReader(open(f"{out}/defense_log.csv")) if r["action"] == "ON"]
    if rows:
        print(f"first quarantine ON: {float(rows[0]['event_time']) - start:.2f} s after the attack started "
              "(window_start of the verdict that triggered it, so approximate)")
    else:
        print("the defender never sent quarantine ON (check that verdicts carry suspect_id)")
except Exception as e:
    print("could not compute quarantine delay:", e)
PY
echo
echo "Files are in $OUT/. Remember: the defence is simulated at application level on vcan0."
