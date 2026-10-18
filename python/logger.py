
#!/usr/bin/env python3

import argparse
import csv
from pathlib import Path
import time

import can


# Locate the main project directory.
PROJECT_DIR = Path(__file__).resolve().parent.parent
CSV_FILE = PROJECT_DIR / "data" / "normal_traffic.csv"


def main():
    parser = argparse.ArgumentParser(
        description="Log CAN messages from vcan0 into a CSV file."
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=30,
        help="Capture duration in seconds; use 0 for continuous capture.",
    )
    args = parser.parse_args()

    if args.duration < 0:
        parser.error("Duration cannot be negative.")

    # Open the virtual CAN interface.
    try:
        bus = can.Bus(
            interface="socketcan",
            channel="vcan0",
        )
    except Exception as error:
        raise SystemExit(
            f"Could not open vcan0: {error}\n"
            "Check that vcan0 exists and is UP."
        ) from error

    CSV_FILE.parent.mkdir(parents=True, exist_ok=True)
    frame_count = 0
    start_time = time.monotonic()

    try:
        with CSV_FILE.open(
            "w", newline="", encoding="utf-8"
        ) as file:
            writer = csv.writer(file)

            # Required header from the shared project contract.
            writer.writerow([
                "timestamp",
                "can_id",
                "dlc",
                "data_hex",
                "label",
            ])
            file.flush()

            print("CAN logger started.")
            print("Interface: vcan0")
            print(f"Saving messages to: {CSV_FILE}")
            print("Waiting for CAN messages...")

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

                    # Save each received CAN frame.
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
    print(f"CSV file: {CSV_FILE}")


if __name__ == "__main__":
    main()
