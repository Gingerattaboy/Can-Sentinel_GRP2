#!/usr/bin/env bash
#
# run_attack_scenarios.sh — CAN-Sentinel Week 2
# Owner: Member 1 (Data Capture, Labelling and Audit)
# Usage:
#   ./run_attack_scenarios.sh
#
set -uo pipefail

# ---------------------------- CONFIG ---------------------------------
IFACE="vcan0"
ECU_SCRIPT="./run_all_ecus.sh"          # Week 1: starts all ECUs incl. Brake
LOGGER_CMD="python3 logger.py --interface ${IFACE}"   # ADJUST to your real logger.py CLI/output flag
ATTACKER_BIN="./can_attacker"           # from can_attacker.c
OUT_DIR="data"
ATTACK_LOG="${OUT_DIR}/attack_log.csv"
WARMUP_S=2        # let ECUs settle before logger starts
SETTLE_S=1        # let logger settle before attacker starts

FLOOD_DURATIONS=(10 20 30)   # 3 flood runs, different durations
INSERT_DURATIONS=(10 20 30)  # 3 insertion runs, different durations
# -----------------------------------------------------------------------

mkdir -p "${OUT_DIR}"
if [ ! -f "${ATTACK_LOG}" ]; then
    echo "start_ts,end_ts,mode,target_id" > "${ATTACK_LOG}"
fi

run_one() {
    local mode="$1"
    local duration="$2"
    local run_num="$3"
    local out_csv="${OUT_DIR}/attack_${mode}_${run_num}.csv"

    echo "=== ${mode} run ${run_num}: duration=${duration}s -> ${out_csv} ==="

    # 1. Bring up all ECUs (includes the real Brake ECU) in the background
    ${ECU_SCRIPT} &
    local ecu_pgid=$!
    sleep "${WARMUP_S}"

    # 2. Start the logger recording to this run's CSV
    ${LOGGER_CMD} --output "${out_csv}" &
    local logger_pid=$!
    sleep "${SETTLE_S}"

    # 3. Run the attacker and capture its summary (has start_ts/end_ts)
    local attacker_out
    attacker_out=$(${ATTACKER_BIN} -i "${IFACE}" -m "${mode}" -d "${duration}" 2>&1)
    local attacker_rc=$?
    echo "${attacker_out}"

    if [ ${attacker_rc} -ne 0 ]; then
        echo "!! ${mode} run ${run_num} FAILED (attacker exit ${attacker_rc}) — "
        echo "   likely because --mode insert isn't implemented yet (Task 3)."
        kill "${logger_pid}" 2>/dev/null
        kill -- "-${ecu_pgid}" 2>/dev/null
        rm -f "${out_csv}"
        return 1
    fi

    # 4. Let the logger capture a trailing moment of traffic, then stop everything
    sleep 1
    kill "${logger_pid}" 2>/dev/null
    wait "${logger_pid}" 2>/dev/null
    kill -- "-${ecu_pgid}" 2>/dev/null
    wait "${ecu_pgid}" 2>/dev/null

    # 5. Pull start_ts/end_ts/target_id out of the attacker's summary and log them
    local start_ts end_ts target_id
    start_ts=$(echo "${attacker_out}" | grep '^start_ts' | awk '{print $3}')
    end_ts=$(echo "${attacker_out}" | grep '^end_ts' | awk '{print $3}')
    target_id=$(echo "${attacker_out}" | grep '^target_id' | awk '{print $3}')
    echo "${start_ts},${end_ts},${mode},${target_id}" >> "${ATTACK_LOG}"

    if [ ! -s "${out_csv}" ]; then
        echo "!! WARNING: ${out_csv} is empty or missing — check logger.py's --output flag"
    else
        echo ">> saved $(wc -l < "${out_csv}") lines to ${out_csv}"
    fi
    echo
}

echo "### Flood runs (3) ###"
n=1
for d in "${FLOOD_DURATIONS[@]}"; do
    run_one "flood" "${d}" "${n}"
    n=$((n + 1))
done

echo "### Insertion runs (3) — will fail until Task 3 (insert mode) is done ###"
n=1
for d in "${INSERT_DURATIONS[@]}"; do
    run_one "insert" "${d}" "${n}"
    n=$((n + 1))
done

echo "### Summary ###"
ls -la "${OUT_DIR}"/attack_*.csv 2>/dev/null
echo "attack_log.csv:"
cat "${ATTACK_LOG}"
