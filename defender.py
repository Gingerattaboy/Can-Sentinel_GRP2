#!/usr/bin/env python3
"""CAN-Sentinel defender

Reads verdict events from the events socket and sends a SIMULATED quarantine
command to the victim ECU as a control frame on vcan0:

    CAN ID 0x7F0, DLC 3: bytes 0-1 = target ID (big-endian), byte 2 = 1 on / 0 off

Logic: ON after --on-after (3) consecutive anomalous verdicts naming the same
suspect_id; OFF after --off-after (10) consecutive clean verdicts.
This is an APPLICATION-LEVEL SIMULATION of an error-frame defence, not a real
CAN error-frame implementation.

Safety: vcan0 only; targets limited to the agreed ID map; cooldown between
commands; every action is appended to data/defense_log.csv; quarantines are
released on exit.

  live:    python defender.py
  replay:  python defender.py --replay tests/sample_events.jsonl   (no bus needed)
"""
import argparse, csv, json, os, signal, socket, struct, sys, time

CAN_IFACE = "vcan0"
CTRL_ID = 0x7F0
EVENTS_SOCK = "/tmp/can_sentinel_events.sock"
ALLOWED_TARGETS = {0x100, 0x200, 0x300, 0x400, 0x500}
LOG_FIELDS = ["wall_time", "event_time", "action", "target_id", "reason", "sent"]


def encode_control(target, on):
    return struct.pack(">HB", target, 1 if on else 0)


class CanSender:
    """Raw SocketCAN sender. Refuses any interface except vcan0."""
    def __init__(self, iface=CAN_IFACE):
        if iface != CAN_IFACE:
            raise ValueError(f"refused: defender only runs on {CAN_IFACE}, got {iface!r}")
        self.sock = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        self.sock.bind((iface,))

    def send(self, can_id, data):
        self.sock.send(struct.pack("=IB3x8s", can_id, len(data), data.ljust(8, b"\0")))


class DryRunSender:
    def __init__(self):
        self.sent = []

    def send(self, can_id, data):
        self.sent.append((can_id, data))


class AuditLog:
    def __init__(self, path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        new = not os.path.exists(path) or os.path.getsize(path) == 0
        self.f = open(path, "a", newline="")
        self.w = csv.DictWriter(self.f, LOG_FIELDS)
        if new:
            self.w.writeheader()

    def write(self, **row):
        row.setdefault("wall_time", f"{time.time():.3f}")
        self.w.writerow(row)
        self.f.flush()


class Defender:
    def __init__(self, sender, log, on_after=3, off_after=10, cooldown=1.0,
                 allowed=ALLOWED_TARGETS):
        self.sender, self.log = sender, log
        self.on_after, self.off_after, self.cooldown = on_after, off_after, cooldown
        self.allowed = set(allowed)
        self.streak_id, self.streak_n, self.clean_n = None, 0, 0
        self.active = set()
        self.last_cmd = None
        self._refused = set()

    def handle(self, v):
        """Process one verdict dict."""
        if v.get("type") != "verdict":
            return
        t = v.get("window_start") or time.time()
        if v.get("is_anomaly"):
            self.clean_n = 0
            sid = v.get("suspect_id")
            if sid is None:
                return
            self.streak_n = self.streak_n + 1 if sid == self.streak_id else 1
            self.streak_id = sid
            if self.streak_n >= self.on_after and sid not in self.active:
                self._command(sid, True, t,
                              f"{self.streak_n} consecutive anomalous verdicts, "
                              f"suspect_z={v.get('suspect_z')}")
        else:
            self.streak_id, self.streak_n = None, 0
            self._refused.clear()
            self.clean_n += 1
            if self.active and self.clean_n >= self.off_after:
                for tid in sorted(self.active):
                    if not self._command(tid, False, t, f"{self.clean_n} consecutive clean verdicts"):
                        break          # cooldown: retry on next clean verdict

    def release_all(self, reason="shutdown"):
        for tid in sorted(self.active):
            self._command(tid, False, None, reason, force=True)

    def _command(self, target, on, t, reason, force=False):
        action = "ON" if on else "OFF"
        if target not in self.allowed:
            if target not in self._refused:        # log once, not every verdict
                self._refused.add(target)
                self.log.write(event_time=t, action="REFUSED", target_id=hex(target),
                               reason="target not in allowed ID map", sent=False)
            return False
        if not force and self.last_cmd is not None and t - self.last_cmd < self.cooldown:
            return False
        self.sender.send(CTRL_ID, encode_control(target, on))
        self.last_cmd = t
        (self.active.add if on else self.active.discard)(target)
        self.log.write(event_time=t, action=action, target_id=hex(target),
                       reason=reason, sent=True)
        print(f"[defender] quarantine {action} -> {hex(target)}  ({reason})", flush=True)
        return True


def replay(path, defender):
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                defender.handle(json.loads(line))


def live(defender, sock_path):
    stop = False

    def _stop(*_):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    while not stop:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(1.0)
        try:
            s.connect(sock_path)
        except OSError:
            s.close()
            time.sleep(1.0)
            continue
        print("[defender] connected to events socket", flush=True)
        buf = b""
        while not stop:
            try:
                chunk = s.recv(65536)
            except socket.timeout:
                continue
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            *lines, buf = buf.split(b"\n")
            for ln in lines:
                if ln.strip():
                    try:
                        defender.handle(json.loads(ln))
                    except json.JSONDecodeError:
                        pass
        s.close()
        print("[defender] events socket lost", flush=True)
    defender.release_all("shutdown")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--on-after", type=int, default=3)
    ap.add_argument("--off-after", type=int, default=10)
    ap.add_argument("--cooldown", type=float, default=1.0, help="seconds between commands")
    ap.add_argument("--iface", default=CAN_IFACE, help="must be vcan0")
    ap.add_argument("--events-sock", default=EVENTS_SOCK)
    ap.add_argument("--log", default=None)
    ap.add_argument("--replay", help="JSONL file of recorded events (dry run, no bus)")
    ap.add_argument("--dry-run", action="store_true", help="live events, but do not send frames")
    a = ap.parse_args()

    dry = bool(a.replay or a.dry_run)
    sender = DryRunSender() if dry else CanSender(a.iface)
    if dry and a.iface != CAN_IFACE:
        sys.exit(f"refused: defender only runs on {CAN_IFACE}")
    log = AuditLog(a.log or ("data/defense_log_replay.csv" if a.replay else "data/defense_log.csv"))
    d = Defender(sender, log, a.on_after, a.off_after, a.cooldown)
    if a.replay:
        replay(a.replay, d)
        print(f"replay done: {len(sender.sent)} control frames would be sent")
    else:
        live(d, a.events_sock)


if __name__ == "__main__":
    main()
