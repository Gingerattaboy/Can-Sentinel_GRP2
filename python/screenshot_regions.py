"""Save report screenshots of every car-diagram region (Week 4, Member 3).

Feeds mock verdicts straight into the real MainWindow (no sockets needed) and
saves one PNG per state in docs/screenshots/ (run from the repo root):

    python3 python/dashboard/screenshot_regions.py
    # headless machine:  QT_QPA_PLATFORM=offscreen python3 python/dashboard/screenshot_regions.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import QApplication   # noqa: E402

from main import MainWindow                # noqa: E402

OUT = os.path.join("docs", "screenshots")
CASES = [  # (file label, suspect_id) - one per region + one unknown ID
    ("engine_rpm_0x100", 0x100), ("drivetrain_0x200", 0x200),
    ("steering_0x300", 0x300), ("engine_cooling_0x400", 0x400),
    ("brakes_0x500", 0x500), ("unknown_0x7ff", 0x7FF),
]


def main():
    os.makedirs(OUT, exist_ok=True)
    app = QApplication(sys.argv)
    win = MainWindow("/tmp/no_such_events.sock")   # no live service needed
    win.show()
    app.processEvents()

    def shot(name):
        app.processEvents()
        path = os.path.join(OUT, name + ".png")
        win.grab().save(path)
        print("saved", path)

    win.on_verdict({"type": "verdict", "window_start": time.time(), "score": -0.1,
                    "threat_level": 8, "is_anomaly": False, "counts": {},
                    "suspect_id": 0x100, "suspect_z": 0.4})
    shot("diagram_normal")

    for label, sid in CASES:
        win.on_verdict({"type": "verdict", "window_start": time.time(),
                        "score": -0.6, "threat_level": 92, "is_anomaly": True,
                        "counts": {hex(sid): 100}, "suspect_id": sid,
                        "suspect_z": 11.7})
        shot("diagram_" + label)

    # quarantine indicator: ON frame for 0x500, then OFF
    win.car_panel.on_frames([[time.time(), 0x7F0, 3, "050001"]])
    shot("diagram_quarantine_on")
    win.car_panel.on_frames([[time.time(), 0x7F0, 3, "050000"]])

    win.close()


if __name__ == "__main__":
    main()
