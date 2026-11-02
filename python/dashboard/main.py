#!/usr/bin/env python3
"""CAN-Sentinel dashboard core (Week 3, Member 3).

- Main window: frame table on the left, reserved panels for gauge/alerts on the right
- EventReader (QThread): connects to the events socket, reads JSON lines, emits signals
- FrameTableModel: last 500 rows, repainted at most 10 times per second
- Rows whose CAN ID appears in an anomalous verdict are highlighted

Member 4 hooks: connect to MainWindow.verdict_received (dict) and
replace/fill MainWindow.gauge_slot and MainWindow.alert_slot layouts.
"""
import json
import socket
import sys
import time
from collections import deque

from PyQt5.QtCore import (QAbstractTableModel, QModelIndex, Qt, QThread,
                          QTimer, pyqtSignal)
from PyQt5.QtGui import QBrush, QColor, QFont
from PyQt5.QtWidgets import (QApplication, QGroupBox, QHBoxLayout, QHeaderView,
                             QLabel, QMainWindow, QTableView, QVBoxLayout,
                             QWidget)

EVENTS_SOCK = "/tmp/can_sentinel_events.sock"
MAX_ROWS = 500
REPAINT_MS = 100          # at most 10 repaints per second
HIGHLIGHT_SECONDS = 2.0   # how long an anomalous ID stays highlighted
HEADERS = ["Time", "ID", "DLC", "Data"]


def parse_id(key):
    """Accept an int, '0x1A0', '1A0' or '416' and return an int (or None)."""
    if isinstance(key, int):
        return key
    try:
        return int(str(key), 0)
    except ValueError:
        try:
            return int(str(key), 16)
        except ValueError:
            return None


class EventReader(QThread):
    """Connects to the events socket and emits parsed JSON events.

    Reconnects every second if the service is not up or the link drops.
    """
    frames_received = pyqtSignal(list)
    verdict_received = pyqtSignal(dict)
    status_changed = pyqtSignal(str)   # "connected" | "disconnected"

    def __init__(self, path=EVENTS_SOCK, parent=None):
        super().__init__(parent)
        self.path = path
        self._running = True

    def stop(self):
        self._running = False
        self.wait(3000)

    def run(self):
        while self._running:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(0.5)
            try:
                sock.connect(self.path)
            except OSError:
                sock.close()
                self.status_changed.emit("disconnected")
                self._sleep(1.0)
                continue

            self.status_changed.emit("connected")
            buf = b""
            while self._running:
                try:
                    chunk = sock.recv(65536)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if line.strip():
                        self._dispatch(line)
            sock.close()
            self.status_changed.emit("disconnected")
            self._sleep(1.0)

    def _sleep(self, seconds):
        end = time.monotonic() + seconds
        while self._running and time.monotonic() < end:
            time.sleep(0.05)

    def _dispatch(self, line):
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            return
        kind = ev.get("type")
        if kind == "frames":
            self.frames_received.emit(ev.get("items", []))
        elif kind == "verdict":
            self.verdict_received.emit(ev)


