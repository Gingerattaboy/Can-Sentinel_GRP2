"""Mock events server: stands in for the inference service (Week 3).

Serves newline-delimited JSON on /tmp/can_sentinel_events.sock:
  - {"type":"frames", ...} every 100 ms
  - {"type":"verdict", ...} every 100 ms
Cycles 15 s normal traffic, then 8 s of simulated attack (flood of 0x7FF).
Assumption: verdict "counts" is {"0x123": n_frames_in_window}.

Run:  python3 python/mock_events_server.py
"""
import json
import os
import random
import socket
import time

SOCK = "/tmp/can_sentinel_events.sock"
NORMAL_IDS = [0x100, 0x200, 0x300, 0x400]
ATTACK_ID = 0x7FF
NORMAL_S, ATTACK_S = 15, 8


def main():
    if os.path.exists(SOCK):
        os.unlink(SOCK)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCK)
    srv.listen(4)
    srv.setblocking(False)
    clients = []
    t0 = time.time()
    print("mock events server on", SOCK, "(Ctrl+C to stop)")
    try:
        while True:
            tick = time.time()
            try:
                c, _ = srv.accept()
                clients.append(c)
                print("client connected")
            except BlockingIOError:
                pass

            phase = (tick - t0) % (NORMAL_S + ATTACK_S)
            attack = phase >= NORMAL_S

            items, counts = [], {}
            for cid in NORMAL_IDS:
                for k in range(10):
                    ts = tick - 0.1 + k * 0.01
                    data = bytes(random.randrange(256) for _ in range(8))
                    items.append([ts, cid, 8, data.hex()])
                    counts[hex(cid)] = counts.get(hex(cid), 0) + 1
            if attack:
                for k in range(50):
                    ts = tick - 0.1 + k * 0.002
                    items.append([ts, ATTACK_ID, 8, "ff" * 8])
                counts[hex(ATTACK_ID)] = 100
            items.sort(key=lambda x: x[0])

            level = random.randint(80, 98) if attack else random.randint(3, 25)
            verdict = {"type": "verdict", "window_start": tick - 0.2,
                       "score": -0.1 - level / 200.0, "threat_level": level,
                       "is_anomaly": attack, "counts": counts}
            payload = (json.dumps({"type": "frames", "items": items}) + "\n" +
                       json.dumps(verdict) + "\n").encode()

            for c in clients[:]:
                try:
                    c.sendall(payload)
                except OSError:
                    clients.remove(c)
                    print("client disconnected")
            time.sleep(max(0.0, 0.1 - (time.time() - tick)))
    except KeyboardInterrupt:
        pass
    finally:
        srv.close()
        if os.path.exists(SOCK):
            os.unlink(SOCK)


if __name__ == "__main__":
    main()
