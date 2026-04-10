# meshcore-llm-Lara

[![CI](https://github.com/ZionBurns/meshcore-llm-Lara/actions/workflows/python-app.yml/badge.svg)](https://github.com/ZionBurns/meshcore-llm-Lara/actions/workflows/python-app.yml) [![Python Version](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org) [![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

AI-powered MeshCore message bot with OpenWebUI integration.

## Project Goal

This project provides a command-line interface around a MeshCore client node to automate and manage message replies using AI. "Lara" acts as a bridge between a USB-connected MeshCore device and an OpenWebUI-powered language model, enabling fast, contextual, and chat-like automation for encrypted mesh messages.

## What is MeshCore?

MeshCore is a mesh networking client platform designed for peer-to-peer encrypted communication over wireless mesh links. No internet or GSM network required. A MeshCore node can route messages across a network of devices, maintain secure channels, and deliver messages as encrypted private packets. Check out https://meshcore.co.uk/
This repository targets the MeshCore client mode, where a local node is connected to the host PC over USB and controlled through serial/COM commands.

## Key Concepts

- **MeshCore client node**: a hardware device running MeshCore firmware that connects via USB to your PC.
- **PRIV messages**: private encrypted mesh messages sent between nodes.
- **OpenWebUI**: a local AI interface used for generating response text.
- **Lara**: the bot logic that receives incoming PRIV messages, generates answers, and sends replies back through the MeshCore node.

## Overview

This repository contains the Lara CLI interface for MeshCore, including an AI-driven PRIV message auto-reply bot that integrates with OpenWebUI.

## Features

- ✅ Auto-Reply to PRIV messages with AI-generated responses
- ✅ Persistent serial/COM connection with MeshCore
- ✅ Health monitoring dashboard at `http://127.0.0.1:8766/status`
- ✅ Graceful shutdown with metrics saved on exit
- ✅ Auto-reconnect for COM port and OpenWebUI failures
- ✅ Batch processing for rapid message bursts
- ✅ Automatic message chunking for long responses
- ✅ Special `/clear` command to reset conversation history
- ✅ Signal metadata injection: RSSI, SNR, hop count context

## Requirements

- Python 3.11+
- `meshcore-cli` available on PATH or library mode enabled
- A MeshCore client node connected to the PC via USB
- OpenWebUI installed or configured as a running instance
- The MeshCore node must be reachable over serial/COM from the host machine

## Setup

1. Create and activate a virtual environment:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

2. Install dependencies:
   ```powershell
   pip install -r requirements.txt
   ```
   Optional: install the package locally for command-line execution:
   ```powershell
   pip install -e .
   ```

3. Configure `lara_config.yaml`:
   - `radio.port` - your MeshCore COM port (default: COM6)
   - `ai.api_key` - OpenWebUI API key or token
   - `ai.model_id` - model name (for example `mistral-nemolatest-tuds-nlkl`)
   - `nodes.node_a.pubkey` and `nodes.node_b.pubkey` - device public keys

> During testing, this project was validated using the `gemma4` model together with RAG handling. In principle, any AI model that Ollama supports through OpenWebUI can be used.

## Development and testing

Install development dependencies:
```powershell
pip install -r requirements-dev.txt
```

Run the test suite:
```powershell
pytest -q
```

Current unit tests include checks for:
- `check_port_available()` success when a COM port opens cleanly
- `check_port_available()` failure when serial access raises an exception
- `find_available_ports()` returning detected ports and prioritizing the preferred port
- OpenWebUI health URL generation with default settings
- OpenWebUI health URL normalization when a custom API URL is configured
- `_is_openwebui_up()` reporting false when the health endpoint is unhealthy
- `_wait_for_openwebui(timeout=0)` returning false when OpenWebUI is unavailable
- `_start_openwebui()` avoiding a process launch when the autostart binary is not found

## Key repository files

Below are the main project files, ordered by importance for running and understanding Lara.

1. `auto_reply_priv.py` — the main application code and entry point. It contains the bot logic for reading incoming MeshCore PRIV messages, calling OpenWebUI, and sending replies back through the USB-connected MeshCore node.
2. `lara_config.yaml` — runtime configuration for the MeshCore node, serial/COM settings, AI model parameters, node public keys, and behavior options.
3. `requirements.txt` — pinned Python dependencies required to install and run the project in a clean environment.
4. `requirements-dev.txt` — developer dependencies for tests and CI.
5. `pyproject.toml` — package metadata for easy install and distribution.
6. `start_lara.bat` / `start_lara.ps1` — convenience startup scripts for Windows.
7. `AUTO_REPLY_USAGE_GUIDE.md` — detailed usage and configuration documentation for all available options.
8. `.gitignore` — excludes local files, generated logs, the virtual environment, and other non-public runtime artifacts from the repository.
9. `README.md` — this file, which explains the project goal, setup, running instructions, and troubleshooting.
10. `CONTRIBUTING.md` / `CODE_OF_CONDUCT.md` — contribution guidelines and expected project conduct.
11. `LICENSE` — repository license and permissions.

Detailed analysis, test reports, and historical notes are now stored in `docs/reports/`.

See `docs/README.md` for the full documentation structure and deeper project references.

### Recommended
```powershell
start_lara.bat
```

### PowerShell
```powershell
.\start_lara.ps1
```

### Manual
```powershell
python auto_reply_priv.py
```

## Configuration highlights

```yaml
bot_behavior:
  use_library_polling: true
  chunk_chars: 145
  batch_enabled: true
  batch_min_messages: 3
  batch_time_window_sec: 2.0

system:
  health_enabled: true
  health_port: 8766
```

See `AUTO_REPLY_USAGE_GUIDE.md` for full configuration details.

## Special commands

- `/clear` - resets the conversation history and starts fresh

## Monitoring

- Status dashboard: `http://127.0.0.1:8766/status`
- JSON API: `http://127.0.0.1:8766/status?format=json`

## Troubleshooting

- If the COM port is not available, close other apps using it and reconnect the device.
- Verify OpenWebUI is running and reachable.
