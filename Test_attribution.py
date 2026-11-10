import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np
from attribution import Attributor, fit_baseline, counts_from_frames


def periodic(period, t_end, cid, jitter=0.0003, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(0, t_end, period) + rng.normal(0, jitter, int(t_end / period) + 1)[: len(np.arange(0, t_end, period))]
    return t, np.full(len(t), cid)


class T(unittest.TestCase):
    def setUp(self):
        parts = [periodic(.01, 30, 0x100), periodic(.02, 30, 0x200),
                 periodic(.05, 30, 0x300), periodic(.1, 30, 0x500)]
        ts = np.concatenate([p[0] for p in parts]); ids = np.concatenate([p[1] for p in parts])
        self.attr = Attributor(fit_baseline(counts_from_frames(ts, ids)))

    def test_normal_window_low_z(self):
        _, z = self.attr.suspect({0x100: 20, 0x200: 10, 0x300: 4, 0x500: 2})
        self.assertLess(z, 3)

    def test_flood_on_brake_id(self):
        sid, z = self.attr.suspect({0x100: 20, 0x200: 10, 0x300: 4, 0x500: 60})
        self.assertEqual(sid, 0x500); self.assertGreater(z, 10)

    def test_string_keys_and_unknown_id(self):
        sid, _ = self.attr.suspect({"0x100": 20, "0x200": 10, "0x300": 4, "0x500": 2, "0x666": 30})
        self.assertEqual(sid, 0x666)

    def test_missing_id_is_suspicious(self):
        sid, _ = self.attr.suspect({0x100: 20, 0x200: 10, 0x300: 4})   # 0x500 vanished
        self.assertEqual(sid, 0x500)


if __name__ == "__main__":
    unittest.main()
