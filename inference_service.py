#!/usr/bin/env python3
"""CAN-Sentinel Week 3 - Member 2: live inference service.

Frames in  : Unix socket /tmp/can_sentinel_frames.sock  (we are the SERVER)
             21-byte records, little-endian: float64 ts, uint32 can_id, uint8 dlc, 8 data bytes
Events out : Unix socket /tmp/can_sentinel_events.sock  (we are the SERVER)
             newline-delimited JSON: {"type":"frames",...} every 100 ms, {"type":"verdict",...} per window
"""
import csv, json, os, socket, struct, threading, time
from collections import deque, Counter
from pathlib import Path

import sys
import joblib
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent / "python"))   # features.py lives in python/
import features  # Member 3's Week 2 module. Import it, never copy it.

# ---------------- contract values (docs/contract.md, Week 3 Step 0) ----------------
FRAME_SOCK = "/tmp/can_sentinel_frames.sock"
EVENT_SOCK = "/tmp/can_sentinel_events.sock"
REC = struct.Struct("<dIB8s")            # 21 bytes, no padding
assert REC.size == 21
WINDOW_S, STEP_S = 0.200, 0.100
GRACE_S = 0.020                           # wait a little for late frames before closing a window
MODEL_PATH = Path("models/iforest.joblib")
SCALE_PATH = Path("models/iforest_scale.json")
LATENCY_LOG = Path("logs/inference_latency.csv")

# ---------------- shared state ----------------
lock = threading.Lock()
frames = deque()          # (ts, can_id, dlc, data_bytes) - ring buffer, pruned by time
pending = []              # frames not yet sent in a "frames" event
received = [0]            # total frames ever received (a list so threads can update it)
event_clients = []        # connected dashboards


def make_server(path):
    if os.path.exists(path):
        os.unlink(path)       # stale socket file after a crash would block bind()
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(path)
    srv.listen(4)
    return srv


# ---------------- task 1: receive frames ----------------
def handle_sniffer(conn):
    buf = b""
    try:
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                break                                   # sniffer disconnected; it will reconnect
            buf += chunk
            n = len(buf) // REC.size                     # stream: records can be split
            for i in range(n):
                ts, cid, dlc, data = REC.unpack_from(buf, i * REC.size)
                with lock:
                    frames.append((ts, cid, dlc, data))
                    pending.append((ts, cid, dlc, data))
                    received[0] += 1
            buf = buf[n * REC.size:]
    finally:
        conn.close()


def frame_server():
    srv = make_server(FRAME_SOCK)
    while True:
        conn, _ = srv.accept()
        threading.Thread(target=handle_sniffer, args=(conn,), daemon=True).start()


# ---------------- task 4: publish events ----------------
def event_server():
    srv = make_server(EVENT_SOCK)
    while True:
        conn, _ = srv.accept()
        with lock:
            event_clients.append(conn)


def publish(obj):
    line = (json.dumps(obj) + "\n").encode()
    with lock:
        clients = list(event_clients)
    for c in clients:
        try:
            c.sendall(line)
        except OSError:
            with lock:
                if c in event_clients:
                    event_clients.remove(c)
            c.close()


# ---------------- tasks 2 and 3: features, model, threat level ----------------
def window_features(rows):
    """Features for ONE live window, computed by Member 3's features.compute_features.

    features.compute_features() drops the last, incomplete window, so handing it a single
    window returns nothing. We add one sentinel frame a full window after the first frame; it
    lands in the dropped window and does not change any number in the real one.
    An empty window gives ten zeros, which is what features.py itself does for empty windows.
    """
    if not rows:
        return pd.DataFrame([[0] * len(features.FEATURE_COLUMNS)], columns=features.FEATURE_COLUMNS)
    df = pd.DataFrame([(ts, cid, data[:dlc]) for ts, cid, dlc, data in rows],
                      columns=["timestamp", "can_id", "payload"])
    first = float(df["timestamp"].iloc[0])
    sentinel = pd.DataFrame([(first + WINDOW_S, 0, b"")], columns=df.columns)
    out = features.compute_features(pd.concat([df, sentinel], ignore_index=True))
    return out.loc[[0], features.FEATURE_COLUMNS]


def load_model():
    bundle = joblib.load(MODEL_PATH)                     # a dict saved by the training script
    assert bundle["window_ms"] == int(WINDOW_S * 1000), f"model is for {bundle['window_ms']} ms windows"
    assert list(bundle["feature_columns"]) == list(features.FEATURE_COLUMNS), "feature order differs from features.py"
    model = bundle["pipeline"]                           # StandardScaler -> IsolationForest
    scale = json.loads(SCALE_PATH.read_text())           # expects {"min": ..., "max": ...}
    return model, float(scale["min"]), float(scale["max"])


def threat_level(anomaly_score, lo, hi):
    """0-100, scaled with the min/max score seen on NORMAL data. Higher = more anomalous."""
    if hi <= lo:
        return 0
    return int(round(100 * min(max((anomaly_score - lo) / (hi - lo), 0.0), 1.0)))


def main():
    model, lo, hi = load_model()
    LATENCY_LOG.parent.mkdir(exist_ok=True)
    new_log = not LATENCY_LOG.exists()
    log = open(LATENCY_LOG, "a", newline="")
    w = csv.writer(log)
    if new_log:
        w.writerow(["window_end", "n_frames", "inference_ms", "verdict_delay_ms"])

    threading.Thread(target=frame_server, daemon=True).start()
    threading.Thread(target=event_server, daemon=True).start()
    print("inference service up; waiting for sniffer and dashboard", flush=True)

    next_end = (int(time.time() / STEP_S) + 1) * STEP_S  # align windows to 100 ms ticks
    last_frames_event = time.time()

    while True:
        now = time.time()

        # frames event every 100 ms
        if now - last_frames_event >= STEP_S:
            with lock:
                batch, pending[:] = list(pending), []
            if batch:
                items = [[ts, cid, dlc, data.hex()] for ts, cid, dlc, data in batch]
                publish({"type": "frames", "items": items})
            last_frames_event = now

        # close every window whose end (plus grace) has passed
        while now >= next_end + GRACE_S:
            start = next_end - WINDOW_S
            with lock:
                while frames and frames[0][0] < start:
                    frames.popleft()                      # prune the ring buffer
                rows = [f for f in frames if start <= f[0] < next_end]
            if received[0] > 0:                               # start scoring once traffic has begun
                t0 = time.perf_counter()
                x = window_features(rows)
                if not hasattr(model, "feature_names_in_"):
                    x = x.to_numpy()                          # model was trained without column names
                raw = float(model.score_samples(x)[0])        # one model call per window
                anomaly = -raw                                # higher = more anomalous
                is_anom = bool(raw < model.steps[-1][1].offset_)    # same rule predict() uses (-1 = anomaly)
                infer_ms = (time.perf_counter() - t0) * 1000
                counts = dict(Counter(f"0x{f[1]:X}" for f in rows))
                lvl = threat_level(anomaly, lo, hi)
                publish({"type": "verdict", "window_start": start, "score": anomaly,
                         "threat_level": lvl, "is_anomaly": is_anom, "counts": counts})
                w.writerow([f"{next_end:.3f}", len(rows), f"{infer_ms:.2f}",
                            f"{(time.time() - next_end) * 1000:.2f}"])
                log.flush()
            next_end += STEP_S
        time.sleep(0.01)


if __name__ == "__main__":
    main()