class FrameTableModel(QAbstractTableModel):
    """Keeps the last MAX_ROWS frames; highlights anomalous IDs."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = deque(maxlen=MAX_ROWS)
        self.pending = []
        self.hot_ids = {}   # can_id -> expiry (monotonic seconds)

    # --- data intake (cheap, called from signals) ---
    def queue_frames(self, items):
        self.pending.extend(items)
        # never let the backlog grow past what we can show
        if len(self.pending) > MAX_ROWS:
            self.pending = self.pending[-MAX_ROWS:]

    def mark_anomalous(self, ids):
        expiry = time.monotonic() + HIGHLIGHT_SECONDS
        for i in ids:
            self.hot_ids[i] = expiry

    # --- batched flush, driven by the 10 Hz timer ---
    def flush(self):
        now = time.monotonic()
        self.hot_ids = {k: v for k, v in self.hot_ids.items() if v > now}
        if not self.pending and not self.rows:
            return False
        self.beginResetModel()
        for item in self.pending:
            self.rows.append(item)
        self.pending = []
        self.endResetModel()
        return True

    # --- Qt model interface ---
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return HEADERS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        ts, can_id, dlc, data_hex = self.rows[index.row()][:4]
        if role == Qt.DisplayRole:
            col = index.column()
            if col == 0:
                return f"{float(ts):.6f}"
            if col == 1:
                return f"0x{int(can_id):03X}"
            if col == 2:
                return str(dlc)
            return " ".join(data_hex[i:i + 2] for i in range(0, len(data_hex), 2)).upper()
        if role == Qt.BackgroundRole and int(can_id) in self.hot_ids:
            return QBrush(QColor(255, 205, 205))
        if role == Qt.ForegroundRole and int(can_id) in self.hot_ids:
            return QBrush(QColor(140, 0, 0))
        if role == Qt.FontRole:
            f = QFont("monospace")
            f.setStyleHint(QFont.Monospace)
            return f
        return None


class MainWindow(QMainWindow):
    verdict_received = pyqtSignal(dict)   # Member 4 connects gauge/alerts here

    def __init__(self, sock_path=EVENTS_SOCK):
        super().__init__()
        self.setWindowTitle("CAN-Sentinel")
        self.resize(1100, 650)

        # left: live frame table
        self.model = FrameTableModel(self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(20)
        self.table.setEditTriggers(QTableView.NoEditTriggers)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)

        left = QGroupBox("Live CAN traffic (last 500 frames)")
        QVBoxLayout(left).addWidget(self.table)

        # right: reserved space for Member 4
        gauge_box = QGroupBox("Threat level")
        self.gauge_slot = QVBoxLayout(gauge_box)
        self.gauge_slot.addWidget(QLabel("Gauge goes here (Member 4)"))
        self.verdict_label = QLabel("Threat: -   Score: -")
        self.gauge_slot.addWidget(self.verdict_label)

        alert_box = QGroupBox("Alerts")
        self.alert_slot = QVBoxLayout(alert_box)
        self.alert_slot.addWidget(QLabel("Alert banner and history go here (Member 4)"))

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.addWidget(gauge_box, 1)
        rl.addWidget(alert_box, 2)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.addWidget(left, 3)
        layout.addWidget(right, 2)
        self.setCentralWidget(central)

        # status indicator
        self.status = QLabel()
        self.statusBar().addPermanentWidget(self.status)
        self.set_status("disconnected")

        # event reader thread
        self.reader = EventReader(sock_path, self)
        self.reader.status_changed.connect(self.set_status)
        self.reader.frames_received.connect(self.model.queue_frames)
        self.reader.verdict_received.connect(self.on_verdict)
        self.reader.start()

        # repaint at most 10 times per second
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_table)
        self.timer.start(REPAINT_MS)

    def set_status(self, state):
        if state == "connected":
            self.status.setText("● Connected to inference service")
            self.status.setStyleSheet("color: #1a8a3a; font-weight: bold;")
        else:
            self.status.setText("● Disconnected (retrying...)")
            self.status.setStyleSheet("color: #b00020; font-weight: bold;")

    def on_verdict(self, ev):
        self.verdict_label.setText(
            f"Threat: {ev.get('threat_level', '-')}   Score: {ev.get('score', 0):.3f}")
        if ev.get("is_anomaly"):
            counts = ev.get("counts") or {}
            keys = counts.keys() if isinstance(counts, dict) else []
            ids = [i for i in (parse_id(k) for k in keys) if i is not None]
            self.model.mark_anomalous(ids)
        self.verdict_received.emit(ev)

    def refresh_table(self):
        at_bottom = (self.table.verticalScrollBar().value()
                     >= self.table.verticalScrollBar().maximum() - 2)
        if self.model.flush() and at_bottom:
            self.table.scrollToBottom()

    def closeEvent(self, event):
        self.timer.stop()
        self.reader.stop()
        super().closeEvent(event)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else EVENTS_SOCK
    app = QApplication(sys.argv)
    win = MainWindow(path)
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
