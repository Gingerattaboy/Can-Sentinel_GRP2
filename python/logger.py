#!/usr/bin/env python3
"""
logger.py - record CAN frames from a SocketCAN interface into a CSV file.

Examples (run from the repo root):
    python python/logger.py                    # record until Ctrl+C
    python python/logger.py --duration 600     # record for 10 minutes
    python python/logger.py -o data/test.csv   # choose the output file
    python python/logger.py -c vcan1 --force   # other interface, overwrite file

CSV columns (shared project contract): timestamp, can_id, dlc, data_hex, label
"""

import argparse
import csv
import time
from pathlib import Path

try:
    import can
except ImportError:
    raise SystemExit(
        "python-can is not installed. Activate your virtual environment and run:\n"
        "    pip install -r python/requirements.txt"
    )

# Locate the main project directory.
PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = PROJECT_DIR / "data" / "normal_traffic.csv"

# Required header from the shared project contract.
HEADER = ["timestamp", "can_id", "dlc", "data_hex", "label"]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Log CAN messages from a SocketCAN interface into a CSV file."
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output CSV file (default: {DEFAULT_OUTPUT}).",
    )
    parser.add_argument(
        "-c", "--channel",
        default="vcan0",
        help="CAN interface to read from (default: vcan0).",
    )
    parser.add_argument(
        "-d", "--duration",
        type=float,
        default=0,
        help="Capture duration in seconds; 0 (the default) records until Ctrl+C.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the output file if it already exists.",
    )
    args = parser.parse_args()
    if args.duration < 0:
        parser.error("Duration cannot be negative.")
    return args


def main():
    args = parse_args()
    output = args.output

    # Never silently destroy an existing recording.
    if output.exists() and not args.force:
        raise SystemExit(
            f"ERROR: {output} already exists.\n"
            "Choose another file with --output, or use --force to overwrite it."
        )

    # Open the CAN interface.
    try:
        bus = can.Bus(interface="socketcan", channel=args.channel)
    except Exception as error:
        raise SystemExit(
            f"Could not open {args.channel}: {error}\n"
            "Check that the interface exists and is UP (./scripts/setup_vcan.sh)."
        ) from error

    output.parent.mkdir(parents=True, exist_ok=True)

    frame_count = 0
    start_time = time.monotonic()

    try:
        with output.open("w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(HEADER)
            file.flush()

            print("CAN logger started.")
            print(f"Interface: {args.channel}")
            print(f"Saving messages to: {output}")
            if args.duration == 0:
                print("Recording until you press Ctrl+C.")
            else:
                print(f"Recording for {args.duration:g} seconds (Ctrl+C stops early).")

            try:
                while (
                    args.duration == 0
                    or time.monotonic() - start_time < args.duration
                ):
                    message = bus.recv(timeout=1.0)
                    if message is None:
                        continue

                    # This project uses standard CAN frames.
                    if (
                        message.is_error_frame
                        or message.is_remote_frame
                        or message.is_extended_id
                    ):
                        continue

                    writer.writerow([
                        f"{message.timestamp:.6f}",
                        f"0x{message.arbitration_id:03x}",
                        message.dlc,
                        bytes(message.data).hex().upper(),
                        0,
                    ])
                    file.flush()
                    frame_count += 1
            except KeyboardInterrupt:
                print("\nCapture stopped by user.")
    finally:
        bus.shutdown()

    print(f"Capture finished. Frames recorded: {frame_count}")
    print(f"CSV file: {output}")


if __name__ == "__main__":
    main()
