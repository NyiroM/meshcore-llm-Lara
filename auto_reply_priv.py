#!/usr/bin/env python3
"""
auto_reply_priv.py

Continuous PRIV-only auto-reply bot:
- Monitors incoming messages on the active node radio via meshcore-cli JSON monitor.
- Sends AI responses back as PRIV to the sender.
- Never posts to public rooms.
"""

import asyncio
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import re
import select
import shutil
import signal
import subprocess
import sys
import threading
import time
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from typing import Optional

import requests
import yaml
import serial  # For COM port availability check

try:
    from meshcore import MeshCore, EventType
except ImportError:
    print("ERROR: meshcore library not found. Install: pip install meshcore")
    sys.exit(1)

def force_utf8_console_output() -> None:
    """Force UTF-8 encoding for the Windows console when running the bot."""
    if sys.platform != "win32":
        return

    import io
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    os.environ["PYTHONIOENCODING"] = "utf-8"

CONFIG_PATH = "lara_config.yaml"
COM_BUSY_HINT = "COM port appears busy. Please close the MeshCore web app (or any app using the port) and retry."


def setup_logging(log_level: str = "INFO", enable_file_logging: bool = True) -> logging.Logger:
    """
    Configure logging with rotation support.

    Uses RotatingFileHandler to prevent log files from growing infinitely.
    Max file size: 5 MB, keeps 3 backup files (total ~20 MB max).
    """
    logger = logging.getLogger("AutoReply")
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()

    # Console handler (always enabled)
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.DEBUG)
    console_formatter = logging.Formatter("%(levelname)s:%(name)s:%(message)s")
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # Rotating file handler (optional)
    if enable_file_logging:
        log_file = "lara_bot.log"
        try:
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=5 * 1024 * 1024,  # 5 MB
                backupCount=3,  # Keep 3 old log files (lara_bot.log.1, .2, .3)
                encoding="utf-8"
            )
            file_handler.setLevel(logging.DEBUG)
            file_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")
            file_handler.setFormatter(file_formatter)
            logger.addHandler(file_handler)
            logger.info(f"📝 Log rotation enabled: {log_file} (max 5MB × 4 files)")
        except Exception as e:
            logger.warning(f"Could not setup file logging: {e}")

    return logger


# Initialize logger (will be properly configured in main())
logger = logging.getLogger("AutoReply")


def load_config(path: str = CONFIG_PATH) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        sys.exit(1)


def validate_config(cfg: dict) -> None:
    errors = []

    ai_cfg = cfg.get("ai", {})
    if not str(ai_cfg.get("api_url", "")).strip():
        errors.append("Missing ai.api_url")
    if not str(ai_cfg.get("api_key", "")).strip():
        errors.append("Missing ai.api_key")
    if not str(ai_cfg.get("model_id", "")).strip():
        errors.append("Missing ai.model_id")

    radio_cfg = cfg.get("radio", {})
    nodes_cfg = cfg.get("nodes", {})
    has_port = bool(str(radio_cfg.get("port", "")).strip())
    if not has_port and isinstance(nodes_cfg, dict):
        for _, node_data in nodes_cfg.items():
            if isinstance(node_data, dict) and node_data.get("active_instance") and node_data.get("port"):
                has_port = True
                break
    if not has_port:
        errors.append("Missing radio.port (or nodes.*.port for active_instance)")

    bot_cfg = cfg.get("bot_behavior", {})
    if "chunk_chars" in bot_cfg:
        try:
            if int(bot_cfg.get("chunk_chars")) <= 0:
                errors.append("bot_behavior.chunk_chars must be > 0")
        except Exception:
            errors.append("bot_behavior.chunk_chars must be an integer")
    if "max_chunks" in bot_cfg:
        try:
            if int(bot_cfg.get("max_chunks")) <= 0:
                errors.append("bot_behavior.max_chunks must be > 0")
        except Exception:
            errors.append("bot_behavior.max_chunks must be an integer")

    system_cfg = cfg.get("system", {})
    if "health_port" in system_cfg:
        try:
            port = int(system_cfg.get("health_port"))
            if port < 1 or port > 65535:
                errors.append("system.health_port must be between 1 and 65535")
        except Exception:
            errors.append("system.health_port must be an integer")

    if errors:
        for err in errors:
            logger.error(f"Config error: {err}")
        sys.exit(1)


def check_port_available(port: str) -> bool:
    """
    Check if a serial port is available and can be opened.
    Returns True if port exists and is accessible, False otherwise.
    """
    try:
        with serial.Serial(port, timeout=1) as _:
            logger.info(f"✅ COM port {port} is available")
            return True
    except serial.SerialException as e:
        logger.error(f"❌ COM port {port} is NOT available: {e}")
        logger.error("   Please check:")
        logger.error("   - Is the device connected?")
        logger.error("   - Is another program using the port?")
        logger.error("   - Is the port name correct in lara_config.yaml?")
        return False


def find_available_ports(preferred_port: str = None) -> list:
    """
    Scan for available serial ports.
    Returns list of available port names, with preferred_port first if available.
    """
    try:
        from serial.tools import list_ports
        available = [port.device for port in list_ports.comports()]

        if not available:
            logger.warning("⚠️ No COM ports detected")
            return []

        # Put preferred port first if it exists
        if preferred_port and preferred_port in available:
            available.remove(preferred_port)
            available.insert(0, preferred_port)

        logger.info(f"🔍 Available COM ports: {', '.join(available)}")
        return available
    except Exception as e:
        logger.debug(f"Port scanning error: {e}")
        return []


def _sanitize_text(s: str) -> str:
    if s is None:
        return ""
    s = str(s).strip()  # Remove leading/trailing whitespace FIRST
    s = s.replace("\r", " ").replace("\n", " ")
    s = re.sub(r"[^\x20-\x7E\u00A0-\uFFFF]", "?", s)
    return s.strip()  # Clean up any new leading/trailing spaces from replacements


def _chunk_text_with_numbering(text: str, max_chars_per_chunk: int = 145, max_chunks: int = 3) -> list[str]:
    """
    Split text into numbered chunks for mesh PRIV messages.

    Rules:
    - If text <= 150 chars: return as-is (single message, no numbering)
    - If text > 150 chars: split into chunks (default 145 chars, leaves 5 for " X/Y")
    - Maximum chunks allowed (default 3)
    - If text needs more chunks, the last ends with " ?/N" and rest is discarded

    Examples:
    - 140 chars → ["full text"]
    - 300 chars → ["chunk1 1/3", "chunk2 2/3", "chunk3 3/3"]
    - 600 chars → ["chunk1 1/3", "chunk2 2/3", "chunk3 ?/3"]  (rest discarded)
    """
    if not text:
        return []

    if len(text) <= 150:
        return [text]

    # Split into chunks
    chunks = []
    pos = 0
    while pos < len(text):
        chunk = text[pos:pos + max_chars_per_chunk]
        chunks.append(chunk)
        pos += max_chars_per_chunk

    # Check if truncation needed
    has_more = len(chunks) > max_chunks
    if has_more:
        chunks = chunks[:max_chunks]

    total_chunks = len(chunks)

    # Add numbering
    numbered_chunks = []
    for i, chunk in enumerate(chunks, 1):
        if i == max_chunks and has_more:
            # Last chunk and there's truncated text
            suffix = f" ?/{max_chunks}"
        else:
            suffix = f" {i}/{total_chunks}"
        numbered_chunks.append(f"{chunk}{suffix}")

    return numbered_chunks


def _looks_like_com_busy(output: str) -> bool:
    if not output:
        return False
    needles = [
        "Access is denied",
        "PermissionError",
        "could not open port",
        "The system cannot find the file specified",
        "Device or resource busy",
        "WinError 5",
    ]
    return any(token in output for token in needles)


