# Architecture Overview

This document summarizes the main structure of the `meshcore-llm-Lara` project.

## Core components

- `auto_reply_priv.py`
  - Main application entry point.
  - Reads config from `lara_config.yaml`.
  - Manages the MeshCore serial/COM connection.
  - Integrates with OpenWebUI for AI-generated PRIV replies.
  - Handles health monitoring, logging, and graceful shutdown.

- `lara_config.example.yaml`
  - Example runtime configuration.
  - Contains placeholders for COM ports, node keys, AI settings, and behavior options.

- `requirements.txt`
  - Runtime dependencies required to run the bot.

- `requirements-dev.txt`
  - Development and test dependencies.

## Runtime flow

1. The bot starts and loads configuration.
2. It checks serial port availability and connects to MeshCore.
3. Incoming PRIV messages are monitored.
4. The bot calls OpenWebUI and generates AI responses.
5. Responses are sent back to the sender through the MeshCore node.
6. Optional health endpoint and logging keep runtime visibility.

## Testing and reports

- `tests/` — unit tests for config loading and OpenWebUI integration logic.
- `docs/reports/` — archived analysis and report files.

## Documentation structure

The `docs/` folder contains project documentation, including:
- `docs/README.md`
- `docs/configuration.md`
- `docs/testing.md`
- `docs/architecture.md`
- `docs/reports/`
- `docs/legacy/`

## Notes

For user-facing usage instructions, the root-level `README.md` and `AUTO_REPLY_USAGE_GUIDE.md` remain the primary references.
