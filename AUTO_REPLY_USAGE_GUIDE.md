# Auto-Reply PRIV Bot — Usage Guide

## Quick Start

### Run on a Single Node

1. **Ensure configuration is correct** in [lara_config.yaml](lara_config.yaml):
   ```yaml
   nodes:
     node_a:
       active_instance: false  # or true, depending on which node to monitor
     node_b:
       active_instance: true   # Set this to the node you want to run the bot on
   ```

2. **Run the bot**:
   ```powershell
   .venv\Scripts\python.exe auto_reply_priv.py
   ```

3. **Send a test message** from the other node:
   ```powershell
   # If node_b is running the bot, send from node_a:
   .venv\Scripts\python.exe send_only_test.py
   ```

4. **Observe the response**: The bot will:
   - Detect the incoming PRIV message
   - Call OpenWebUI API to generate a response
   - Send the AI-generated response back via PRIV

---

## Configuration Options

**`lara_config.yaml`** sections:

### Radio & Nodes
```yaml
radio:
  port: "COM6"                    # Primary COM port for the bot
  baud: 115200                    # Baud rate
  node_name: "Enomee"            # Bot's node name

nodes:
  node_a:                         # This device
    name: "Enomee"
    port: "COM6"
    pubkey: "0d620201..."         # Your device public key
    active_instance: true         # Bot monitors this port
  node_b:                         # Remote device
    name: "Enomee"
    port: "COM4"
    pubkey: "e7c354a9..."         # Remote device public key
```

### Bot Behavior
```yaml
bot_behavior:
  active: true                    # Enable/disable auto-reply functionality
  reply_to_all: true             # Respond to all PRIV messages
  chunk_chars: 145               # Characters per chunk (5 reserved for " X/Y")
  max_chunks: 3                  # Max chunks per response (truncate with " ?/3")
  debug_auto_reply: true         # Detailed logging (recommended)
  allow_self_processing: true    # Process own messages (for testing)
  circular_max_iterations: 3     # Max AI loop iterations
  
  # Persistent connection (RECOMMENDED)
  use_library_polling: true      # Use MeshCore library instead of CLI
  library_poll_interval_sec: 1.0 # Polling frequency
  
  # Batch processing (v2.0 NEW)
  batch_enabled: true            # Aggregate rapid messages into one AI call
  batch_min_messages: 3          # Min messages to trigger batch mode
  batch_time_window_sec: 2.0     # Time window for batching
```

### AI Settings
```yaml
ai:
  api_url: "http://127.0.0.1:8080/api/chat/completions"
  api_key: "sk-..."              # OpenWebUI API key
  model_id: "mistral-nemolatest-tuds-nlkl"
  memory_limit: 20               # Conversation history length
  streaming: false               # Use streaming API (beta)
  
  # OpenWebUI Auto-Start (v2.0)
  openwebui_autostart: true      # Auto-start OpenWebUI if not running
  openwebui_data_dir: "E:\\..."  # OpenWebUI data directory
  openwebui_startup_timeout: 180 # Wait time for model loading (seconds)
  
  # Webhook (optional)
  webui_webhook_url: "http://..."
  webui_webhook_disable_on_405: true  # Auto-disable on HTTP 405
```

### System Settings
```yaml
system:
  log_level: "INFO"              # DEBUG, INFO, WARNING, ERROR
  health_enabled: true           # Enable /status dashboard
  health_host: "127.0.0.1"
  health_port: 8766              # Dashboard port
  health_log_limit: 60           # Max messages in message stream
```

---

## Special Commands

The bot recognizes special commands sent as PRIV messages:

### `/clear` - Clear Conversation History

**Usage**: Send `/clear` as a PRIV message to the bot

**Effect**:
- Immediately clears all conversation history from bot's memory
- **ALSO clears OpenWebUI backend chat history** (web UI storage)
- Does not call AI API (instant response)
- Useful when AI gets confused or context becomes too long

**What gets cleared**:
1. **Bot memory** (`self.memory` list) - ensures next AI call has no context
2. **OpenWebUI backend** (via `DELETE /api/v1/chats/`) - removes chat history from web UI

**Response**:
```
✅ Conversation history cleared. Starting fresh!
```