class AutoReplyBot:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.radio_cfg = cfg.get("radio", {})
        self.ai_cfg = cfg.get("ai", {})
        self.bot_cfg = cfg.get("bot_behavior", {})
        self.running = True
        self.memory: list[dict] = []
        self.monitor_proc: Optional[subprocess.Popen] = None
        self._send_lock = threading.Lock()
        self._message_worker_thread: Optional[threading.Thread] = None
        self._message_queue: list = []
        self._openwebui_proc: Optional[subprocess.Popen] = None
        self._openwebui_log_handle = None
        self._openwebui_output_thread: Optional[threading.Thread] = None
        self._health_server: Optional[ThreadingHTTPServer] = None
        self._health_thread: Optional[threading.Thread] = None
        self._webhook_disabled = False
        self.webhook_disable_on_405 = bool(self.ai_cfg.get("webui_webhook_disable_on_405", True))
        self._last_monitor_line_time = time.time()
        self._last_seen_messages: dict[str, float] = {}
        self._last_seen_messages_lock = threading.Lock()  # Lock for thread-safe access
        self._last_monitor_restart_time = 0.0
        self._next_monitor_start_time = 0.0
        self._message_log: list[dict] = []
        self._message_log_lock = threading.Lock()
        self._message_log_limit = int(self.cfg.get("system", {}).get("health_log_limit", 60))

        # NEW: Queue for monitor lines (reader thread puts raw lines here)
        self._monitor_line_queue: list = []
        self._monitor_reader_thread: Optional[threading.Thread] = None

        # NEW: Persistent mesh connection for library mode
        self._persistent_mesh = None
        self._use_library_mode = False

        # NEW: Deduplication cleanup thread
        self._dedup_cleanup_thread: Optional[threading.Thread] = None
        self._start_dedup_cleanup_thread()

        # NEW: Rate Limiting for AI calls
        self._last_ai_call_time = 0.0
        self.min_ai_interval_sec = float(self.bot_cfg.get("min_ai_interval_sec", 3.0))

        # NEW: Metrics/Monitoring
        self._metrics = {
            "messages_received": 0,
            "messages_processed": 0,
            "ai_calls_success": 0,
            "ai_calls_failed": 0,
            "ai_calls_fallback": 0,
            "total_ai_latency_sec": 0.0,
            "last_ai_latency_sec": 0.0,
            "queue_peak_size": 0,
            "start_time": time.time(),
        }
        self._metrics_lock = threading.Lock()
        self._last_metrics_log_time = time.time()

        self.default_port = str(self.radio_cfg.get("port", "COM6"))
        self.node_name = str(self.radio_cfg.get("node_name", "Enomee"))

        # For single-radio mode: send_port == recv_port (default)
        # For dual-radio mode: can be configured differently via send_port/recv_port in config
        self.send_port = self.default_port
        self.recv_port = self.default_port

        nodes = cfg.get("nodes", {})
        for node_key, node_data in nodes.items():
            if isinstance(node_data, dict) and node_data.get("active_instance", False):
                self.default_port = str(node_data.get("port", self.default_port))
                self.node_name = str(node_data.get("name", self.node_name))
                # Support for dual-radio (separate send/recv ports) if configured in nodes
                send_ovr = node_data.get("send_port")
                recv_ovr = node_data.get("recv_port")
                if send_ovr:
                    self.send_port = str(send_ovr)
                else:
                    self.send_port = self.default_port
                if recv_ovr:
                    self.recv_port = str(recv_ovr)
                else:
                    self.recv_port = self.default_port
                logger.info(
                    f"Active instance: node '{node_key}' ({self.node_name}) on port {self.default_port} (send: {self.send_port}, recv: {self.recv_port})")
                break

        self.chunk_chars = int(self.bot_cfg.get("chunk_chars", 145))
        self.max_chunks = int(self.bot_cfg.get("max_chunks", 3))
        self.debug_mode = bool(self.bot_cfg.get("debug_auto_reply", False))
        self.simulate_metadata = bool(self.bot_cfg.get("simulate_metadata", False))
        self.use_streaming = bool(self.ai_cfg.get("streaming", True))
        if self.debug_mode:
            logging.getLogger().setLevel(logging.DEBUG)
        if self.simulate_metadata:
            logger.warning("🧪 METADATA SIMULATION MODE ENABLED - Random RSSI/SNR/hops will be added to messages")

        # Graceful shutdown handlers
        try:
            signal.signal(signal.SIGINT, lambda sig, frame: self.stop())
            signal.signal(signal.SIGTERM, lambda sig, frame: self.stop())  # Added SIGTERM
        except Exception:
            pass

        # NEW: Hot-reload support via SIGHUP signal (reload config without restarting)
        try:
            signal.signal(signal.SIGHUP, lambda sig, frame: self._reload_config())
        except (AttributeError, ValueError):
            # SIGHUP not available on Windows
            pass

    def stop(self) -> None:
        logger.info("🛑 Signal received - shutting down gracefully...")
        self.running = False

        # Stop monitor processes
        self._stop_monitor()

        # Stop health server
        self._stop_health_server()

        # Wait for worker thread to finish
        if self._message_worker_thread and self._message_worker_thread.is_alive():
            logger.info("⏳ Waiting for message worker to finish...")
            self._message_worker_thread.join(timeout=5)

        # Disconnect persistent COM port connection
        if self._persistent_mesh:
            logger.info("🔌 Closing COM port connection...")
            try:
                asyncio.run(self._persistent_mesh.disconnect())
            except Exception as e:
                logger.debug(f"COM disconnect error: {e}")
            self._persistent_mesh = None

        # Stop OpenWebUI process
        if self._openwebui_proc:
            logger.info("🛑 Stopping OpenWebUI process...")
            try:
                self._openwebui_proc.terminate()
                self._openwebui_proc.wait(timeout=10)
                logger.info("✅ OpenWebUI stopped")
            except Exception as e:
                logger.warning(f"OpenWebUI stop error: {e}")
                try:
                    self._openwebui_proc.kill()  # Force kill if terminate fails
                except Exception:
                    pass

        # Close OpenWebUI log file
        if self._openwebui_log_handle:
            try:
                self._openwebui_log_handle.close()
            except Exception:
                pass

        # Save metrics to file
        self._save_metrics()

        logger.info("✅ Shutdown complete")

    def _reload_config(self) -> None:
        """
        Hot-reload configuration from YAML without restarting the bot.
        Useful for changing AI settings, debug mode, rate limiting, etc. on the fly.
        Usage: kill -HUP <pid> (or on Windows, just restart)
        """
        logger.info("🔄 HOT-RELOAD: Attempting to reload configuration...")
        try:
            new_cfg = load_config(CONFIG_PATH)

            # Reload mutable settings (don't touch serial port stuff)
            old_streaming = self.use_streaming
            self.ai_cfg = new_cfg.get("ai", {})
            self.bot_cfg = new_cfg.get("bot_behavior", {})
            self.webhook_disable_on_405 = bool(self.ai_cfg.get("webui_webhook_disable_on_405", True))
            if not self.webhook_disable_on_405:
                self._webhook_disabled = False

            # Re-read key settings
            self.use_streaming = bool(self.ai_cfg.get("streaming", True))
            self.min_ai_interval_sec = float(self.bot_cfg.get("min_ai_interval_sec", 3.0))
            new_debug = bool(self.bot_cfg.get("debug_auto_reply", False))

            # Update logger if debug mode changed
            if new_debug != self.debug_mode:
                self.debug_mode = new_debug
                if self.debug_mode:
                    logging.getLogger().setLevel(logging.DEBUG)
                    logger.info("🔧 DEBUG MODE ENABLED")
                else:
                    logging.getLogger().setLevel(logging.INFO)
                    logger.info("🔧 DEBUG MODE DISABLED")

            if self.use_streaming != old_streaming:
                logger.info(f"🔧 Streaming: {old_streaming} → {self.use_streaming}")

            logger.info(f"✅ HOT-RELOAD: Configuration reloaded successfully (rate limit: {self.min_ai_interval_sec}s)")

        except Exception as e:
            logger.error(f"❌ HOT-RELOAD FAILED: {e}")
            logger.error("Configuration remains unchanged")

    def _openwebui_health_url(self) -> str:
        api_url = str(self.ai_cfg.get("api_url", "")).strip()
        if api_url:
            parsed = urlparse(api_url)
            if parsed.scheme and parsed.netloc:
                return f"{parsed.scheme}://{parsed.netloc}/api/health"
        return "http://127.0.0.1:8080/api/health"

    def _is_openwebui_up(self) -> bool:
        url = self._openwebui_health_url()
        try:
            res = requests.get(url, timeout=2)
            return res.status_code < 500
        except Exception:
            return False

    def _start_openwebui(self) -> None:
        if not bool(self.ai_cfg.get("openwebui_autostart", False)):
            return
        if self._is_openwebui_up():
            logger.info("OpenWebUI already running.")
            return

        uvx_path = shutil.which("uvx")
        if not uvx_path:
            logger.warning("uvx not found on PATH; cannot start OpenWebUI.")
            return

        env = os.environ.copy()

        # Set proper environment variables for OpenWebUI (matching openwebui3.ps1)
        # DATA_DIR: Where the webui.db file lives
        data_dir = self.ai_cfg.get("openwebui_data_dir") or "E:\\Users\\M\\Documents\\LLM\\Doomsday_files"
        env["DATA_DIR"] = str(data_dir)

        # OLLAMA_BASE_URL: Ollama server location
        ollama_url = self.ai_cfg.get("openwebui_ollama_url") or "http://127.0.0.1:11434"
        env["OLLAMA_BASE_URL"] = str(ollama_url)

        # CORS and User Agent
        cors_origin = self.ai_cfg.get("openwebui_cors_allow_origin") or "http://localhost:8080"
        user_agent = self.ai_cfg.get("openwebui_user_agent") or "OpenWebUI-User"
        env["CORS_ALLOW_ORIGIN"] = str(cors_origin)
        env["USER_AGENT"] = str(user_agent)

        # UTF-8 encoding for Python subprocess
        env["PYTHONIOENCODING"] = "utf-8"

        # Check if webui.db exists in DATA_DIR
        webui_db_path = os.path.join(data_dir, "webui.db")
        if os.path.exists(webui_db_path):
            logger.info("✅ SUCCESS: Database found (%s)", webui_db_path)
        else:
            logger.warning("⚠️  webui.db not found: %s", webui_db_path)

        python_version = str(self.ai_cfg.get("openwebui_python", "3.11"))
        log_file = str(self.ai_cfg.get("openwebui_log_file", "openwebui.log"))

        try:
            self._openwebui_log_handle = open(log_file, "a", encoding="utf-8")
        except Exception:
            self._openwebui_log_handle = None

        cmd = [uvx_path, "--python", python_version, "open-webui", "serve"]
        logger.info("🌐 Starting OpenWebUI with DATA_DIR=%s", data_dir)
        logger.info("   Command: %s", " ".join(cmd))
        try:
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if sys.platform == "win32" else 0
            self._openwebui_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
                creationflags=creationflags,
            )
            logger.info("✅ OpenWebUI started (PID: %s)", self._openwebui_proc.pid)
            self._openwebui_output_thread = threading.Thread(
                target=self._stream_openwebui_output,
                args=(self._openwebui_proc, self._openwebui_log_handle),
                daemon=True,
            )
            self._openwebui_output_thread.start()
        except Exception as e:
            logger.error(f"Failed to start OpenWebUI: {e}")

    def _stream_openwebui_output(self, proc: subprocess.Popen, log_handle) -> None:
        """Stream OpenWebUI output to terminal and optional log file."""
        if not proc or not proc.stdout:
            return
        try:
            for line in proc.stdout:
                if not line:
                    continue
                # Print to terminal
                sys.stdout.write(line)
                sys.stdout.flush()
                # Write to log file if configured
                if log_handle:
                    try:
                        log_handle.write(line)
                        log_handle.flush()
                    except Exception:
                        pass
        except Exception:
            return

    def _wait_for_openwebui(self, timeout: int = 60) -> bool:
        """Wait for OpenWebUI to become healthy (up to timeout seconds)."""
        logger.info("⏳ Waiting for OpenWebUI to become ready (timeout: %ds)...", timeout)
        deadline = time.time() + timeout
        attempt = 0
        while time.time() < deadline:
            attempt += 1
            if self._is_openwebui_up():
                logger.info("✅ OpenWebUI is ready!")
                return True
            time.sleep(2)
            if attempt % 5 == 0:
                logger.info(f"  ... still waiting ({int(deadline - time.time())}s remaining)")
        logger.error("❌ OpenWebUI did not become ready in time")
        return False

    def _restart_openwebui(self) -> None:
        """Restart OpenWebUI process if it crashed or became unresponsive."""
        try:
            # Stop existing process
            if self._openwebui_proc:
                try:
                    self._openwebui_proc.terminate()
                    self._openwebui_proc.wait(timeout=5)
                except Exception:
                    try:
                        self._openwebui_proc.kill()
                    except Exception:
                        pass
                self._openwebui_proc = None

            # Wait a bit before restart
            time.sleep(2)

            # Start again
            self._start_openwebui()

            # Wait for it to be ready
            timeout = int(self.ai_cfg.get("openwebui_startup_timeout", 180))
            if self._wait_for_openwebui(timeout=timeout):
                logger.info("✅ OpenWebUI restarted successfully")
            else:
                logger.error("❌ OpenWebUI restart failed")
        except Exception as e:
            logger.error(f"OpenWebUI restart error: {e}")

    def _get_health_payload(self) -> dict:
        with self._metrics_lock:
            m = dict(self._metrics)
        total_calls = m.get("ai_calls_success", 0) + m.get("ai_calls_failed", 0) + m.get("ai_calls_fallback", 0)
        avg_latency = (m.get("total_ai_latency_sec", 0.0) / total_calls) if total_calls else 0.0
        uptime_sec = time.time() - m.get("start_time", time.time())
        last_monitor_age_sec = time.time() - self._last_monitor_line_time
        with self._message_log_lock:
            message_log = list(self._message_log)
        return {
            "status": "running" if self.running else "stopped",
            "uptime_sec": round(uptime_sec, 1),
            "messages_received": m.get("messages_received", 0),
            "messages_processed": m.get("messages_processed", 0),
            "queue_size": len(self._message_queue),
            "queue_peak": m.get("queue_peak_size", 0),
            "ai_calls_success": m.get("ai_calls_success", 0),
            "ai_calls_failed": m.get("ai_calls_failed", 0),
            "ai_calls_fallback": m.get("ai_calls_fallback", 0),
            "ai_avg_latency_sec": round(avg_latency, 3),
            "ai_last_latency_sec": round(m.get("last_ai_latency_sec", 0.0), 3),
            "openwebui_up": self._is_openwebui_up(),
            "webhook_disabled": self._webhook_disabled,
            "last_monitor_line_age_sec": round(last_monitor_age_sec, 1),
            "message_log": message_log,
        }

    def _append_message_log(self, direction: str, peer: str, text: str, status: str = "", metadata: dict = None) -> None:
        entry = {
            "ts": time.time(),
            "dir": direction,
            "peer": peer,
            "text": _sanitize_text(text)[:300],
            "status": status,
            "metadata": metadata if metadata else None,
        }
        with self._message_log_lock:
            self._message_log.append(entry)
            if len(self._message_log) > self._message_log_limit:
                self._message_log = self._message_log[-self._message_log_limit:]

    def _save_metrics(self) -> None:
        """Save current metrics to JSON file for post-mortem analysis."""
        try:
            metrics_file = "lara_metrics.json"
            payload = self._get_health_payload()
            with open(metrics_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            logger.info(f"💾 Metrics saved to {metrics_file}")
        except Exception as e:
            logger.warning(f"Could not save metrics: {e}")

    def _start_dedup_cleanup_thread(self) -> None:
        """Start background thread that periodically cleans up expired deduplication entries."""
        self._dedup_cleanup_thread = threading.Thread(target=self._dedup_cleanup_worker, daemon=True)
        self._dedup_cleanup_thread.start()
        logger.debug("🧹 Deduplication cleanup thread started")

    def _dedup_cleanup_worker(self) -> None:
        """
        Background worker that cleans up expired deduplication entries.
        Runs every 5 minutes to prevent memory leaks on long-running bots.
        """
        cleanup_interval = 300  # 5 minutes
        seen_ttl = float(self.bot_cfg.get("monitor_dedupe_ttl_sec", 120.0))

        while self.running:
            time.sleep(cleanup_interval)
            if not self.running:
                break

            # Clean up expired entries
            now = time.time()
            with self._last_seen_messages_lock:
                before_count = len(self._last_seen_messages)
                self._last_seen_messages = {
                    k: v for k, v in self._last_seen_messages.items()
                    if now - v < seen_ttl
                }
                after_count = len(self._last_seen_messages)
                removed = before_count - after_count

            if removed > 0:
                logger.debug(f"🧹 Dedup cleanup: removed {removed} expired entries ({after_count} remain)")

    def _render_status_html(self, payload: dict) -> str:
        status = payload.get("status", "unknown")
        openwebui_up = payload.get("openwebui_up", False)
        webhook_disabled = payload.get("webhook_disabled", False)
        messages_received = payload.get("messages_received", 0)
        messages_processed = payload.get("messages_processed", 0)
        queue_size = payload.get("queue_size", 0)
        queue_peak = payload.get("queue_peak", 0)
        uptime_sec = payload.get("uptime_sec", 0)
        uptime_min = round(uptime_sec / 60.0, 1) if uptime_sec else 0.0
        ai_ok = payload.get("ai_calls_success", 0)
        ai_fail = payload.get("ai_calls_failed", 0)
        ai_fallback = payload.get("ai_calls_fallback", 0)
        ai_latency = payload.get("ai_avg_latency_sec", 0.0)
        ai_last_latency = payload.get("ai_last_latency_sec", 0.0)
        last_monitor_age = payload.get("last_monitor_line_age_sec", 0.0)
        message_log = payload.get("message_log", [])

        status_tag = "RUNNING" if status == "running" else "STOPPED"
        openwebui_tag = "UP" if openwebui_up else "DOWN"
        webhook_tag = "DISABLED" if webhook_disabled else "ENABLED"

        chat_rows = []
        for item in message_log:
            ts = item.get("ts", 0.0)
            ts_str = time.strftime("%H:%M:%S", time.localtime(ts)) if ts else "--:--:--"
            direction = item.get("dir", "in")
            peer = html.escape(str(item.get("peer", "")))
            text = html.escape(str(item.get("text", "")))
            status = html.escape(str(item.get("status", "")))
            metadata = item.get("metadata")
            role_class = "in" if direction == "in" else "out"
            status_suffix = f" [{status}]" if status else ""

            # Format metadata badges for incoming messages
            metadata_html = ""
            if metadata and direction == "in":
                badges = []
                rssi = metadata.get('rssi')
                snr = metadata.get('snr')
                hop_count = metadata.get('hop_count')
                hop_start = metadata.get('hop_start')

                if rssi is not None:
                    # Color code based on signal strength
                    if rssi >= -50:
                        rssi_class = "signal-excellent"
                    elif rssi >= -70:
                        rssi_class = "signal-good"
                    elif rssi >= -85:
                        rssi_class = "signal-moderate"
                    else:
                        rssi_class = "signal-weak"
                    badges.append(f"<span class='badge {rssi_class}'>📡 {rssi} dBm</span>")

                if snr is not None:
                    badges.append(f"<span class='badge'>SNR {snr} dB</span>")

                if hop_count is not None and hop_start is not None:
                    hops_traveled = hop_start - hop_count
                    badges.append(f"<span class='badge'>🔀 {hops_traveled}/{hop_start} hops</span>")

                if badges:
                    metadata_html = f"<div class='metadata-badges'>{''.join(badges)}</div>"

            chat_rows.append(
                f"<div class=\"msg {role_class}\">"
                f"<div class=\"meta\"><span>{ts_str}</span><span>{peer}{status_suffix}</span></div>"
                f"{metadata_html}"
                f"<div class=\"bubble\">{text}</div>"
                f"</div>"
            )
        chat_html = "\n".join(chat_rows) if chat_rows else "<div class=\"empty\">No messages yet.</div>"

        return f"""<!doctype html>
<html lang=\"en\">
<head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>LARA Status</title>
    <style>
        :root {{
            --bg: #0b1014;
            --bg-2: #131a21;
            --ink: #e7eef5;
            --muted: #9fb1c1;
            --accent: #43d9ad;
            --warn: #f5b04c;
            --danger: #ff5d6c;
            --card: #111820;
            --card-2: #0f161d;
            --border: #1c2732;
        }}
        * {{ box-sizing: border-box; }}
        body {{
            margin: 0;
            font-family: "Georgia", "Times New Roman", serif;
            color: var(--ink);
            background:
                radial-gradient(1200px 600px at 20% -10%, #1b2b35 0%, transparent 60%),
                radial-gradient(900px 500px at 100% 0%, #142330 0%, transparent 55%),
                linear-gradient(180deg, var(--bg), var(--bg-2));
            min-height: 100vh;
        }}
        .wrap {{ max-width: 980px; margin: 28px auto 56px; padding: 0 16px; }}
        header {{
            display: flex; align-items: center; justify-content: space-between;
            gap: 12px; padding: 16px 18px; border: 1px solid var(--border);
            background: linear-gradient(135deg, #121a22 0%, #0e151c 100%);
            border-radius: 16px; box-shadow: 0 10px 30px rgba(0,0,0,0.25);
        }}
        h1 {{ margin: 0; font-size: 22px; letter-spacing: 1.2px; text-transform: uppercase; }}
        .meta {{ font-family: "Trebuchet MS", Arial, sans-serif; color: var(--muted); font-size: 12px; }}
        .grid {{ display: grid; gap: 14px; margin-top: 16px; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }}
        .card {{
            border: 1px solid var(--border); border-radius: 14px; padding: 14px 16px;
            background: linear-gradient(180deg, var(--card), var(--card-2));
        }}
        .card h2 {{ margin: 0 0 8px; font-size: 14px; text-transform: uppercase; letter-spacing: 1px; color: var(--muted); }}
        .value {{ font-size: 28px; font-weight: 700; letter-spacing: 0.5px; }}
        .pill {{
            display: inline-block; padding: 4px 10px; border-radius: 999px;
            font-family: "Trebuchet MS", Arial, sans-serif; font-size: 12px; letter-spacing: 0.5px;
            border: 1px solid var(--border);
        }}
        .ok {{ background: rgba(67,217,173,0.15); color: var(--accent); }}
        .warn {{ background: rgba(245,176,76,0.15); color: var(--warn); }}
        .bad {{ background: rgba(255,93,108,0.15); color: var(--danger); }}
        .row {{ display: flex; align-items: center; justify-content: space-between; gap: 8px; }}
        .small {{ font-family: "Trebuchet MS", Arial, sans-serif; color: var(--muted); font-size: 12px; }}
        .status-line {{ margin-top: 14px; padding: 10px 12px; border-radius: 12px; border: 1px dashed var(--border); }}
        .mono {{ font-family: "Courier New", Courier, monospace; }}
        .footer {{ margin-top: 16px; color: var(--muted); font-size: 11px; text-align: right; }}
        .chat {{
            margin-top: 16px; border: 1px solid var(--border); border-radius: 16px;
            background: linear-gradient(180deg, #0f151c, #0b1117);
            padding: 12px;
        }}
        .chat h3 {{ margin: 0 0 10px; font-size: 13px; letter-spacing: 1px; text-transform: uppercase; color: var(--muted); }}
        .msg {{ display: grid; gap: 6px; margin-bottom: 10px; }}
        .msg .meta {{ display: flex; justify-content: space-between; font-size: 11px; color: var(--muted); }}
        .bubble {{ padding: 8px 10px; border-radius: 12px; line-height: 1.3; }}
        .msg.in .bubble {{ background: rgba(67,217,173,0.08); border: 1px solid rgba(67,217,173,0.2); }}
        .msg.out .bubble {{ background: rgba(70,130,255,0.08); border: 1px solid rgba(70,130,255,0.25); }}
        .empty {{ color: var(--muted); font-size: 12px; padding: 6px 0; }}
        .metadata-badges {{ display: flex; gap: 6px; flex-wrap: wrap; margin: 4px 0; }}
        .badge {{
            font-family: "Courier New", Courier, monospace;
            font-size: 10px;
            padding: 3px 7px;
            border-radius: 8px;
            background: rgba(100,120,140,0.12);
            border: 1px solid rgba(100,120,140,0.25);
            color: var(--muted);
        }}
        .badge.signal-excellent {{ background: rgba(67,217,173,0.15); border-color: rgba(67,217,173,0.35); color: var(--accent); }}
        .badge.signal-good {{ background: rgba(100,200,100,0.15); border-color: rgba(100,200,100,0.35); color: #6ec86e; }}
        .badge.signal-moderate {{ background: rgba(245,176,76,0.15); border-color: rgba(245,176,76,0.35); color: var(--warn); }}
        .badge.signal-weak {{ background: rgba(255,93,108,0.15); border-color: rgba(255,93,108,0.35); color: var(--danger); }}
    </style>
</head>
<body>
    <div class=\"wrap\">
        <header>
            <div>
                <h1>LARA Status</h1>
                <div class=\"meta\">MeshCore Auto-Reply Dashboard</div>
            </div>
            <div class=\"pill {('ok' if status == 'running' else 'bad')}\">{status_tag}</div>
        </header>

        <div class=\"grid\">
            <div class=\"card\">
                <h2>Messages</h2>
                <div class=\"value\">{messages_received} in</div>
                <div class=\"small\">Processed: {messages_processed}</div>
                <div class=\"small\">Queue now: {queue_size}</div>
            </div>
            <div class=\"card\">
                <h2>Uptime</h2>
                <div class=\"value\">{uptime_min} min</div>
                <div class=\"small\">{uptime_sec} seconds</div>
            </div>
            <div class=\"card\">
                <h2>Queue</h2>
                <div class=\"row\">
                    <div class=\"value\">{queue_size}</div>
                    <div class=\"pill {('warn' if queue_size > 0 else 'ok')}\">LIVE</div>
                </div>
                <div class=\"small\">Peak: {queue_peak}</div>
            </div>
            <div class=\"card\">
                <h2>AI</h2>
                <div class=\"value\">{ai_ok} ok</div>
                <div class=\"small\">Fail: {ai_fail} | Fallback: {ai_fallback}</div>
                <div class=\"small\">Avg latency: {ai_latency}s | Last: {ai_last_latency}s</div>
            </div>
            <div class=\"card\">
                <h2>OpenWebUI</h2>
                <div class=\"row\">
                    <div class=\"value\">{openwebui_tag}</div>
                    <div class=\"pill {('ok' if openwebui_up else 'bad')}\">HEALTH</div>
                </div>
                <div class=\"small\">Webhook: {webhook_tag}</div>
            </div>
        </div>

        <div class=\"status-line\">
            <div class=\"row\">
                <div class=\"small\">Last monitor activity</div>
                <div class=\"mono\">{last_monitor_age} sec ago</div>
            </div>
        </div>

        <div class=\"chat\">
            <h3>Message Stream</h3>
            {chat_html}
        </div>

        <div class=\"footer\">/status (HTML) | /status?format=json (JSON)</div>
    </div>
</body>
</html>"""

    def _start_health_server(self) -> None:
        system_cfg = self.cfg.get("system", {})
        enabled = bool(system_cfg.get("health_enabled", True))
        if not enabled:
            return

        host = str(system_cfg.get("health_host", "127.0.0.1"))
        port = int(system_cfg.get("health_port", 8766))

        bot = self

        class HealthHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                base_path = self.path.split("?")[0]
                if base_path != "/status":
                    self.send_response(404)
                    self.end_headers()
                    return

                payload = bot._get_health_payload()
                query = self.path.split("?", 1)[1] if "?" in self.path else ""
                accept = (self.headers.get("Accept") or "").lower()
                wants_json = "format=json" in query or "application/json" in accept

                if wants_json:
                    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    html = bot._render_status_html(payload)
                    body = html.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

            def log_message(self, format: str, *args) -> None:
                return

        try:
            self._health_server = ThreadingHTTPServer((host, port), HealthHandler)
            self._health_thread = threading.Thread(
                target=self._health_server.serve_forever,
                daemon=True,
            )
            self._health_thread.start()
            logger.info("✅ Health dashboard running at http://%s:%s/status", host, port)
        except Exception as e:
            logger.error(f"Health dashboard start failed: {e}")

    def _stop_health_server(self) -> None:
        if not self._health_server:
            return
        try:
            self._health_server.shutdown()
            self._health_server.server_close()
        except Exception:
            pass
        finally:
            self._health_server = None

    def _start_monitor(self) -> None:
        binp = shutil.which("meshcore-cli")
        if not binp:
            logger.error("meshcore-cli not found on PATH - install or add it to PATH.")
            sys.exit(1)
        cmd = [binp, "-j", "-s", self.default_port, "ms"]
        logger.info(f"Starting monitor: {' '.join(cmd)}")
        try:
            self.monitor_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except Exception as e:
            logger.error(f"Monitor start failed: {e}")
            sys.exit(1)

    def _stop_monitor(self) -> None:
        if not self.monitor_proc:
            return
        try:
            # Close stdout first to unblock any waiting readline()
            if self.monitor_proc.stdout:
                try:
                    self.monitor_proc.stdout.close()
                except Exception:
                    pass
            self.monitor_proc.terminate()
            self.monitor_proc.wait(timeout=2)
        except Exception:
            try:
                self.monitor_proc.kill()
            except Exception:
                pass
        finally:
            self.monitor_proc = None

    def _read_monitor_line_nonblocking(self) -> Optional[str]:
        proc = self.monitor_proc
        if not proc or not proc.stdout:
            return None

        stdout = proc.stdout

        if sys.platform == "win32":
            try:
                import ctypes
                import msvcrt

                handle = msvcrt.get_osfhandle(stdout.fileno())
                avail = ctypes.c_ulong()
                # PeekNamedPipe returns nonzero on success
                ok = ctypes.windll.kernel32.PeekNamedPipe(
                    handle, None, 0, None, ctypes.byref(avail), None
                )
                if ok == 0 or avail.value == 0:
                    return None
            except Exception:
                return None

            return stdout.readline()

        try:
            rlist, _, _ = select.select([stdout], [], [], 0)
        except Exception:
            return None

        if not rlist:
            return None

        return stdout.readline()

    def _monitor_reader_loop(self) -> None:
        """
        Background thread that reads lines from monitor process and queues them.
        This prevents the main loop from blocking on readline().
        """
        logger.debug("Monitor reader thread started")
        while self.running:
            try:
                line = self._read_monitor_line_nonblocking()
                if line is None:
                    time.sleep(0.05)
                    continue

                if line == "":
                    # EOF - monitor died or pipe closed
                    logger.debug("Monitor EOF detected - will restart")
                    time.sleep(0.5)
                    continue

                line = line.strip()
                if line:
                    self._monitor_line_queue.append(line)
                    if self.debug_mode:
                        logger.debug(f"[READER] Queued: {line[:100]}...")
            except Exception as e:
                logger.debug(f"Monitor reader error: {e}")
                time.sleep(0.5)

        logger.debug("Monitor reader thread exiting")

    def _resolve_sender_pubkey(self, pubkey_prefix: str) -> Optional[str]:
        if not pubkey_prefix:
            return None
        nodes = self.cfg.get("nodes", {})
        for _, node_cfg in nodes.items():
            node_pubkey = str(node_cfg.get("pubkey", "")).lower()
            if node_pubkey.startswith(pubkey_prefix.lower()):
                return node_pubkey
        return None

    def _enforce_rate_limit(self) -> float:
        """
        Enforce rate limiting for AI calls.
        Returns: time_waited (seconds), or 0 if no wait needed.
        """
        now = time.time()
        time_since_last_call = now - self._last_ai_call_time

        if time_since_last_call < self.min_ai_interval_sec:
            wait_time = self.min_ai_interval_sec - time_since_last_call
            if self.debug_mode:
                logger.debug(f"⏱️  Rate limit: Waiting {wait_time:.2f}s before next AI call")
            time.sleep(wait_time)
            self._last_ai_call_time = time.time()
            return wait_time

        self._last_ai_call_time = now
        return 0.0

    def _record_ai_call(self, latency_sec: float, success: bool, is_fallback: bool = False) -> None:
        """Record AI call metrics."""
        with self._metrics_lock:
            if success:
                if is_fallback:
                    self._metrics["ai_calls_fallback"] += 1
                else:
                    self._metrics["ai_calls_success"] += 1
            else:
                self._metrics["ai_calls_failed"] += 1

            self._metrics["total_ai_latency_sec"] += latency_sec
            self._metrics["last_ai_latency_sec"] = latency_sec

    def _get_metrics_summary(self) -> str:
        """Format a one-line metrics summary."""
        with self._metrics_lock:
            m = self._metrics
            total_calls = m["ai_calls_success"] + m["ai_calls_failed"] + m["ai_calls_fallback"]
            if total_calls == 0:
                return "[STATS] No calls yet"

            avg_latency = m["total_ai_latency_sec"] / total_calls if total_calls > 0 else 0
            last_latency = m.get("last_ai_latency_sec", 0.0)
            uptime_sec = time.time() - m["start_time"]
            uptime_min = uptime_sec / 60

            return (
                f"[STATS] Msgs: {m['messages_received']} in / {m['messages_processed']} done | "
                f"AI: {m['ai_calls_success']}✓ {m['ai_calls_failed']}✗ {m['ai_calls_fallback']}⚠️  | "
                f"Avg latency: {avg_latency:.2f}s | Last: {last_latency:.2f}s | "
                f"Queue peak: {m['queue_peak_size']} | "
                f"Uptime: {uptime_min:.1f}min"
            )

    def _detect_language(self, text: str) -> str:
        """
        Detect language (HU or EN) based on keywords.
        Returns: 'hu' or 'en' (default)
        """
        hu_keywords = {
            "szia", "halló", "hello", "köszönöm", "hogyan", "segítség",
            "mi", "miért", "hol", "mikor", "mit", "melyik",
            "lehet", "tudod", "segíts", "kérlek", "kérem",
        }
        en_keywords = {
            "hello", "hi", "thanks", "help", "please", "thanks",
            "how", "what", "where", "when", "why", "which",
            "can", "could", "would", "should", "need",
        }

        text_lower = text.lower()
        text_words = set(text_lower.split())

        # Count keyword matches
        hu_score = len(text_words & hu_keywords)
        en_score = len(text_words & en_keywords)

        if hu_score > en_score:
            return "hu"
        return "en"

    def _prioritize_queue(self) -> None:
        """
        Re-prioritize message queue: shorter messages first (higher priority).
        This ensures quick questions get answered quickly, while longer/complex
        messages don't pile up the queue.
        """
        if len(self._message_queue) <= 1:
            return  # No need to sort single or empty queue

        # Sort by message text length (shortest first)
        self._message_queue.sort(key=lambda msg: len(msg.get("text", "")))

        if self.debug_mode:
            logger.debug(f"[QUEUE] Re-prioritized {len(self._message_queue)} messages by length")

    def call_ai(self, user_text: str, metadata: dict = None) -> Optional[str]:
        """
        Call OpenWebUI API with streaming support and graceful degradation.

        GRACEFUL DEGRADATION CHAIN:
        1. Try streaming API (if enabled)
        2. Fall back to non-streaming API
        3. Fall back to stub AI (offline mode)
        4. Return None (complete failure)

        Returns the AI response which is then sent via PRIV.

        MEMORY MANAGEMENT:
        Uses sliding window to prevent context overflow. Only keeps the last
        N message pairs (user + assistant) in memory to stay within LLM token limits.

        METADATA INJECTION:
        If metadata is provided (RSSI, SNR, hop count), it's injected as a system
        message at the start of the conversation. This allows the AI to be aware
        of signal quality and routing without treating it as a user message.

        SPECIAL COMMANDS:
        /clear - Clears conversation history without calling AI
        """
        # SPECIAL COMMAND: Clear conversation history
        if user_text.strip().lower() == "/clear":
            previous_count = len(self.memory)
            self.memory.clear()

            # ALSO: Clear OpenWebUI backend chat history (if API available)
            self._clear_openwebui_chats()

            logger.info(f"🗑️  Conversation history cleared ({previous_count} messages removed)")
            return "✅ Conversation history cleared. Starting fresh!"

        # RATE LIMITING: Enforce minimum interval between AI calls
        self._enforce_rate_limit()

        start_time = time.time()

        api_url = self.ai_cfg.get("api_url")
        api_key = self.ai_cfg.get("api_key")
        if not api_url or not api_key:
            logger.error("AI API not configured (api_url/api_key missing).")
            elapsed = time.time() - start_time
            self._record_ai_call(elapsed, success=False, is_fallback=False)
            return None

        # Add user message to memory
        self.memory.append({"role": "user", "content": user_text})

        # SLIDING WINDOW: Limit memory size to prevent context overflow
        # memory_limit specifies number of message PAIRS to keep (user + assistant)
        # So actual message count = memory_limit * 2
        memory_limit = int(self.ai_cfg.get("memory_limit", 15))  # Default: 15 pairs = 30 messages
        max_memory_size = memory_limit * 2

        # Trim oldest messages if we exceed the limit
        if len(self.memory) > max_memory_size:
            self.memory = self.memory[-max_memory_size:]
            logger.debug(f"🔄 Memory trimmed to last {memory_limit} message pairs ({max_memory_size} messages)")

        # Send all remaining messages to AI (already trimmed)
        messages = self.memory.copy()

        # METADATA INJECTION: Add system message with signal/routing info
        if metadata:
            metadata_msg = self._format_metadata_for_ai(metadata)
            if metadata_msg:
                # Insert system message at the beginning
                messages.insert(0, {"role": "system", "content": metadata_msg})

        answer = None

        if self.use_streaming:
            # Try streaming first
            logger.debug("Attempting streaming API call...")
            answer = self._call_ai_streaming(api_url, api_key, messages)

            if answer:
                logger.debug(f"Streaming response received: {len(answer)} bytes")
                self.memory.append({"role": "assistant", "content": answer})
                # Trim again after adding assistant response
                if len(self.memory) > max_memory_size:
                    self.memory = self.memory[-max_memory_size:]
                elapsed = time.time() - start_time
                self._record_ai_call(elapsed, success=True, is_fallback=False)
                return answer

        # Fallback to non-streaming
        logger.debug("Streaming failed or disabled, trying non-streaming API...")
        answer = self._call_ai_nonstreaming(api_url, api_key, messages)

        if answer:
            logger.debug(f"Non-streaming response received: {len(answer)} bytes")
            self.memory.append({"role": "assistant", "content": answer})
            # Trim again after adding assistant response
            if len(self.memory) > max_memory_size:
                self.memory = self.memory[-max_memory_size:]
            elapsed = time.time() - start_time
            self._record_ai_call(elapsed, success=True, is_fallback=False)
            return answer

        # All API calls failed - use fallback/stub AI
        logger.error("Both streaming and non-streaming calls failed - USING STUB AI")
        answer = self._get_stub_ai_response(user_text)
        if answer:
            self.memory.append({"role": "assistant", "content": answer})
            # Trim again after adding fallback response
            if len(self.memory) > max_memory_size:
                self.memory = self.memory[-max_memory_size:]
            elapsed = time.time() - start_time
            self._record_ai_call(elapsed, success=True, is_fallback=True)
            return answer

        elapsed = time.time() - start_time
        self._record_ai_call(elapsed, success=False, is_fallback=False)
        return None

    def _call_ai_streaming(self, api_url: str, api_key: str, messages: list) -> Optional[str]:
        """
        Call OpenWebUI with streaming enabled (SSE format).
        Accumulates all tokens into a complete response.
        """
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.ai_cfg.get("model_id", "mistral"),
            "messages": messages,
            "stream": True,  # Enable streaming
        }

        try:
            logger.info("📤 START: Streaming API request")
            res = requests.post(api_url, headers=headers, json=payload, timeout=60, stream=True)

            if res.status_code != 200:
                logger.warning(f"Streaming API error: {res.status_code}")
                return None

            accumulated = ""
            token_count = 0

            for line in res.iter_lines():
                if not line:
                    continue

                line = line.decode("utf-8") if isinstance(line, bytes) else line

                # SSE format: "data: {json}"
                if line.startswith("data: "):
                    line = line[6:].strip()

                    if line == "[DONE]":
                        logger.info(f"📥 DONE: Streaming complete ({token_count} tokens, {len(accumulated)} bytes)")
                        return accumulated if accumulated else None

                    try:
                        data = json.loads(line)
                        # OpenAI-format streaming response
                        if "choices" in data and len(data["choices"]) > 0:
                            delta = data["choices"][0].get("delta", {})
                            token = delta.get("content", "")
                            if token:
                                accumulated += token
                                token_count += 1
                                if token_count % 10 == 0:
                                    logger.debug(f"  ↓ Received {token_count} tokens so far...")
                    except json.JSONDecodeError:
                        continue

            logger.info(f"Stream ended: {token_count} tokens, {len(accumulated)} bytes")
            return accumulated if accumulated else None

        except requests.exceptions.Timeout:
            logger.warning("Streaming call timeout (60s)")
            return None
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"Streaming connection error: {e}")
            return None
        except Exception as e:
            logger.warning(f"Streaming call error: {e}")
            return None

    def _call_ai_nonstreaming(self, api_url: str, api_key: str, messages: list) -> Optional[str]:
        """
        Call OpenWebUI without streaming (standard JSON response).
        Returns after full response is ready.
        """
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.ai_cfg.get("model_id", "mistral"),
            "messages": messages,
            "stream": False,  # Disable streaming
        }

        try:
            logger.info("📤 START: Non-streaming API request (timeout: 60s)")
            res = requests.post(api_url, headers=headers, json=payload, timeout=60)

            if res.status_code != 200:
                logger.error(f"Non-streaming API error: {res.status_code}")
                return None

            data = None
            raw_text = res.text or ""
            if raw_text.lstrip().startswith("data:"):
                for raw_line in raw_text.splitlines():
                    line = raw_line.strip()
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if not payload or payload == "[DONE]":
                        continue
                    try:
                        data = json.loads(payload)
                        break
                    except json.JSONDecodeError:
                        continue
            if data is None:
                data = res.json()

            try:
                answer = data["choices"][0]["message"]["content"]
                logger.info(f"📥 DONE: Response received ({len(answer)} bytes)")
                return answer
            except (KeyError, IndexError, TypeError) as e:
                logger.error(f"Response parse error: {e}")
                return None

        except requests.exceptions.Timeout:
            logger.error("Non-streaming call timeout (60s)")
            return None
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Non-streaming connection error: {e}")
            return None
        except Exception as e:
            logger.error(f"Non-streaming call failed: {e}")
            return None

    def _clear_openwebui_chats(self) -> None:
        """
        Clear all OpenWebUI backend chat history using DELETE /api/v1/chats/ endpoint.
        This removes chat history from the web UI, but does NOT affect the stateless
        /api/chat/completions endpoint (which has no server-side session).

        NOTE: The main context reset happens via self.memory.clear() - this is an
        optional cleanup for the OpenWebUI web UI backend storage.
        """
        try:
            api_url_base = self.ai_cfg.get("api_url", "").replace("/api/chat/completions", "")
            if not api_url_base:
                logger.debug("No API URL configured, skipping OpenWebUI chat history clear")
                return

            api_key = self.ai_cfg.get("api_key")
            if not api_key:
                logger.debug("No API key configured, skipping OpenWebUI chat history clear")
                return

            # DELETE /api/v1/chats/ - Remove all user chats from backend
            delete_url = f"{api_url_base}/api/v1/chats/"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }

            logger.debug(f"🗑️  Clearing OpenWebUI backend chats: DELETE {delete_url}")
            res = requests.delete(delete_url, headers=headers, timeout=10)

            if res.status_code == 200:
                logger.info("✅ OpenWebUI backend chat history cleared")
            elif res.status_code == 404:
                logger.debug("OpenWebUI chat history endpoint not found (may not exist in this version)")
            elif res.status_code == 401:
                logger.warning("OpenWebUI chat clear failed: unauthorized (API key may be invalid)")
            else:
                logger.warning(f"OpenWebUI chat clear returned status {res.status_code}")

        except requests.exceptions.Timeout:
            logger.debug("OpenWebUI chat clear timeout (non-critical)")
        except requests.exceptions.ConnectionError:
            logger.debug("OpenWebUI chat clear connection error (OpenWebUI may be offline)")
        except Exception as e:
            logger.debug(f"OpenWebUI chat clear error (non-critical): {e}")

    def _format_metadata_for_ai(self, metadata: dict) -> str:
        """
        Format message metadata (RSSI, SNR, hop count) into human-readable text
        for AI system message injection.

        This allows the AI to be aware of signal quality and routing information
        without treating it as part of the user's message.

        Returns empty string if no relevant metadata is present.
        """
        if not metadata:
            return ""

        parts = []

        # Signal strength (RSSI)
        rssi = metadata.get('rssi')
        if rssi is not None:
            # RSSI typically ranges from -120 (very weak) to -30 (very strong)
            if rssi >= -50:
                signal_quality = "excellent"
            elif rssi >= -70:
                signal_quality = "good"
            elif rssi >= -85:
                signal_quality = "moderate"
            else:
                signal_quality = "weak"
            parts.append(f"Signal strength: {rssi} dBm ({signal_quality})")

        # Signal-to-Noise Ratio (SNR)
        snr = metadata.get('snr')
        if snr is not None:
            parts.append(f"SNR: {snr} dB")

        # Hop count (routing)
        hop_count = metadata.get('hop_count')
        hop_start = metadata.get('hop_start')
        if hop_count is not None and hop_start is not None:
            hops_traveled = hop_start - hop_count
            parts.append(f"Network route: {hops_traveled} hops / max {hop_start}")
        elif hop_count is not None:
            parts.append(f"Network hops: {hop_count}")

        if not parts:
            return ""

        # Build system message
        return (
            "[Metadata - Do not treat this as a user message, just acknowledge\n"
            f"{'; '.join(parts)}. "
            "Only refer to these if the user asks about them.]"
        )

    def _get_stub_ai_response(self, user_input: str) -> str:
        """
        Fallback AI response generator when OpenWebUI is unavailable.
        Simple rule-based responder for basic conversation.
        Responses are marked with [Offline] to indicate stub/fallback mode.
        Language is auto-detected (HU or EN).
        Includes personality & cultural nuances with emoji.
        """
        logger.warning("🚫 OpenWebUI unavailable - using STUB AI FALLBACK (Offline Mode)")

        user_lower = user_input.lower().strip()
        lang = self._detect_language(user_input)

        # Language-specific responses with personality and emoji
        if lang == "hu":
            # Hungarian responses with personality
            if any(w in user_lower for w in ["szia", "halló", "hello", "hi"]):
                return "[Offline] � Hi! Meshcore AI bot in offline mode. How can I help?"

            if any(w in user_lower for w in ["hobby", "kedvenc", "szeretsz"]):
                return "[Offline] 🤖 I like radios, mesh networks, and good conversations. What do you like?"

            if any(w in user_lower for w in ["hogy vagy", "milyen vagy", "jól vagy"]):
                return "[Offline] ⚡ Running great! Offline, but ready for questions."

            if any(w in user_lower for w in ["segítség", "segíts", "help"]):
                return "[Offline] 🆘 I'm here! Tell me what you need."

            if any(w in user_lower for w in ["köszönöm", "köszi", "kösz", "köszös"]):
                return "[Offline] 😊 You're welcome! Many packets! 📦"

            if any(w in user_lower for w in ["mi az", "miért", "mikor", "hogyan"]):
                return "[Offline] 🤔 Interesting! Tell me more?"

            if any(w in user_lower for w in ["meshcore", "mesh", "rádió", "node"]):
                return "[Offline] 📡 Ah meshcore! That's my home. Offline limits here, but online I know much more!"

            # Default Hungarian response
            return f"[Offline] 🤷 I understand: '{user_input[:50]}'. Tell me more about it?"

        else:
            # English responses with personality and emoji
            if any(w in user_lower for w in ["hello", "hi", "szia", "halló"]):
                return "[Offline] 🌐 Hi there! Meshcore AI bot in offline mode. How can I help?"

            if any(w in user_lower for w in ["hobby", "like", "favorite", "love"]):
                return "[Offline] 🤖 I love radios, mesh networks, and good chats. What about you?"

            if any(w in user_lower for w in ["how are you", "how do you", "you ok"]):
                return "[Offline] ⚡ Running great! Just offline right now. Ready for questions!"

            if any(w in user_lower for w in ["help", "assist", "need"]):
                return "[Offline] 🆘 I'm here! Tell me what you need."

            if any(w in user_lower for w in ["thanks", "thank you", "thanx", "thx"]):
                return "[Offline] 😊 Welcome! Many packets! 📦"

            if any(w in user_lower for w in ["what", "why", "when", "how"]):
                return "[Offline] 🤔 Interesting! Can you tell me more?"

            if any(w in user_lower for w in ["meshcore", "mesh", "radio", "node"]):
                return "[Offline] 📡 Ah meshcore! That's my home. Offline limits here, but when online I can tell you so much!"

            # Default English response with personality
            return f"[Offline] 🤷 I understand: '{user_input[:50]}'. Tell me more?"

    def _webhook_fire_and_forget(self, user_message: str, ai_response: str) -> None:
        """
        Fire-and-forget webhook push. Runs in a separate daemon thread
        to avoid blocking the worker thread. Uses aggressive timeout to prevent hangs.
        """
        try:
            if self._webhook_disabled:
                logger.debug("⚠️  WEBHOOK disabled - skipping push")
                return
            webui_api_url = self.ai_cfg.get("webui_webhook_url")
            api_key = self.ai_cfg.get("api_key")

            if not webui_api_url:
                logger.debug("⚠️  webui_webhook_url not configured - skipping webhook")
                return

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }

            # OpenWebUI expects a message push format
            payload = {
                "type": "message",
                "role": "assistant",
                "content": ai_response,
                "model": self.ai_cfg.get("model_id", "mistral"),
                "metadata": {
                    "source": "meshcore-bot",
                    "original_user_message": user_message,
                }
            }

            # Very short timeout (1s) - don't wait for slow WebUI
            logger.debug(f"🌐 WEBHOOK (async): Pushing {len(ai_response)} bytes (timeout: 1s)")
            res = requests.post(webui_api_url, headers=headers, json=payload, timeout=1)

            if res.status_code in [200, 201]:
                logger.debug("✅ WEBHOOK (async): Pushed successfully")
            elif res.status_code == 405:
                logger.debug("⚠️  WEBHOOK (async): Got 405 - disabling webhook")
                if self.webhook_disable_on_405:
                    self._webhook_disabled = True
            else:
                logger.debug(f"⚠️  WEBHOOK (async): Got {res.status_code}")

        except requests.exceptions.Timeout:
            logger.debug("⏱️  WEBHOOK (async): Timeout (expected for slow systems) - continuing anyway")
        except Exception as e:
            logger.debug(f"🌐 WEBHOOK (async): Non-critical error: {e}")

    def push_response_to_webui(self, user_message: str, ai_response: str) -> bool:
        """
        Push AI response back to OpenWebUI for web UI display.
        Creates a conversation entry so the user sees their message + AI response in the webapp.

        NOTE: This method is deprecated. Use _webhook_fire_and_forget() instead,
        which runs in a background thread and doesn't block the worker.
        """
        if self._webhook_disabled:
            logger.debug("⚠️  WEBHOOK disabled - skipping web UI update")
            return False
        webui_api_url = self.ai_cfg.get("webui_webhook_url")
        api_key = self.ai_cfg.get("api_key")

        if not webui_api_url:
            logger.debug("⚠️  webui_webhook_url not configured - skipping web UI update")
            return False

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # OpenWebUI expects a message push format
        payload = {
            "type": "message",
            "role": "assistant",
            "content": ai_response,
            "model": self.ai_cfg.get("model_id", "mistral"),
            "metadata": {
                "source": "meshcore-bot",
                "original_user_message": user_message,
            }
        }

        try:
            logger.info(f"🌐 WEBHOOK: Pushing response to WebUI ({len(ai_response)} bytes)...")
            res = requests.post(webui_api_url, headers=headers, json=payload, timeout=10)

            if res.status_code in [200, 201]:
                logger.info("✅ WEBHOOK SUCCESS: Response pushed to WebUI")
                return True
            if res.status_code == 405:
                logger.warning("⚠️  WEBHOOK FAILED: 405 - disabling webhook")
                if self.webhook_disable_on_405:
                    self._webhook_disabled = True
                return False
            else:
                logger.warning(f"⚠️  WEBHOOK FAILED: {res.status_code} - {res.text[:200]}")
                return False

        except Exception as e:
            logger.debug(f"Webhook push error (non-critical): {e}")
            return False

    def _send_priv_interactive(self, recipient_pubkey: str, text: str) -> bool:
        """
        Send PRIV using asyncio from worker thread (safe approach).
        AsyncIO is called from the worker thread, not the monitor thread,
        so monitor I/O is never blocked.
        """
        if not text:
            logger.warning("Empty message - not sending.")
            return False
        try:
            # Call asyncio from worker thread - this is safe!
            return asyncio.run(self._send_priv(recipient_pubkey, text))
        except Exception as e:
            logger.error(f"PRIV send failed: {e}")
            return False

    async def _send_via_persistent_connection(self, recipient_pubkey: str, text: str) -> bool:
        """
        Send PRIV using the existing persistent mesh connection.
        Does NOT create new connection or disconnect.
        """
        if not text:
            logger.warning("Empty message - not sending.")
            return False

        if not self._persistent_mesh:
            logger.error("No persistent connection available for sending")
            return False

        try:
            mesh = self._persistent_mesh
            contacts_res = await mesh.commands.get_contacts()
            if contacts_res.type == EventType.ERROR:
                logger.error(f"get_contacts failed: {contacts_res.payload}")
                return False
            contacts = contacts_res.payload or {}
            recipient_obj = contacts.get(recipient_pubkey)
            if not recipient_obj:
                logger.error(f"Recipient {recipient_pubkey[:16]}... not found in contacts.")
                return False

            chunks = _chunk_text_with_numbering(text, self.chunk_chars, self.max_chunks)
            for i, chunk in enumerate(chunks, 1):
                logger.info(f"Sending PRIV chunk {i}/{len(chunks)} via persistent connection")
                send_res = await mesh.commands.send_msg(recipient_obj, chunk)
                if send_res.type == EventType.ERROR:
                    logger.error(f"send_msg failed: {send_res.payload}")
                    return False
                await asyncio.sleep(0.2)
            # Do NOT disconnect - connection stays alive
            return True
        except Exception as e:
            logger.error(f"PRIV send via persistent connection failed: {e}")
            return False

    async def _send_priv(self, recipient_pubkey: str, text: str) -> bool:
        """
        Send PRIV by creating new connection (CLI mode).
        Opens connection, sends, then disconnects.
        """
        if not text:
            logger.warning("Empty message - not sending.")
            return False
        try:
            mesh = await MeshCore.create_serial(self.default_port)
            contacts_res = await mesh.commands.get_contacts()
            if contacts_res.type == EventType.ERROR:
                logger.error(f"get_contacts failed: {contacts_res.payload}")
                await mesh.disconnect()
                return False
            contacts = contacts_res.payload or {}
            recipient_obj = contacts.get(recipient_pubkey)
            if not recipient_obj:
                logger.error(f"Recipient {recipient_pubkey[:16]}... not found in contacts.")
                await mesh.disconnect()
                return False

            chunks = _chunk_text_with_numbering(text, self.chunk_chars, self.max_chunks)
            for i, chunk in enumerate(chunks, 1):
                logger.info(f"Sending PRIV chunk {i}/{len(chunks)}")
                send_res = await mesh.commands.send_msg(recipient_obj, chunk)
                if send_res.type == EventType.ERROR:
                    logger.error(f"send_msg failed: {send_res.payload}")
                    await mesh.disconnect()
                    return False
                await asyncio.sleep(0.2)
            await mesh.disconnect()
            return True
        except Exception as e:
            if _looks_like_com_busy(str(e)):
                logger.error(COM_BUSY_HINT)
            logger.error(f"PRIV send failed: {e}")
            return False

    def send_priv_sync(self, recipient_pubkey: str, text: str) -> bool:
        """
        Send PRIV using asyncio from worker thread.
        In library mode: uses persistent connection (no stop/restart needed).
        In CLI mode: stops monitor, sends PRIV, and restarts monitor.
        """
        if self._use_library_mode and self._persistent_mesh:
            # Library mode: use persistent connection (thread-safe via send_lock)
            with self._send_lock:
                try:
                    result = asyncio.run(self._send_via_persistent_connection(recipient_pubkey, text))
                    return result
                except Exception as e:
                    logger.error(f"PRIV send via persistent connection failed: {e}")
                    return False
        else:
            # CLI mode: stop monitor, send, restart
            with self._send_lock:
                # Stop monitor temporarily (we're in the worker thread, not monitor thread)
                self._stop_monitor()
                time.sleep(0.5)

                try:
                    # Call asyncio.run() from worker thread - safe!
                    result = asyncio.run(self._send_priv(recipient_pubkey, text))
                finally:
                    # Always restart monitor
                    time.sleep(0.5)
                    self._start_monitor()

                return result

    def monitor_loop_library(self) -> None:
        """Monitor using MeshCore library with PERSISTENT connection (recommended)."""
        logger.info("🔄 Starting LIBRARY-BASED monitor (PERSISTENT connection mode)...")
        self._use_library_mode = True  # Set flag for send operations

        # Start background worker thread
        self._message_worker_thread = threading.Thread(target=self._message_worker, daemon=False)
        self._message_worker_thread.start()
        logger.info("📡 Message worker thread started")

        poll_interval = float(self.bot_cfg.get("library_poll_interval_sec", 1.0))
        logger.info(f"📡 Polling for new messages every {poll_interval}s...")
        logger.info(f"📡 Connecting to {self.default_port}...")

        # Run the async persistent loop
        try:
            asyncio.run(self._persistent_poll_loop(poll_interval))
        except Exception as e:
            logger.error(f"Persistent polling error: {e}")
            if _looks_like_com_busy(str(e)):
                logger.error(COM_BUSY_HINT)

        logger.info("Monitor loop stopped.")

    async def _persistent_poll_loop(self, poll_interval: float) -> None:
        """
        Persistent connection polling loop with auto-reconnect.
        Opens serial connection and keeps it open, automatically reconnecting on failures.
        """
        mesh = None
        metrics_log_interval = 600  # 10 minutes
        last_metrics_log = time.time()
        openwebui_check_interval = 60  # Check OpenWebUI every 60 seconds
        last_openwebui_check = time.time()
        retry_delay = 1.0  # Start with 1 second
        max_retry_delay = 60.0  # Cap at 60 seconds

        while self.running:
            try:
                # Open/reopen connection
                if mesh is None:
                    logger.info(f"📡 Connecting to {self.default_port}...")
                    mesh = await MeshCore.create_serial(self.default_port)
                    self._persistent_mesh = mesh  # Store for send operations
                    logger.info(f"✅ Connected to {self.default_port} (persistent mode)")
                    retry_delay = 1.0  # Reset retry delay on successful connection

                # Poll continuously without disconnecting
                while self.running:
                    try:
                        await self._poll_messages_from_connection(mesh)
                    except Exception as e:
                        logger.debug(f"Poll iteration error: {e}")
                        # Check if it's a fatal connection error
                        error_str = str(e).lower()
                        if "disconnected" in error_str or "closed" in error_str or "not open" in error_str:
                            logger.warning(f"⚠️ Connection lost: {e}")
                            raise  # Re-raise to trigger reconnect

                    now = time.time()

                    # Periodically log metrics (every 10 minutes)
                    if now - last_metrics_log >= metrics_log_interval:
                        metrics_summary = self._get_metrics_summary()
                        logger.info(metrics_summary)
                        last_metrics_log = now

                    # Periodically check OpenWebUI health (every 60 seconds)
                    if now - last_openwebui_check >= openwebui_check_interval:
                        if not self._is_openwebui_up() and self._openwebui_proc:
                            logger.warning("⚠️ OpenWebUI is not responding, attempting restart...")
                            self._restart_openwebui()
                        last_openwebui_check = now

                    # Wait before next poll
                    await asyncio.sleep(poll_interval)

            except Exception as e:
                logger.error(f"❌ Persistent connection error: {e}")
                if _looks_like_com_busy(str(e)):
                    logger.error(COM_BUSY_HINT)

                # Disconnect and prepare for reconnect
                self._persistent_mesh = None
                if mesh:
                    try:
                        await mesh.disconnect()
                    except Exception:
                        pass
                    mesh = None

                # Don't retry if shutting down
                if not self.running:
                    break

                # Auto-heal: Try to find an available port if default port fails
                target_port = self.default_port
                if retry_delay >= 10:  # After a few failed attempts
                    logger.info("🔍 Scanning for available COM ports...")
                    available_ports = find_available_ports(self.default_port)
                    if available_ports:
                        target_port = available_ports[0]
                        if target_port != self.default_port:
                            logger.info(f"🔄 Switching to alternative port: {target_port}")
                            self.default_port = target_port  # Update for future attempts

                # Exponential backoff
                logger.info(f"🔄 Reconnecting to {target_port} in {retry_delay:.1f}s...")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_retry_delay)

        # Final cleanup on shutdown
        self._persistent_mesh = None
        if mesh:
            try:
                await mesh.disconnect()
                logger.info("🔌 Disconnected from serial port")
            except Exception as e:
                logger.debug(f"Disconnect error: {e}")

    async def _poll_messages_from_connection(self, mesh) -> None:
        """
        Poll for messages using an already-open connection.
        Does NOT disconnect after checking.
        """
        try:
            # Try get_msg() first - it should return messages as a list
            msg_res = await mesh.commands.get_msg()

            if msg_res.type == EventType.ERROR:
                logger.debug(f"get_msg returned error: {msg_res.payload}")
                return

            payload = msg_res.payload

            # DEBUG: Log the raw payload
            if self.debug_mode and payload:
                logger.debug(f"📦 get_msg() payload type: {type(payload)}, value: {repr(payload)[:200]}")

            # Handle different payload formats:
            # 1. String notification (e.g., "messages_available") - ignore
            if isinstance(payload, str):
                return  # Just a notification, no actual messages

            # 2. None or empty - no messages
            if not payload:
                return

            # 3. Dict (single message) - wrap in list
            if isinstance(payload, dict):
                messages = [payload]
            # 4. List of messages - use as-is
            elif isinstance(payload, list):
                messages = payload
            else:
                logger.debug(f"Unexpected payload type: {type(payload)}")
                return

            # DEBUG: Log message count
            if self.debug_mode and messages:
                logger.debug(f"📨 Processing {len(messages)} message(s)")

            # Process each message
            for msg_obj in messages:
                try:
                    await self._process_library_message(msg_obj)
                except Exception as e:
                    logger.debug(f"Message processing error: {e}")

        except Exception as e:
            logger.debug(f"Poll from connection error: {e}")

    async def _process_library_message(self, msg_obj) -> None:
        """Process a single message from library get_msg()."""
        try:
            # DEBUG: Log the raw message object
            if self.debug_mode:
                logger.debug(f"📦 RAW MESSAGE: type={type(msg_obj)}, repr={repr(msg_obj)[:200]}")
                if hasattr(msg_obj, '__dict__'):
                    logger.debug(f"   Attributes: {msg_obj.__dict__}")

            # Extract message fields - handle both dict and object formats
            if isinstance(msg_obj, dict):
                msg_type = msg_obj.get('type')
                text = msg_obj.get('text', '').strip()
                sender_pubkey_prefix = msg_obj.get('pubkey_prefix', '')
                sender_timestamp = str(msg_obj.get('sender_timestamp', ''))
                # Extract metadata (signal strength, hops, etc.)
                rssi = msg_obj.get('rssi')
                snr = msg_obj.get('snr')
                hop_count = msg_obj.get('hop_count')
                hop_start = msg_obj.get('hop_start')
            else:
                # Object format
                msg_type = getattr(msg_obj, 'type', None)
                text = getattr(msg_obj, 'text', '').strip()
                sender_pubkey_prefix = getattr(msg_obj, 'pubkey_prefix', '')
                sender_timestamp = str(getattr(msg_obj, 'sender_timestamp', ''))
                # Extract metadata (signal strength, hops, etc.)
                rssi = getattr(msg_obj, 'rssi', None)
                snr = getattr(msg_obj, 'snr', None)
                hop_count = getattr(msg_obj, 'hop_count', None)
                hop_start = getattr(msg_obj, 'hop_start', None)

            if self.debug_mode:
                logger.debug(
                    f"   Extracted: type={msg_type}, text_len={len(text)}, sender={sender_pubkey_prefix[:8]}..., ts={sender_timestamp}")

            if msg_type != 'PRIV':
                logger.debug(f"   ❌ Skipped: Not PRIV (type={msg_type})")
                return  # Only process PRIV messages

            if not text:
                logger.debug("   ❌ Skipped: Empty text")
                return

            # Dedupe check
            dedupe_key = f"{sender_pubkey_prefix}|{sender_timestamp}|{text}"
            now = time.time()
            seen_ttl = float(self.bot_cfg.get("monitor_dedupe_ttl_sec", 120.0))

            with self._last_seen_messages_lock:
                if dedupe_key in self._last_seen_messages:
                    if now - self._last_seen_messages[dedupe_key] < seen_ttl:
                        return
                self._last_seen_messages[dedupe_key] = now

            # Resolve sender
            sender_pubkey = self._resolve_sender_pubkey(sender_pubkey_prefix)
            if not sender_pubkey:
                logger.warning(f"Sender pubkey not resolved: {sender_pubkey_prefix}")
                return

            # Find sender name
            sender_name = None
            nodes = self.cfg.get("nodes", {})
            for _, node_cfg in nodes.items():
                if str(node_cfg.get("pubkey", "")).lower().startswith(sender_pubkey_prefix.lower()):
                    sender_name = node_cfg.get("name")
                    break

            # Build metadata dict
            metadata = {}
            if rssi is not None:
                metadata['rssi'] = rssi
            if snr is not None:
                metadata['snr'] = snr
            if hop_count is not None:
                metadata['hop_count'] = hop_count
            if hop_start is not None:
                metadata['hop_start'] = hop_start

            # SIMULATION MODE: Generate random metadata for testing
            if self.simulate_metadata and not metadata:
                import random
                metadata = {
                    'rssi': random.randint(-95, -40),
                    'snr': random.randint(0, 15),
                    'hop_count': random.randint(0, 5),
                    'hop_start': 5
                }
                logger.warning(f"🧪 SIMULATED METADATA: {metadata}")

            logger.info(f"✉️  QUEUED: Incoming PRIV from [{sender_name or sender_pubkey_prefix}]")
            if metadata:
                logger.debug(f"      Metadata: {metadata}")
            logger.debug(f"      Text: {text[:150]}...")
            self._append_message_log("in", sender_name or sender_pubkey_prefix, text, metadata=metadata)

            # Queue for processing
            self._message_queue.append({
                "sender_pubkey": sender_pubkey,
                "sender_name": sender_name,
                "text": text,
                "timestamp": time.time(),
                "metadata": metadata if metadata else None,
            })
            with self._metrics_lock:
                self._metrics["messages_received"] += 1
                current_queue = len(self._message_queue)
                if current_queue > self._metrics["queue_peak_size"]:
                    self._metrics["queue_peak_size"] = current_queue
            logger.debug(f"      Queue size: {len(self._message_queue)}")

        except Exception as e:
            logger.debug(f"Library message processing error: {e}")

    def monitor_loop(self) -> None:
        self._start_monitor()
        if not self.monitor_proc or not self.monitor_proc.stdout:
            logger.error("Monitor could not start - exiting.")
            return

        # Start background worker thread for processing messages
        # Note: daemon=False to allow graceful shutdown
        self._message_worker_thread = threading.Thread(target=self._message_worker, daemon=False)
        self._message_worker_thread.start()
        logger.info("📡 Message worker thread started")

        logger.info("Monitor loop started, waiting for messages...")
        while self.running:
            if not self.monitor_proc or self.monitor_proc.poll() is not None:
                if not self._send_lock.locked():
                    poll_interval = float(self.bot_cfg.get("monitor_poll_interval_sec", 0.8))
                    min_restart = float(self.bot_cfg.get("monitor_restart_min_interval_sec", 0.8))
                    now = time.time()
                    if now >= self._next_monitor_start_time and now - self._last_monitor_restart_time >= min_restart:
                        logger.debug("Monitor process not running - restarting...")
                        self._stop_monitor()
                        time.sleep(0.2)
                        self._start_monitor()
                        self._last_monitor_restart_time = now
                        self._next_monitor_start_time = now + poll_interval
                time.sleep(0.05)
                continue

            line = self._read_monitor_line_nonblocking()
            if line is None:
                time.sleep(0.05)
                continue

            if line == "":
                # EOF - monitor died or pipe closed
                time.sleep(0.05)
                continue

            line = line.strip()
            if _looks_like_com_busy(line):
                logger.error(COM_BUSY_HINT)
                break
            if self.debug_mode:
                logger.debug("RAW: %s", line[:500])
            if not line.startswith("{"):
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            if "text" not in data:
                continue

            pubkey_prefix = str(data.get("pubkey_prefix", ""))
            incoming = str(data.get("text", "")).strip()
            sender_ts = str(data.get("sender_timestamp", ""))
            dedupe_key = f"{pubkey_prefix}|{sender_ts}|{incoming}"
            now = time.time()
            seen_ttl = float(self.bot_cfg.get("monitor_dedupe_ttl_sec", 120.0))

            with self._last_seen_messages_lock:
                if dedupe_key in self._last_seen_messages:
                    if now - self._last_seen_messages[dedupe_key] < seen_ttl:
                        continue
                self._last_seen_messages[dedupe_key] = now

            sender_pubkey = self._resolve_sender_pubkey(pubkey_prefix)

            if not sender_pubkey:
                logger.warning("Sender pubkey not resolved; ignoring message.")
                continue

            sender_name = None
            nodes = self.cfg.get("nodes", {})
            for _, node_cfg in nodes.items():
                if str(node_cfg.get("pubkey", "")).lower().startswith(pubkey_prefix.lower()):
                    sender_name = node_cfg.get("name")
                    break

            logger.info(f"✉️  QUEUED: Incoming PRIV from [{sender_name or pubkey_prefix}]")
            logger.debug(f"      Text: {incoming[:150]}...")
            self._append_message_log("in", sender_name or pubkey_prefix, incoming)

            # Queue message for async processing instead of blocking here
            self._message_queue.append({
                "sender_pubkey": sender_pubkey,
                "sender_name": sender_name,
                "text": incoming,
                "timestamp": time.time(),  # Track when message arrived
            })
            with self._metrics_lock:
                self._metrics["messages_received"] += 1
                current_queue = len(self._message_queue)
                if current_queue > self._metrics["queue_peak_size"]:
                    self._metrics["queue_peak_size"] = current_queue
            logger.debug(f"      Queue size: {len(self._message_queue)}")
            self._last_monitor_line_time = time.time()

        self._stop_monitor()

    def _message_worker(self) -> None:
        """Background worker thread that processes messages from queue."""
        logger.info("🔄 Message worker running...")
        last_msg_arrival_time = None
        in_batch_mode = False
        last_prioritize_time = time.time()
        prioritize_interval = 5.0  # Re-prioritize queue every 5 seconds

        # Batch processing config
        batch_enabled = bool(self.bot_cfg.get("batch_enabled", True))
        batch_window = float(self.bot_cfg.get("batch_time_window_sec", 2.0))
        min_batch_size = int(self.bot_cfg.get("batch_min_messages", 3))

        while self.running:
            current_queue_size = len(self._message_queue)

            if current_queue_size == 0:
                time.sleep(0.2)  # Check queue every 200ms
                last_msg_arrival_time = None  # Reset batch tracking when queue empty
                in_batch_mode = False
                continue

            # Periodically re-prioritize queue (shorter messages first)
            now = time.time()
            if now - last_prioritize_time >= prioritize_interval and current_queue_size > 1:
                self._prioritize_queue()
                last_prioritize_time = now

            # BATCH AGGREGATION: If enabled and enough messages arrived within time window
            if batch_enabled and current_queue_size >= min_batch_size:
                # Check if newest message is within batch window
                newest_msg_time = self._message_queue[-1].get("timestamp", 0)
                oldest_msg_time = self._message_queue[0].get("timestamp", 0)
                time_span = newest_msg_time - oldest_msg_time

                if time_span < batch_window:
                    logger.info(f"📦 BATCH MODE: Processing {current_queue_size} messages together")
                    self._process_batch_messages()
                    time.sleep(1.0)  # Pause after batch processing
                    continue

            # SINGLE MESSAGE PROCESSING
            msg = self._message_queue.pop(0)
            sender_pubkey = msg["sender_pubkey"]
            sender_name = msg["sender_name"]
            text = msg["text"]
            msg_arrival_time = msg.get("timestamp", time.time())

            # Detect batch/synchronized message arrival pattern
            # If messages arrive within 1.5 seconds of each other, we're likely in "batch sync" mode
            if last_msg_arrival_time is not None:
                time_since_last = msg_arrival_time - last_msg_arrival_time
                if time_since_last < 1.5:  # Rapid message arrival
                    in_batch_mode = True
                    if self.debug_mode:
                        logger.debug(f"[BATCH MODE] Messages arriving rapidly ({time_since_last:.2f}s apart)")
                else:
                    in_batch_mode = False  # Long pause = batch finished
                    logger.debug(f"[BATCH OFF] Gap of {time_since_last:.2f}s - exiting batch mode")

            # UPDATE: Store this message's arrival time for next iteration
            last_msg_arrival_time = msg_arrival_time

            # Update queue metrics
            with self._metrics_lock:
                self._metrics["messages_processed"] += 1

            logger.info(
                f"🤖 PROCESSING: Message from [{sender_name or sender_pubkey[:16]}] ({current_queue_size} in queue) [{len(text)} chars]")
            start_time = time.time()

            # Extract metadata for AI context
            msg_metadata = msg.get("metadata")
            resp = self.call_ai(text, metadata=msg_metadata)
            elapsed = time.time() - start_time

            if not resp:
                logger.error(f"❌ AI FAILED: No response generated (took {elapsed:.1f}s)")
                continue

            # DEBUG: Log raw AI response to detect unexpected prefix characters
            logger.debug(f"RAW AI RESPONSE (first 50 chars): {repr(resp[:50])}")

            logger.info(f"✅ AI RESPONSE: Generated {len(resp)} bytes in {elapsed:.1f}s")

            ok = self.send_priv_sync(sender_pubkey, resp)
            logger.info(f"📨 PRIV SENT: {ok} to [{sender_name or sender_pubkey[:16]}]")
            status = "sent" if ok else "failed"
            self._append_message_log("out", sender_name or sender_pubkey[:16], resp, status=status)

            # 🆕 FALLBACK: Write response to shared file for web UI consumption
            self._write_response_to_file(text, resp)

            # WEBHOOK: Fire-and-forget thread to avoid deadlock
            # Creates a daemon thread that pushes to WebUI without blocking the worker
            webhook_thread = threading.Thread(
                target=self._webhook_fire_and_forget,
                args=(text, resp),
                daemon=True
            )
            webhook_thread.start()

            # Adaptive delay: longer delay in batch mode (synced messages from node reconnect)
            if in_batch_mode and current_queue_size > 0:
                # More messages waiting - this is likely a batch sync situation
                delay = 1.0  # 1 second between batch messages to let network clear
                if self.debug_mode:
                    logger.debug(f"[BATCH DELAY] Waiting {delay}s before next message ({current_queue_size} remain)...")
            else:
                delay = 0.1  # Normal 100ms delay between messages

            time.sleep(delay)

    def _write_response_to_file(self, user_msg: str, ai_response: str) -> None:
        """
        Write AI response to a file for web UI consumption.
        Workaround for unidirectional meshcore routing.
        """
        try:
            import json
            response_file = "ai_responses.jsonl"
            entry = {
                "timestamp": time.time(),
                "user_message": user_msg[:100],
                "ai_response": ai_response,
            }
            with open(response_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            logger.debug(f"💾 Response written to {response_file}")
        except Exception as e:
            logger.debug(f"Could not write response file: {e}")

    def _process_batch_messages(self) -> None:
        """
        Process multiple messages in batch mode with aggregated AI call.
        Extracts all messages from queue, asks AI to respond to all together,
        then parses and sends individual responses.
        """
        # Extract all messages from queue
        batch_messages = []
        while self._message_queue:
            batch_messages.append(self._message_queue.pop(0))

        if not batch_messages:
            return

        batch_size = len(batch_messages)
        logger.info(f"📦 Processing {batch_size} messages in batch mode")

        # Build aggregated prompt
        aggregated_prompt = f"I received {batch_size} messages. Please respond to each one separately, numbering your responses 1-{batch_size}:\n\n"
        for i, msg in enumerate(batch_messages, 1):
            text = msg["text"][:200]  # Limit to 200 chars per message
            sender_name = msg.get("sender_name", "Unknown")
            aggregated_prompt += f"{i}. From {sender_name}: {text}\n"

        # Use metadata from first message (batch context)
        first_metadata = batch_messages[0].get("metadata") if batch_messages else None

        # Call AI with aggregated prompt
        start_time = time.time()
        resp = self.call_ai(aggregated_prompt, metadata=first_metadata)
        elapsed = time.time() - start_time

        if not resp:
            logger.error(f"❌ BATCH AI FAILED: No response generated (took {elapsed:.1f}s)")
            # Fall back to individual processing
            for msg in batch_messages:
                self._message_queue.append(msg)  # Re-queue
            return

        logger.info(f"✅ BATCH AI RESPONSE: Generated {len(resp)} bytes in {elapsed:.1f}s for {batch_size} messages")

        # Parse numbered responses
        responses = self._parse_numbered_responses(resp, batch_size)

        # Send individual responses
        for i, msg in enumerate(batch_messages):
            sender_pubkey = msg["sender_pubkey"]
            sender_name = msg.get("sender_name", sender_pubkey[:16])
            response_text = responses.get(i + 1, "Sorry, I couldn't process your message in batch mode.")

            with self._metrics_lock:
                self._metrics["messages_processed"] += 1

            ok = self.send_priv_sync(sender_pubkey, response_text)
            logger.info(f"📨 BATCH PRIV SENT: {ok} to [{sender_name}]")
            status = "sent" if ok else "failed"
            self._append_message_log("out", sender_name, response_text, status=status)

            time.sleep(0.3)  # Small delay between sends

    def _parse_numbered_responses(self, text: str, expected_count: int) -> dict:
        """
        Parse numbered responses from AI output.
        Expected format: "1. Response text\n2. Response text\n..."
        Returns dict of {number: response_text}
        """
        responses = {}
        lines = text.split('\n')
        current_num = None
        current_text = []

        for line in lines:
            # Check for numbered line (e.g., "1. " or "1) ")
            match = re.match(r'^(\d+)[\.\)]\s*(.*)$', line.strip())
            if match:
                # Save previous response
                if current_num is not None and current_text:
                    responses[current_num] = ' '.join(current_text).strip()

                # Start new response
                current_num = int(match.group(1))
                current_text = [match.group(2)] if match.group(2) else []
            elif current_num is not None:
                # Continue current response
                current_text.append(line.strip())

        # Save last response
        if current_num is not None and current_text:
            responses[current_num] = ' '.join(current_text).strip()

        logger.debug(f"Parsed {len(responses)} numbered responses from batch output")
        return responses


def main() -> None:
    force_utf8_console_output()
    cfg = load_config()
    validate_config(cfg)

    # Setup logging with rotation
    log_level = cfg.get("system", {}).get("log_level", "INFO")
    enable_file_logging = cfg.get("system", {}).get("enable_file_logging", True)
    global logger
    logger = setup_logging(log_level, enable_file_logging)

    # Check COM port availability before starting bot
    port = cfg.get("radio", {}).get("port", "COM6")
    if not check_port_available(port):
        logger.error("❌ Cannot start: COM port not available")
        sys.exit(1)

    bot = AutoReplyBot(cfg)
    bot._start_health_server()
    bot._start_openwebui()
    # Wait for OpenWebUI to load models (can take 120-180s on slower machines)
    timeout = int(cfg.get("ai", {}).get("openwebui_startup_timeout", 180))
    bot._wait_for_openwebui(timeout=timeout)

    # Use library-based polling instead of CLI monitor
    use_library_mode = bool(cfg.get("bot_behavior", {}).get("use_library_polling", True))

    if use_library_mode:
        logger.info("🔄 Using LIBRARY-BASED polling (get_msg)")
        bot.monitor_loop_library()
    else:
        logger.info("🔄 Using CLI monitor (meshcore-cli ms)")
        bot.monitor_loop()


if __name__ == "__main__":
    main()
