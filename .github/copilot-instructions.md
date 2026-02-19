# Copilot instructions — Lara CLI Interface

Short, actionable guidance for AI coding agents working in this repository.

## Big picture
- This repository is a small bridge between MeshCore `meshcore-cli` and an AI service. Key roles:
  - `lara_main.py`: Windows-safe, byte-aware monitor + AI bridge (preferred entrypoint for interactive operation).
  - `lara_cli_bridge.py`: earlier bridge implementation with similar responsibilities (monitor, AI, interactive send).
  - `meshcore_send.py`: library-based sender using the Python `meshcore` package (async code, useful for direct library calls).
  - `serial_proxy_logger.py`: serial proxy / hex logger used for debugging physical COM connections.

## Critical files to inspect
- `lara_config.yaml` — central configuration (radio, ai, bot_behavior, system). Always consult it before changing behavior.
- `lara_main.py` / `lara_cli_bridge.py` — implement monitor loop, AI call (`requests.post` to `ai.api_url`) and interactive `meshcore-cli` workflows.
- `meshcore_send.py` — shows the preferred usage of the `meshcore` Python library (async/await); useful examples of resolving room adv_name → pubkey and `set_channel` usage.
- `test_send.py`, `test.py` — small ad-hoc invocation examples for CLI usage.

## What to know about runtime & external deps
- `meshcore-cli` must be installed and available on `PATH`. The code calls `shutil.which('meshcore-cli')` and fails gracefully if missing.
- Python packages used but not listed in a lock file: `pyyaml`, `requests`, `meshcore` (optional), `pyserial` (for `serial_proxy_logger`). Install with: `pip install pyyaml requests meshcore pyserial`.
- Network: AI integration is HTTP-based. `lara_config.yaml` uses `ai.api_url` and `ai.api_key`; payloads are OpenAI-like (`messages`) but code handles alternate response shapes.

## Project-specific patterns & gotchas
- Binary/interactive CLI pattern: interactive `meshcore-cli` sends are performed in binary pipes (stdin/stdout) — scripts stop the monitor process before starting interactive CLI and restart it afterwards. See `send_to_room_interactive` / `send_to_room` in `lara_cli_bridge.py` and `lara_main.py`.
- UTF-8-aware byte chunking: messages are split by UTF-8 byte length (not characters) using `_byte_chunks` / `_byte_chunk_text`. Preserve this when changing chunk logic.
- Two similar bridge implementations exist; prefer editing `lara_main.py` for Windows-specific fixes and `lara_cli_bridge.py` for the original logic. Keep changes synchronized if you modify shared behavior.
- AI memory: both bridge files maintain an in-memory `messages` list limited by `memory_limit` (configured in `lara_config.yaml`). Code appends roles `user` / `assistant`; follow this format when changing AI integration.

## Common developer workflows (examples)
- Run the bridge (ensure `meshcore-cli` in PATH and `lara_config.yaml` present):
  - `python lara_main.py`
  - or `python lara_cli_bridge.py`
- Send one-off message via the library-backed script:
  - `python meshcore_send.py -p COM6 --room "ROOM_OR_PUBKEY" -m "Hello"`
- Debug serial link with proxy logger:
  - `python serial_proxy_logger.py --phys COM6 --virt COM7 --log serial.log`

## Editing guidance and examples
- Config-first: when changing behavior, prefer adding config keys to `lara_config.yaml` and read them in the scripts: e.g. change chunk size via `bot_behavior.chunk_size` or `bot_behavior.chunk_bytes`.
- If adding features that interact with the hardware CLI, follow the existing flow: stop monitor → start interactive `meshcore-cli -s <port>` → wait for prompt → write `to <room>` and `send <chunk>` lines → `quit` → restart monitor.
- For async library work, mirror patterns in `meshcore_send.py` (use `MeshCore.create_serial`, `await mesh.commands.*`, and `await mesh.disconnect()`).

## Tests & expectations
- There are no formal unit tests; `test_send.py` and `test.py` are examples and quick sanity scripts. Run them to reproduce simple behaviors.

## When in doubt
- Check `lara_config.yaml` for runtime values. Inspect both `lara_main.py` and `lara_cli_bridge.py` to understand subtle behavioral differences (Windows byte handling vs. original bridge). Search for `_byte_chunk` or `meshcore-cli` usage when changing send/monitor logic.

---
If any section is unclear or you want me to expand examples (e.g., adding a `requirements.txt` or automated start script), tell me which part to expand.
