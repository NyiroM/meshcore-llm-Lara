# Configuration Reference

This file describes the configuration options used by `lara_config.example.yaml`.

## Main sections

### `radio`
- `port`: the serial/COM port for the MeshCore device.
- `baud`: serial baud rate, typically `115200`.
- `room_name`: the MeshCore room name or identifier.
- `node_name`: friendly node name used for logging.
- `room_key`: shared room key for the MeshCore session.

### `nodes`
Defines the local bot node and the remote node used for test or reply routing.
- `node_a`: the local bot node.
  - `name`: node label.
  - `port`: COM port for the local device.
  - `pubkey`: public key for this node.
  - `active_instance`: set to `true` for the active bot node.
- `node_b`: the remote or peer node.
  - `name`: peer node label.
  - `port`: port used by the peer node.
  - `pubkey`: peer public key.

### `node_test`
Optional test configuration that can be used by development scripts or integration checks:
- `timeout_seconds`: how long to wait for a response.
- `message`: example test prompt.
- `direction`: message direction for test traffic.
- `allow_public_forwarding`: whether public forwarding is permitted.
- `allow_reverse_direction`: enable reply capability in the opposite direction.

### `ai`
AI engine and OpenWebUI integration settings:
- `api_url`: OpenWebUI API endpoint.
- `api_key`: secret authentication token for OpenWebUI.
- `model_id`: model name or identifier.
- `memory_limit`: number of message pairs to keep in context.
- `streaming`: whether to use streamed responses.
- `openwebui_autostart`: whether Lara should attempt to start OpenWebUI automatically.
- `openwebui_data_dir`: path to OpenWebUI model/data directory.
- `openwebui_ollama_url`: internal Ollama API URL, if used.
- `openwebui_cors_allow_origin`: CORS origin for OpenWebUI.
- `openwebui_user_agent`: HTTP User-Agent header for requests.
- `openwebui_python`: Python version used to launch OpenWebUI.
- `openwebui_log_file`: filename for OpenWebUI logs.
- `openwebui_startup_timeout`: seconds to wait while OpenWebUI starts.
- `webui_webhook_url`: optional webhook URL for pushing messages.
- `webui_webhook_disable_on_405`: disable webhook support on HTTP 405 responses.

### `bot_behavior`
Controls how Lara processes incoming messages and replies:
- `active`: enable the bot.
- `reply_to_all`: reply to every incoming PRIV message.
- `chunk_chars`: maximum characters per message chunk.
- `max_chunks`: maximum number of chunks per response.
- `debug_auto_reply`: enable debug reply behavior.
- `simulate_metadata`: add synthetic RSSI/SNR/hop metadata for tests.
- `allow_self_processing`: allow the bot to process its own messages.
- `circular_max_iterations`: loop limit for circular replies.
- `use_library_polling`: use persistent serial port polling.
- `library_poll_interval_sec`: polling interval.
- `monitor_restart_min_interval_sec`: minimum restart interval for monitoring.
- `batch_enabled`: enable batching of rapid messages.
- `batch_min_messages`: minimum messages required to batch.
- `batch_time_window_sec`: batching time window.

### `network`
- `ws_port`: WebSocket port used by the bot for optional network interfaces.

### `system`
- `log_level`: logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`).
- `enable_file_logging`: rotate logs into `lara_bot.log`.
- `health_enabled`: enable the health endpoint.
- `health_host`: host for the health server.
- `health_port`: port for the health endpoint.

## Usage

Copy `lara_config.example.yaml` to `lara_config.yaml`, then update the placeholders with your device-specific values.

Do not commit `lara_config.yaml` if it contains secrets or local paths.
