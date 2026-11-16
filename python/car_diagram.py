"""CAN-Sentinel car diagram + quarantine indicator (Week 4, Member 3).

CarDiagram  - QPainter top-down car with four regions (Engine, Drivetrain,
              Steering, Brakes). The suspect's region turns red.
CarPanel    - diagram + caption (suspect ID, z-score) + Quarantine indicator.

Wiring (see main.py):
    reader.frames_received -> CarPanel.on_frames    (spots 0x7F0 frames)
    MainWindow.verdict_received -> CarPanel.on_verdict

NOTE: the quarantine defence is SIMULATED at application level on vcan0.
It is not a real CAN error-frame implementation.
"""
from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

QUARANTINE_CTRL_ID = 0x7F0

# contract: ID -> system. 0x100 and 0x400 are both engine-side.
ID_TO_REGION = {
    0x100: "Engine",       # RPM
    0x200: "Drivetrain",   # speed
    0x300: "Steering",
    0x400: "Engine",       # cooling temperature
    0x500: "Brakes",
}
REGIONS = ["Engine", "Steering", "Drivetrain", "Brakes"]


def parse_id(key):
    """Accept int, '0x500', '500' or '1280'; return int or None."""
    if key is None:
        return None
    if isinstance(key, int):
        return key
    try:
        return int(str(key), 0)
    except ValueError:
        try:
            return int(str(key), 16)
        except ValueError:
            return None


def _rr(x, y, w, h, r=8.0):
    p = QPainterPath()
    p.addRoundedRect(QRectF(x, y, w, h), r, r)
    return p


def _build_regions():
    """name -> (path, label_rect, label_on_body). Drawn in a 200x400 box."""
    drive = _rr(66, 182, 68, 100, 8)
    drive.addRoundedRect(QRectF(56, 290, 88, 30), 6, 6)       # rear differential
    wheels = _rr(14, 128, 24, 56, 6)
    for x, y in ((162, 128), (14, 290), (162, 290)):
        wheels.addRoundedRect(QRectF(x, y, 24, 56), 6, 6)
    return {
        "Engine": (_rr(60, 35, 80, 85, 10), QRectF(60, 35, 80, 85), False),
        "Steering": (_rr(52, 135, 96, 34, 8), QRectF(52, 135, 96, 34), False),
        "Drivetrain": (drive, QRectF(66, 182, 68, 100), False),
        "Brakes": (wheels, QRectF(56, 335, 88, 24), True),     # label under body
    }


class CarDiagram(QWidget):
    NORMAL_FILL = QColor(200, 210, 222)
    HOT_FILL = QColor(215, 38, 38)
    OUTLINE = QColor(90, 100, 110)
    HOT_OUTLINE = QColor(120, 0, 0)
    TEXT = QColor(30, 35, 40)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._regions = _build_regions()
        self._active = None
        self.setMinimumSize(160, 320)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    @property
    def active_region(self):
        return self._active

    def set_active_region(self, name):
        if name not in self._regions:
            name = None
        if name != self._active:
            self._active = name
            self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        s = min(w / 200.0, h / 400.0)
        p.translate((w - 200 * s) / 2.0, (h - 400 * s) / 2.0)
        p.scale(s, s)

        # body
        p.setPen(QPen(self.OUTLINE, 2))
        p.setBrush(QColor(246, 248, 251))
        p.drawPath(_rr(40, 20, 120, 360, 28))
        small = QFont()
        small.setPixelSize(10)
        p.setFont(small)
        p.setPen(QColor(130, 140, 150))
        p.drawText(QRectF(40, 4, 120, 14), Qt.AlignCenter, "FRONT")

        for name, (path, label_rect, on_body) in self._regions.items():
            hot = (name == self._active)
            p.setPen(QPen(self.HOT_OUTLINE if hot else self.OUTLINE, 1.5))
            p.setBrush(self.HOT_FILL if hot else self.NORMAL_FILL)
            p.drawPath(path)
            f = QFont()
            f.setPixelSize(12)
            f.setBold(hot)
            p.setFont(f)
            if on_body:
                p.setPen(self.HOT_FILL if hot else self.TEXT)
            else:
                p.setPen(QColor(255, 255, 255) if hot else self.TEXT)
            p.drawText(label_rect, Qt.AlignCenter, name)
        p.end()


class CarPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.diagram = CarDiagram()
        self.caption = QLabel()
        self.caption.setAlignment(Qt.AlignCenter)
        self.caption.setWordWrap(True)
        self.quarantine = QLabel()
        self.quarantine.setAlignment(Qt.AlignCenter)
        self.quarantine.setMinimumHeight(28)

        lay = QVBoxLayout(self)
        lay.addWidget(self.diagram, 1)
        lay.addWidget(self.caption)
        lay.addWidget(self.quarantine)

        self._quarantined = set()
        self.reset()

    # ---- public API
    def reset(self):
        self._quarantined.clear()
        self.diagram.set_active_region(None)
        self._set_caption("Traffic normal", False)
        self._refresh_quarantine()

    def on_verdict(self, ev):
        if not ev.get("is_anomaly"):
            self.diagram.set_active_region(None)
            self._set_caption("Traffic normal", False)
            return
        sid = parse_id(ev.get("suspect_id"))
        if sid is None:
            self.diagram.set_active_region(None)
            self._set_caption("Anomaly detected - suspect not reported", True)
            return
        region = ID_TO_REGION.get(sid)
        self.diagram.set_active_region(region)
        z = ev.get("suspect_z")
        z_txt = f"   z = {z:.1f}" if isinstance(z, (int, float)) else ""
        self._set_caption(
            f"Suspect 0x{sid:03X} ({region or 'unknown system'}){z_txt}", True)

    def on_frames(self, items):
        """Look for quarantine control frames (ID 0x7F0, DLC 3) in the stream."""
        changed = False
        for it in items:
            try:
                if int(it[1]) != QUARANTINE_CTRL_ID:
                    continue
                data = bytes.fromhex(str(it[3]))
            except (IndexError, ValueError, TypeError):
                continue
            if len(data) < 3:
                continue
            target = (data[0] << 8) | data[1]      # big-endian
            if data[2] == 1:
                self._quarantined.add(target)
                changed = True
            elif data[2] == 0:
                self._quarantined.discard(target)
                changed = True
        if changed:
            self._refresh_quarantine()

    # ---- helpers
    def _set_caption(self, text, alert):
        self.caption.setText(text)
        self.caption.setStyleSheet(
            "font-weight: bold; color: #b00020;" if alert
            else "color: #1a8a3a; font-weight: bold;")

    def _refresh_quarantine(self):
        if self._quarantined:
            ids = ", ".join(f"0x{i:03X}" for i in sorted(self._quarantined))
            self.quarantine.setText(f"QUARANTINE ACTIVE: {ids} (simulated)")
            self.quarantine.setStyleSheet(
                "background: #d98200; color: white; font-weight: bold;"
                " border-radius: 4px; padding: 4px;")
        else:
            self.quarantine.setText("Quarantine inactive")
            self.quarantine.setStyleSheet(
                "background: #e3e6ea; color: #555; border-radius: 4px;"
                " padding: 4px;")
