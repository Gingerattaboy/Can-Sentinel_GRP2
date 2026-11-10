#!/usr/bin/env python3
"""Stand-in inference service for testing sniffer.c 

Listens on the frames socket, parses 21-byte records (<dIB8s) and prints
frames/s plus transport latency (receive time - sniffer kernel timestamp).

  --slow-ms N       sleep N ms per read burst (simulate a slow detector -> sniffer drops)
  --close-after S   close each connection after S seconds (tests sniffer reconnect)
"""
import argparse, os, socket, struct, time, statistics

REC = struct.Struct("<dIB8s")
assert REC.size == 21


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default="/tmp/can_sentinel_frames.sock")
    ap.add_argument("--slow-ms", type=float, default=0)
    ap.add_argument("--close-after", type=float, default=0)
    a = ap.parse_args()

    if os.path.exists(a.path):
        os.unlink(a.path)                      # stale socket file
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(a.path)
    srv.listen(1)
    print(f"mock server listening on {a.path}")
    try:
        while True:
            conn, _ = srv.accept()
            print("sniffer connected")
            serve(conn, a)
            print("connection closed")
    except KeyboardInterrupt:
        pass
    finally:
        srv.close()
        if os.path.exists(a.path):
            os.unlink(a.path)


def serve(conn, a):
    buf = b""
    lat, n_sec, total = [], 0, 0
    cid = dlc = 0
    payload = b""
    t0 = tick = time.time()
    while True:
        data = conn.recv(65536)
        if not data:
            return
        now = time.time()
        buf += data
        usable = len(buf) - len(buf) % REC.size
        for off in range(0, usable, REC.size):
            ts, cid, dlc, payload = REC.unpack_from(buf, off)
            lat.append((now - ts) * 1000.0)
            n_sec += 1
            total += 1
        buf = buf[usable:]
        if now - tick >= 1.0:
            med = statistics.median(lat) if lat else float("nan")
            p99 = sorted(lat)[int(len(lat) * 0.99) - 1] if len(lat) > 100 else float("nan")
            print(f"recv/s={n_sec:5d} total={total} transport median={med:.3f} ms p99={p99:.3f} ms "
                  f"(last id=0x{cid:X} dlc={dlc} data={payload.hex()})")
            lat, n_sec, tick = [], 0, now
        if a.close_after and now - t0 >= a.close_after:
            conn.close()
            return
        if a.slow_ms:
            time.sleep(a.slow_ms / 1000.0)


if __name__ == "__main__":
    main()