**Example Scenario**:
1. You've had a long conversation with the bot
2. AI starts giving irrelevant responses or gets confused
3. Send: `/clear`
4. Bot responds instantly with confirmation
5. Bot clears its local memory + OpenWebUI web UI history
6. Next message starts fresh without previous context

**Technical Details**:
- Clears the `memory` list in `call_ai()` function
- Sends `DELETE /api/v1/chats/` to OpenWebUI backend (removes web UI history)
- No AI call made, no rate limiting applied
- Previous context completely removed (not trimmed)
- Message logged but not added to memory
- OpenWebUI chat clear is non-critical (fails gracefully if unavailable)

**Note**: The `/api/chat/completions` endpoint used by the bot is **stateless** - it has no server-side session. The main context reset happens via `self.memory.clear()`. The OpenWebUI backend clear is an optional bonus that removes chat history from the web UI.

---

## Signal Metadata & Network Context

The bot automatically extracts and provides **signal quality and routing information** to the AI without treating it as a user message. This allows the AI to understand the technical context of each message.

### What Metadata is Captured?

When a PRIV message is received, the bot extracts:

1. **RSSI (Received Signal Strength Indicator)**
   - Range: -120 dBm (very weak) to -30 dBm (very strong)
   - Quality classification:
     - `-50 dBm` or better: **excellent**
     - `-50 to -70 dBm`: **good**
     - `-70 to -85 dBm`: **moderate**
     - Below `-85 dBm`: **weak**

2. **SNR (Signal-to-Noise Ratio)**
   - Measured in dB
   - Higher = clearer signal

3. **Hop Count (Network Routing)**
   - `hop_start`: Maximum hops allowed
   - `hop_count`: Remaining hops
   - Calculated hops traveled: `hop_start - hop_count`
   - Example: "Network route: 2 hops / max 5"

### How is it Provided to the AI?

The metadata is injected as a **system message** at the start of the conversation context:

```
[Metadata - Do not treat this as a user message, just acknowledge
Signal strength: -78 dBm (good); SNR: 12 dB; Network route: 2 hops / max 5. 
Only refer to these if the user asks about them.]
```

**Key Principles**:
- ✅ **NOT treated as user input** - System role, not user role
- ✅ **AI context only** - AI knows about signal quality but won't mention it unless asked
- ✅ **Transparent logging** - Metadata logged in debug mode
- ✅ **Graceful fallback** - If metadata unavailable, AI works normally

### Example Interaction

**User sends**: "Can you hear my messages well?"

**AI receives**:
1. System message: `[Metadata... Signal strength: -92 dBm (weak); Network route: 3 hops / max 5]`
2. User message: "Can you hear my messages well?"

**AI responds**: "The signal strength is currently weak (-92 dBm), and your message traveled through 3 hops. I recommend getting closer to the network if possible."

### Technical Implementation

```python
# Metadata extraction from MeshCore message object
metadata = {
    'rssi': msg_obj.get('rssi'),           # e.g., -78
    'snr': msg_obj.get('snr'),             # e.g., 12
    'hop_count': msg_obj.get('hop_count'), # e.g., 3
    'hop_start': msg_obj.get('hop_start')  # e.g., 5
}

# Format for AI system message
def _format_metadata_for_ai(metadata):
    # Returns Hungarian-language system message
    # Empty string if no metadata available
```

**Debug Logging**:
```log
INFO:AutoReply:✉️  QUEUED: Incoming PRIV from [Enomee]
DEBUG:AutoReply:      Metadata: {'rssi': -78, 'snr': 12, 'hop_count': 3, 'hop_start': 5}
DEBUG:AutoReply:      Text: Can you hear my messages well?...
```

---

## Logging & Debugging

### Enable Debug Mode

1. Open [lara_config.yaml](lara_config.yaml)
2. Set `debug_auto_reply: true`
3. Re-run the bot

**Debug Output Examples**:
```log
DEBUG:AutoReply:RAW: {"type": "PRIV", "pubkey_prefix": "e7c354a913b", "text": "Hello bot"}
DEBUG:urllib3.connectionpool:http://127.0.0.1:8080 "POST /api/chat/completions HTTP/1.1" 200 300
INFO:AutoReply:Sending PRIV chunk 1/2
INFO:AutoReply:PRIV reply sent: True
```

### Log Files

- `auto_reply_a.log` — Node A (COM4) monitoring logs
- `auto_reply_b.log` — Node B (COM6) monitoring logs
- `auto_reply_b_fresh.log` — Fresh node B run (test evidence)

