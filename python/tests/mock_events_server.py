#!/usr/bin/env python3
"""Mock events server: stands in for the inference service (Week 3, Member 3).

Usage:
  python tests/mock_events_server.py                 # synthetic traffic, attack after 10 s
  python tests/mock_events_server.py --attack-after 5 --attack-for 8
  python tests/mock_events_server.py --replay events.jsonl   # replay recorded events

Sends newline-delimited JSON on /tmp/can_sentinel_events.sock:
  {"type": "frames",  "items": [[ts, id, dlc, data_hex], ...]}     every 100 ms
  {"type": "verdict", "window_start", "score", "threat_level",
                      "is_anomaly", "counts"}                      every 100 ms
"""
import argparse
import json
import os
import random
import socket
import time

SOCK = "/tmp/can_sentinel_events.sock"
NORMAL_IDS = [0x0C0, 0x1A0, 0x244, 0x316, 0x3E8]
ATTACK_ID = 0x666


def make_frame(ts, can_id):
    data = bytes(random.randrange(256) for _ in range(8)).hex()
    return [ts, can_id, 8, data]


def synthetic(conn, attack_after, attack_for):
    start = time.time()
    step = 0
    while True:
        now = time.time()
        elapsed = now - start
        attacking = attack_after <= elapsed < attack_after + attack_for

        items = []
        counts = {}
        for i in range(20):
            cid = random.choice(NORMAL_IDS)
            items.append(make_frame(now - 0.1 + i * 0.005, cid))
            counts[hex(cid)] = counts.get(hex(cid), 0) + 1
        if attacking:
            for i in range(40):
                items.append(make_frame(now - 0.1 + i * 0.0025, ATTACK_ID))
            counts[hex(ATTACK_ID)] = 40
        items.sort(key=lambda r: r[0])

        if attacking:
            level = min(100, 70 + int((elapsed - attack_after) * 10) + random.randint(0, 5))
        else:
            level = random.randint(2, 18)
        verdict = {"type": "verdict", "window_start": now - 0.2,
                   "score": -0.35 - level / 200.0, "threat_level": level,
                   "is_anomaly": level >= 70, "counts": counts}

        conn.sendall((json.dumps({"type": "frames", "items": items}) + "\n").encode())
        conn.sendall((json.dumps(verdict) + "\n").encode())
        step += 1
        time.sleep(0.1)


def replay(conn, path):
    with open(path) as f:
        for line in f:
            if line.strip():
                conn.sendall(line.encode() if line.endswith("\n") else (line + "\n").encode())
                time.sleep(0.1 / 2)  # frames + verdict pair per 100 ms


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default=SOCK)
    ap.add_argument("--attack-after", type=float, default=10.0)
    ap.add_argument("--attack-for", type=float, default=10.0)
    ap.add_argument("--replay")
    args = ap.parse_args()

    if os.path.exists(args.path):   # clear stale socket file
        os.unlink(args.path)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(args.path)
    srv.listen(1)
    print(f"mock events server listening on {args.path}")
    try:
        while True:
            conn, _ = srv.accept()
            print("dashboard connected")
            try:
                if args.replay:
                    replay(conn, args.replay)
                else:
                    synthetic(conn, args.attack_after, args.attack_for)
            except (BrokenPipeError, ConnectionResetError):
                print("dashboard disconnected")
            finally:
                conn.close()
    except KeyboardInterrupt:
        pass
    finally:
        srv.close()
        if os.path.exists(args.path):
            os.unlink(args.path)


if __name__ == "__main__":
    main()
