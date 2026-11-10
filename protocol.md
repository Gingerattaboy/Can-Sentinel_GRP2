# CAN-Sentinel Protocol

Safety rule: every tool reads/writes **vcan0 only**.

## 1. Frames socket (sniffer -> inference service)
- Unix domain socket, `SOCK_STREAM`, path `/tmp/can_sentinel_frames.sock`.
- Inference service = **server** (deletes a stale socket file before `bind`). C sniffer = **client**.
- Byte stream of fixed **21-byte records**, little-endian, no padding. Python: `struct.Struct("<dIB8s")`.

| Offset | Size | Type    | Field                                        |
|-------:|-----:|---------|----------------------------------------------|
| 0      | 8    | float64 | timestamp, seconds since epoch (kernel `SO_TIMESTAMP`) |
| 8      | 4    | uint32  | CAN ID (error frames are skipped)            |
| 12     | 1    | uint8   | DLC (0-8)                                    |
| 13     | 8    | bytes   | data, zero-padded to 8                       |

### Sniffer behaviour
- Reads with `recvmsg` on a raw SocketCAN socket; timestamp comes from the kernel receive time.
- **Never blocks the bus.** All socket calls are non-blocking. Whole records are queued (~4096 records);
  if the queue is full, or the service is not connected, the frame is **dropped and counted**.
- **Reconnect:** if the service disconnects or a send fails, the sniffer discards any partially sent record,
  closes the socket and retries every 500 ms. The service must be able to accept a new connection at any time
  and must treat a new connection as a fresh stream (record boundaries restart at byte 0).
- **Stats:** once per second on stderr: `fps, sent, drops (queue_full, no_link), totals, link up/down`.
- Receiver must buffer partial reads: `usable = len(buf) - len(buf) % 21`.

## 2. Events socket (inference service -> dashboard, defender)
- Unix socket `/tmp/can_sentinel_events.sock`, newline-delimited JSON. Service = server; dashboard and defender = clients.
- `{"type":"frames","items":[[ts,id,dlc,"data_hex"],...]}` every 100 ms.
- `{"type":"verdict","window_start":ts,"score":s,"threat_level":0-100,"is_anomaly":bool,"counts":{id:n},`
  `"suspect_id":int,"suspect_z":float}` every window step (100 ms).
  `suspect_id`/`suspect_z` are added in Week 4 (see `attribution.py`).

## 3. Control frame (defender -> victim ECU), on vcan0
CAN ID `0x7F0`, DLC 3: bytes 0-1 = target ID (big-endian), byte 2 = 1 quarantine on / 0 off.
Example: `7F0#050001` = quarantine ON for 0x500. **Simulated defence - see `countermeasure.md`.**

## 4. ID to system map
0x100 Engine (RPM), 0x200 Drivetrain (speed), 0x300 Steering, 0x400 Engine cooling (temperature), 0x500 Brakes.

## 5. Latency terms (report separately)
- **Transport latency** (per frame): service receive time minus sniffer kernel timestamp. Target median < 1 ms.
- **Detection delay** (per window): at most one 100 ms step plus inference time. Do not claim sub-millisecond detection.
