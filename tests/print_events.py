#!/usr/bin/env python3
"""Acts as a dashboard: connects to the events socket and prints what arrives."""
import json, socket
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.connect("/tmp/can_sentinel_events.sock")
for line in s.makefile():
    e = json.loads(line)
    if e["type"] == "verdict":
        print(f'verdict  threat={e["threat_level"]:3d}  anomaly={e["is_anomaly"]!s:5}  counts={e["counts"]}')
    else:
        print(f'frames   {len(e["items"])} frames')
