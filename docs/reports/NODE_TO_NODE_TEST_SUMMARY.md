# Node-to-Node Test Summary — Stable Send+Read Solution

## Problem Statement
The original node-to-node test could send messages successfully (confirmed by monitor/device display) but failed to read incoming messages programmatically via the meshcore Python API, preventing the AI from detecting replies.

## Root Cause
The receiver inbox API behavior depends on:
1. **API method used**: `get_msg()` returns single-message dict payloads with `{'text': '...'}`, while `get_messages()` returns lists
2. **Timing**: Messages must be polled repeatedly with a delay — immediate queries after send often return `{'messages_available': False}`
3. **Connection state**: Receiver must be connected via meshcore library when the message arrives for reliable programmatic retrieval

## Solution Implemented

### Key Changes in `meshcore_send.py`
1. **Exclusive-mode receiver open first** (lines ~268-276):
   - Open receiver serial port *before* sending (avoids monitor port conflicts)
   - Poll `get_msg()` first (not `get_messages()`) as it reliably returns dict payloads
   - Poll repeatedly with 0.4s sleep for up to `timeout` seconds

2. **Improved inbox polling loop** (lines ~322-361):
   - Try `get_msg` first in each poll iteration
   - Handle both dict (`{'text': '...'}`) and list payloads
   - Compare timestamps using epoch time when `ts > 1e9`, else monotonic loop time
   - Log poll count and payload summary for debugging

3. **Sender port retry logic** (lines ~283-291):
   - Retry opening sender port up to 5 times with 0.35s sleep (handles transient locks)

4. **Monitor fallback path** (lines ~576+):
   - Reordered `inbox_methods` list to try `get_msg` first
   - Added epoch timestamp handling for temporal filtering

### Test Results (2026-02-17)

#### A → B Direction (Enomee COM4 → Enomee B COM6)
- ✅ **Pass** — Message sent (`EventType.MSG_SENT`) and retrieved via `get_msg` poll #1
- Receiver payload: `{'type': 'PRIV', 'SNR': 12.0, 'pubkey_prefix': 'e7c354a9913b', 'path_len': 255, 'txt_type': 0, 'sender_timestamp': 1771326315, 'text': 'Node-to-node test message (do not forward to public networks)'}`
- Confirmed in multiple runs (poll #1 found message consistently)

#### B → A Direction (Enomee B COM6 → Enomee COM4)
- ✅ **Pass** — Message sent (`EventType.MSG_SENT`) and retrieved via `get_msg` poll #3
- Receiver payload contained full `text` field with test message
- Confirmed in multiple runs (poll #3 or earlier found message consistently)

### Configuration (`lara_config.yaml`)
```yaml
node_test:
  timeout_seconds: 8
  message: "Node-to-node test message (do not forward to public networks)"
  direction: "b_to_a"  # or "a_to_b" — both work stably
  allow_public_forwarding: false
```

## Usage

### Run integrated node-to-node test:
```powershell
.venv\Scripts\python meshcore_send.py --node-test
```

### Run with debug logging:
```powershell
.venv\Scripts\python meshcore_send.py --node-test --debug
```

### Switch direction (edit `lara_config.yaml`):
```yaml
direction: "a_to_b"  # Test A→B
# or
direction: "b_to_a"  # Test B→A
```

## Known Limitations
- **Standalone `test_node_to_node.py`**: Opens receiver *after* sending (monitor holds port during send), so messages aren't readable via API afterward. Use integrated `meshcore_send.py --node-test` instead.
- **CLI commands**: The firmware's interactive CLI (`meshcore-cli`) does not expose a `messages` command — use Python `meshcore` library API (`get_msg()`) instead.
- **Message type**: Node-to-node sends create PRIV (private) messages, which may not appear in all UI views.

## Why Interactive CLI Doesn't Show Messages
1. Firmware v1.13.0 interactive mode has no `messages` command (confirmed via `?get` help)
2. UI may filter PRIV messages or require specific commands not documented in help
3. Programmatic API (`get_msg()`) works reliably when receiver connection is open during message arrival

## Recommendations
- Always use `meshcore_send.py --node-test` (integrated test with exclusive receiver open)
- For production AI reply detection: open receiver connection before expecting messages, poll `get_msg()` repeatedly with ~0.4s delay
- Monitor evidence (device display) confirms transmission; programmatic read confirms storage/retrievability

## Files Modified
- `meshcore_send.py`: Added exclusive-mode receiver open, `get_msg` polling, sender port retry, epoch timestamp handling
- `lara_config.yaml`: Added `node_test` section with direction, timeout, message, safety flags
- `test_node_to_node.py`: Updated inbox method order, added dict payload handling (limited usefulness — see limitations)
- `README.md`: Added node-to-node test instructions

## Status
✅ **Stable and verified** — Both A→B and B→A directions pass consistently with programmatic send + inbox read verification.

---
*Last updated: 2026-02-17 by AI autonomous testing agent*
