#!/usr/bin/env python3
"""Stand-in for Member 1's C sniffer, so the inference service can be tested alone.

  python3 tests/mock_sniffer.py --synthetic            # fake normal traffic
  python3 tests/mock_sniffer.py --synthetic --attack   # normal traffic plus a 0x500 flood (1 ms)
  python3 tests/mock_sniffer.py --csv data/normal_v2.csv --data-col data_hex   # replay a recording
"""
import argparse, csv, socket, struct, time

REC = struct.Struct("<dIB8s")
SOCK = "/tmp/can_sentinel_frames.sock"


def synthetic(attack):
    """Yield (offset_seconds, can_id, data) forever. IDs/periods follow the team contract."""
    # rates copied from the team's Normal_v2.csv (100/50/20/10/50 frames per second)
    periods = {0x100: 0.010, 0x200: 0.020, 0x300: 0.050, 0x400: 0.100, 0x500: 0.020}
    nxt = {i: 0.0 for i in periods}
    t, counter = 0.0, 0
    flood_next = 0.0
    while True:
        due = min(nxt, key=nxt.get)
        t = nxt[due]
        yield t, due, struct.pack(">HB5x", counter % 65535, counter % 256)
        nxt[due] += periods[due]
        counter += 1
        if attack and t > 5.0 and t >= flood_next:        # attack starts 5 s in
            flood_next = t + 0.001
            yield t, 0x500, b"\xff\xff\x00\x00\x00\x00\x00\x00"


def from_csv(path, ts_col, id_col, data_col):
    with open(path) as f:
        rows = list(csv.DictReader(f))
    t0 = float(rows[0][ts_col])
    for r in rows:
        data = bytes.fromhex(r[data_col]).ljust(8, b"\x00")[:8]
        cid = int(r[id_col], 0)
        yield float(r[ts_col]) - t0, cid, data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--attack", action="store_true")
    ap.add_argument("--csv")
    ap.add_argument("--ts-col", default="timestamp")
    ap.add_argument("--id-col", default="can_id")
    ap.add_argument("--data-col", default="data")
    a = ap.parse_args()
    src = synthetic(a.attack) if a.synthetic else from_csv(a.csv, a.ts_col, a.id_col, a.data_col)

    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(SOCK)
    start = time.time()
    for off, cid, data in src:
        delay = start + off - time.time()
        if delay > 0:
            time.sleep(delay)                       # replay at real-time pace
        s.sendall(REC.pack(start + off, cid, 8, data))  # timestamps shifted to "now"


if __name__ == "__main__":
    main()
