import json, os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from defender import Defender, DryRunSender, AuditLog, CanSender, encode_control, CTRL_ID, replay


def verdict(t, anomaly, suspect=0x500, z=9.0):
    return {"type": "verdict", "window_start": t, "score": 0.5, "threat_level": 80 if anomaly else 5,
            "is_anomaly": anomaly, "counts": {}, "suspect_id": suspect, "suspect_z": z}


def make(**kw):
    s = DryRunSender()
    log = AuditLog(os.path.join(tempfile.mkdtemp(), "log.csv"))
    return Defender(s, log, **kw), s


class T(unittest.TestCase):
    def test_encoding(self):
        self.assertEqual(encode_control(0x500, True), b"\x05\x00\x01")
        self.assertEqual(encode_control(0x100, False), b"\x01\x00\x00")

    def test_on_after_3_off_after_10(self):
        d, s = make(cooldown=0)
        t = 0.0
        for _ in range(2):
            t += .1; d.handle(verdict(t, False))
        for i in range(5):
            t += .1; d.handle(verdict(t, True))
            if i < 2: self.assertEqual(s.sent, [])           # not yet
        self.assertEqual(s.sent, [(CTRL_ID, b"\x05\x00\x01")])  # exactly one ON, on 3rd anomaly
        for i in range(10):
            t += .1; d.handle(verdict(t, False))
            if i < 9: self.assertEqual(len(s.sent), 1)
        self.assertEqual(s.sent[-1], (CTRL_ID, b"\x05\x00\x00"))
        self.assertEqual(len(s.sent), 2)

    def test_streak_breaks(self):
        d, s = make(cooldown=0)
        for i, (a, sid) in enumerate([(1, 0x500), (1, 0x500), (0, 0x500), (1, 0x500), (1, 0x500),
                                      (1, 0x100), (1, 0x500), (1, 0x500)]):
            d.handle(verdict(i * .1, bool(a), sid))
        self.assertEqual(s.sent, [])                            # never 3 in a row for same ID

    def test_cooldown_delays_off(self):
        d, s = make(cooldown=5.0)
        t = 0.0
        for _ in range(3):
            t += .1; d.handle(verdict(t, True))
        on_t = t
        off_t = None
        for _ in range(80):
            t += .1; d.handle(verdict(t, False))
            if len(s.sent) == 2 and off_t is None: off_t = t
        self.assertIsNotNone(off_t)
        self.assertGreaterEqual(off_t - on_t, 5.0)

    def test_refuses_unknown_targets(self):
        d, s = make(cooldown=0)
        for i in range(10):
            d.handle(verdict(i * .1, True, suspect=0x7F0))
            d.handle(verdict(i * .1, True, suspect=0x123))
        self.assertEqual(s.sent, [])

    def test_release_all_on_shutdown(self):
        d, s = make(cooldown=0)
        for i in range(3): d.handle(verdict(i * .1, True))
        d.release_all()
        self.assertEqual(s.sent[-1], (CTRL_ID, b"\x05\x00\x00"))

    def test_vcan_only(self):
        with self.assertRaises(ValueError):
            CanSender("can0")
        with self.assertRaises(ValueError):
            CanSender("eth0")

    def test_replay_file(self):
        d, s = make(cooldown=0)
        replay(os.path.join(os.path.dirname(__file__), "sample_events.jsonl"), d)
        self.assertEqual([x[1][2] for x in s.sent], [1, 0])     # one ON then one OFF


if __name__ == "__main__":
    unittest.main()