---

## Testing Scenarios

### Scenario 1: Single Outgoing PRIV
```powershell
# Terminal 1: Run node_b bot
.venv\Scripts\python.exe auto_reply_priv.py

# Terminal 2: Send PRIV from node_a
.venv\Scripts\python.exe send_only_test.py

# Expected: Node_b bot receives, processes, and responds
```

### Scenario 2: Bi-Directional Conversation
```powershell
# Terminal 1: Run node_b bot
.venv\Scripts\python.exe auto_reply_priv.py

# Terminal 2: Run node_a bot (in another terminal with different Python venv)
# First, switch config to node_a:
# - Set node_a.active_instance: true
# - Set node_b.active_instance: false
# Then: .venv\Scripts\python.exe auto_reply_priv.py

# Terminal 3: Send PRIV from node_a
.venv\Scripts\python.exe send_only_test.py

# Expected: Node_b receives, responds; node_a receives node_b's response (circular)
```

---

## Troubleshooting

### Bot Not Detecting PRIV Messages

1. **Check meshcore-cli availability**:
   ```powershell
   meshcore-cli --help
   ```

2. **Verify port configuration** in [lara_config.yaml](lara_config.yaml):
   ```yaml
   nodes:
     node_a:
       port: "COM4"  # Must match actual serial port
   ```

3. **Check bot startup logs** (enable `debug_auto_reply: true`)

### API Call Failures

1. **Verify OpenWebUI is running**:
   ```powershell
   curl http://127.0.0.1:8080/api/chat/completions
   ```

2. **Check API credentials** in [lara_config.yaml](lara_config.yaml):
   ```yaml
   ai:
     api_url: "http://127.0.0.1:8080/api/chat/completions"
     api_key: "eyJ..."  # Must be valid
   ```

3. **Check model availability**:
   ```yaml
   ai:
     model_id: "mistral-nemolatest-tuds-nlkl"  # Verify this model exists in OpenWebUI
   ```

### PORT BUSY / PERMISSION ERRORS

1. **Ensure webapp is closed** (closes COM port lock)
2. **Check for zombie processes**:
   ```powershell
   Get-Process python | Stop-Process -Force -ErrorAction Ignore
   ```
3. **Restart meshcore-cli**:
   ```powershell
   Stop-Process -Name meshcore-cli -Force -ErrorAction Ignore
   Start-Sleep -Seconds 2
   ```

---

## Advanced: Running Both Nodes Simultaneously

**Current Limitation**: Both nodes cannot run simultaneously due to shared COM ports in a single process.

**Workaround Options**:

1. **Separate Python processes** (in different terminal windows with separate Python environments)
2. **Virtual COM port emulation** (setup COM port pairs with tools like VirtualSerialPort)
3. **Async pooling** (future enhancement: use `multiprocessing` to run both in one process)

---

## Performance & Monitoring

### Expected Performance

- **Detection latency**: < 1 second (from PRIV arrival to bot detection)
- **AI response time**: 1–2 seconds (OpenWebUI processing)
- **Send latency**: < 500ms (meshcore library send)
- **Total latency**: 2–3.5 seconds (detection + AI + send)

### System Resources

- **Memory**: ~40–60 MB per bot process
- **CPU**: Minimal when idle, brief spike during API calls
- **Disk**: Optional debug logs (~3 KB per log file)

---

## Files Overview

| File | Purpose |
|------|---------|
| [auto_reply_priv.py](auto_reply_priv.py) | Main bot script (production-ready) |
| [lara_config.yaml](lara_config.yaml) | Configuration file (bot behavior, AI, nodes) |
| [send_only_test.py](send_only_test.py) | Test PRIV sender (doesn't read inbox) |
| [AUTO_REPLY_TEST_SUMMARY.md](AUTO_REPLY_TEST_SUMMARY.md) | Test evidence & verification |

---

## Support & Next Steps

1. **For production deployment**: Run bot in a systemd service or Windows scheduled task
2. **For monitoring**: Set up log aggregation (ELK, Splunk, etc.)
3. **For advanced features**: Extend `call_ai()` method for custom prompt tuning
4. **For persistence**: Add database backend for conversation history

---

**Last Updated**: Test completion timestamp
**Status**: ✅ Production-Ready
