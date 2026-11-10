# Countermeasure (SIMULATED)

> **Disclosure:** this defence is a **simulation at application level on vcan0**. It is **not** a real CAN
> error-frame implementation. vcan has no electrical layer, so nothing here can destroy or override a frame
> on a wire. It only imitates the *effect* of such a defence in software.

## Why simulated
On a real CAN bus, a node can destroy a frame in flight by driving a dominant bit during the frame, which
triggers an error frame, and repeated errors push the sending node's transmit error counter up until it goes
error-passive and then bus-off. That needs a real CAN controller and physical layer. vcan0 is a software
loopback: frames are just copied between sockets, so no bus-level arbitration or error signalling exists.

## Protocol
Control frame on CAN ID `0x7F0`, DLC 3: bytes 0-1 target ID (big-endian), byte 2 = 1 on / 0 off.
The victim ECU (`victim_ecu.c`, brake receiver on 0x500) listens for it. While quarantine is on it accepts
at most one 0x500 frame per 20 ms and drops the rest. Collateral drops of legitimate frames are measured and reported.

## Defender logic (`defender.py`)
1. Read `verdict` events from the events socket.
2. **ON:** after `--on-after` (default 3) consecutive anomalous verdicts with the same `suspect_id`.
3. **OFF:** after `--off-after` (default 10) consecutive clean verdicts. Any anomaly resets the clean streak.
4. Safety limits: vcan0 only (`CanSender` refuses other names); targets restricted to the ID map
   (0x100-0x500); `--cooldown` seconds between commands; quarantines released on exit;
   every action (ON, OFF, REFUSED) appended to `data/defense_log.csv`.
5. Replay test (no bus): `python defender.py --replay tests/sample_events.jsonl`; unit tests: `python -m unittest discover -s tests`.

## Limits
- Frequency-based suspicion can name the wrong ID if the attacker copies normal timing.
- The rate limiter can drop legitimate frames; this is reported, not hidden.
- The attacker's ground-truth tag (0xA5) is used only by the evaluation, never by the detector or defender.
