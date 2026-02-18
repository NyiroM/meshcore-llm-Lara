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
import os
import re
import select
import shutil
import signal
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse
from typing import Optional

import requests
import yaml

try:
    from meshcore import MeshCore, EventType
except ImportError:
    print("ERROR: meshcore library not found. Install: pip install meshcore")
    sys.exit(1)

# ============================================================================
# FIX: Force UTF-8 encoding for Windows console (handles emoji in logs)
# ============================================================================
if sys.platform == "win32":
    import io
    # Force UTF-8 for stderr (where logger outputs)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    # Force UTF-8 for stdout too
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    # Also set environment variable for subprocess
    os.environ["PYTHONIOENCODING"] = "utf-8"

CONFIG_PATH = "lara_config.yaml"
COM_BUSY_HINT = "COM port appears busy. Please close the MeshCore web app (or any app using the port) and retry."

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [AUTO-REPLY] - %(message)s")
logger = logging.getLogger("AutoReply")


def load_config(path: str = CONFIG_PATH) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        sys.exit(1)


def _sanitize_text(s: str) -> str:
    if s is None:
        return ""
    s = str(s)
    s = s.replace("\r", " ").replace("\n", " ")
    s = re.sub(r"[^\x20-\x7E\u00A0-\uFFFF]", "?", s)
    return s.strip()


def _byte_chunk_text(text: str, max_bytes: int) -> list[str]:
    if not text:
        return []
    chunks = []
    buf = ""
    for ch in text:
        if len((buf + ch).encode("utf-8")) > max_bytes:
            if buf:
                chunks.append(buf)
            buf = ch
        else:
            buf += ch
    if buf:
        chunks.append(buf)
    return chunks


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
        self._last_monitor_line_time = time.time()
        self._last_seen_messages: dict[str, float] = {}
        self._last_monitor_restart_time = 0.0
        self._next_monitor_start_time = 0.0
        
        # NEW: Queue for monitor lines (reader thread puts raw lines here)
        self._monitor_line_queue: list = []
        self._monitor_reader_thread: Optional[threading.Thread] = None
        
        # NEW: Persistent mesh connection for library mode
        self._persistent_mesh = None
        self._use_library_mode = False

        self.default_port = str(self.radio_cfg.get("port", "COM4"))
        self.node_name = str(self.radio_cfg.get("node_name", "Enomee"))
        
        # Get both sending and receiving ports for bidirectional operation
        self.send_port = "COM4"
        self.recv_port = "COM6"
        self.other_port = "COM6"  # For reverse direction responses
        
        nodes = cfg.get("nodes", {})
        for node_key, node_data in nodes.items():
            if isinstance(node_data, dict) and node_data.get("active_instance", False):
                self.default_port = str(node_data.get("port", self.default_port))
                self.node_name = str(node_data.get("name", self.node_name))
                logger.info(f"Active instance: node '{node_key}' ({self.node_name}) on port {self.default_port}")
                # If active node is on COM4, responses go to COM6
                self.send_port = self.default_port
                self.other_port = "COM6" if self.default_port == "COM4" else "COM4"
                break

        self.chunk_bytes = int(self.bot_cfg.get("chunk_bytes", 200))
        self.debug_mode = bool(self.bot_cfg.get("debug_auto_reply", False))
        self.use_streaming = bool(self.ai_cfg.get("streaming", True))
        if self.debug_mode:
            logging.getLogger().setLevel(logging.DEBUG)

        try:
            signal.signal(signal.SIGINT, lambda sig, frame: self.stop())
        except Exception:
            pass

    def stop(self) -> None:
        logger.info("Signal received - shutting down...")
        self.running = False
        self._stop_monitor()
        if self._message_worker_thread and self._message_worker_thread.is_alive():
            self._message_worker_thread.join(timeout=5)
        if self._openwebui_log_handle:
            try:
                self._openwebui_log_handle.close()
            except Exception:
                pass

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
        
        # Set proper environment variables for OpenWebUI
        # DATA_DIR: Where the webui.db file lives
        data_dir = self.ai_cfg.get("openwebui_data_dir") or "E:\\Users\\M\\Documents\\LLM\\Doomsday_files"
        env["DATA_DIR"] = str(data_dir)
        
        # CORS and User Agent
        cors_origin = self.ai_cfg.get("openwebui_cors_allow_origin") or "http://localhost:8080"
        user_agent = self.ai_cfg.get("openwebui_user_agent") or "OpenWebUI-User"
        env["CORS_ALLOW_ORIGIN"] = str(cors_origin)
        env["USER_AGENT"] = str(user_agent)
        
        # UTF-8 encoding for Python subprocess
        env["PYTHONIOENCODING"] = "utf-8"

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
                stdout=self._openwebui_log_handle or subprocess.DEVNULL,
                stderr=self._openwebui_log_handle or subprocess.DEVNULL,
                env=env,
                creationflags=creationflags,
            )
            logger.info("✅ OpenWebUI started (PID: %s)", self._openwebui_proc.pid)
        except Exception as e:
            logger.error(f"Failed to start OpenWebUI: {e}")

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

    def call_ai(self, user_text: str) -> Optional[str]:
        """
        Call OpenWebUI API with streaming support.
        Tries streaming first (if available), falls back to non-streaming.
        Returns the AI response which is then sent via PRIV.
        """
        api_url = self.ai_cfg.get("api_url")
        api_key = self.ai_cfg.get("api_key")
        if not api_url or not api_key:
            logger.error("AI API not configured (api_url/api_key missing).")
            return None

        self.memory.append({"role": "user", "content": user_text})
        memory_limit = int(self.ai_cfg.get("memory_limit", 20))
        messages = self.memory[-memory_limit:]
        
        if self.use_streaming:
            # Try streaming first
            logger.debug("Attempting streaming API call...")
            answer = self._call_ai_streaming(api_url, api_key, messages)
            
            if answer:
                logger.debug(f"Streaming response received: {len(answer)} bytes")
                self.memory.append({"role": "assistant", "content": answer})
                return answer
        else:
            logger.debug("Streaming disabled in config; using non-streaming API...")
        
        # Fallback to non-streaming
        logger.debug("Streaming failed or empty, trying non-streaming API...")
        answer = self._call_ai_nonstreaming(api_url, api_key, messages)
        
        if answer:
            logger.debug(f"Non-streaming response received: {len(answer)} bytes")
            self.memory.append({"role": "assistant", "content": answer})
            return answer
        
        logger.error("Both streaming and non-streaming calls failed.")
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
            logger.warning(f"Streaming connection error: {e} - FALLING BACK to stub AI")
            return self._get_stub_ai_response(messages[-1]["content"] if messages else "")
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
                user_text = messages[-1]["content"] if messages else ""
                return self._get_stub_ai_response(user_text)
            
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
            logger.error("Non-streaming call timeout (60s) - USING FALLBACK")
            user_text = messages[-1]["content"] if messages else ""
            return self._get_stub_ai_response(user_text)
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Non-streaming connection error: {e} - USING FALLBACK")
            user_text = messages[-1]["content"] if messages else ""
            return self._get_stub_ai_response(user_text)
        except Exception as e:
            logger.error(f"Non-streaming call failed: {e}")
            return None

    def _get_stub_ai_response(self, user_input: str) -> str:
        """
        Fallback AI response generator when OpenWebUI is unavailable.
        Simple rule-based responder for basic conversation.
        """
        logger.warning("🚫 OpenWebUI unavailable - using STUB AI FALLBACK")
        
        user_lower = user_input.lower().strip()
        
        # Simple keyword-based responses
        if any(w in user_lower for w in ["hello", "hi", "szia", "halló"]):
            return "Hello! I'm the meshcore AI bot. How can I help you today?"
        
        if any(w in user_lower for w in ["hobby", "like", "favorite"]):
            return "As an AI, I enjoy problem-solving and having meaningful conversations. What about you?"
        
        if any(w in user_lower for w in ["how are you", "how do you", "milyen vagy", "hogy vagy"]):
            return "I'm working well! Ready to assist with questions or discussions. How can I help?"
        
        if any(w in user_lower for w in ["help", "segítség"]):
            return "I'm here to help! Please tell me what you need assistance with."
        
        if any(w in user_lower for w in ["thanks", "thank you", "köszönöm", "köszi"]):
            return "You're welcome! Feel free to ask if you need anything else."
        
        if any(w in user_lower for w in ["what is", "mi az", "mi"]):
            return "That's an interesting question! Can you provide more details about what you'd like to know?"
        
        # Default response
        return f"I understand: '{user_input[:50]}'. Could you elaborate on that? I'm here to help with any questions."

    def push_response_to_webui(self, user_message: str, ai_response: str) -> bool:
        """
        Push AI response back to OpenWebUI for web UI display.
        Creates a conversation entry so the user sees their message + AI response in the webapp.
        """
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
                logger.info(f"✅ WEBHOOK SUCCESS: Response pushed to WebUI")
                return True
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
        text = _sanitize_text(text)
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
        text = _sanitize_text(text)
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

            chunks = _byte_chunk_text(text, self.chunk_bytes)
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
        text = _sanitize_text(text)
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

            chunks = _byte_chunk_text(text, self.chunk_bytes)
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
        Persistent connection polling loop.
        Opens serial connection ONCE and keeps it open for the lifetime of the bot.
        """
        mesh = None
        try:
            # Open connection once
            mesh = await MeshCore.create_serial(self.default_port)
            self._persistent_mesh = mesh  # Store for send operations
            logger.info(f"✅ Connected to {self.default_port} (persistent mode)")
            
            # Poll continuously without disconnecting
            while self.running:
                try:
                    await self._poll_messages_from_connection(mesh)
                except Exception as e:
                    logger.debug(f"Poll iteration error: {e}")
                
                # Wait before next poll
                await asyncio.sleep(poll_interval)
                
        except Exception as e:
            logger.error(f"Persistent connection error: {e}")
            if _looks_like_com_busy(str(e)):
                logger.error(COM_BUSY_HINT)
        finally:
            # Disconnect only on shutdown
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
            else:
                # Object format
                msg_type = getattr(msg_obj, 'type', None)
                text = getattr(msg_obj, 'text', '').strip()
                sender_pubkey_prefix = getattr(msg_obj, 'pubkey_prefix', '')
                sender_timestamp = str(getattr(msg_obj, 'sender_timestamp', ''))
            
            if self.debug_mode:
                logger.debug(f"   Extracted: type={msg_type}, text_len={len(text)}, sender={sender_pubkey_prefix[:8]}..., ts={sender_timestamp}")
            
            if msg_type != 'PRIV':
                logger.debug(f"   ❌ Skipped: Not PRIV (type={msg_type})")
                return  # Only process PRIV messages
            
            if not text:
                logger.debug(f"   ❌ Skipped: Empty text")
                return
            
            # Dedupe check
            dedupe_key = f"{sender_pubkey_prefix}|{sender_timestamp}|{text}"
            now = time.time()
            seen_ttl = float(self.bot_cfg.get("monitor_dedupe_ttl_sec", 120.0))
            
            if dedupe_key in self._last_seen_messages:
                if now - self._last_seen_messages[dedupe_key] < seen_ttl:
                    return
            
            # Prune old entries
            self._last_seen_messages = {
                k: v for k, v in self._last_seen_messages.items() if now - v < seen_ttl
            }
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
            
            # Skip self messages
            if sender_name and sender_name == self.node_name:
                logger.debug("Self message detected; skipping.")
                return
            
            logger.info(f"✉️  QUEUED: Incoming PRIV from [{sender_name or sender_pubkey_prefix}]")
            logger.debug(f"      Text: {text[:150]}...")
            
            # Queue for processing
            self._message_queue.append({
                "sender_pubkey": sender_pubkey,
                "sender_name": sender_name,
                "text": text,
                "timestamp": time.time(),
            })
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
            if dedupe_key in self._last_seen_messages:
                if now - self._last_seen_messages[dedupe_key] < seen_ttl:
                    continue
            # Prune old entries to keep memory bounded
            self._last_seen_messages = {
                k: v for k, v in self._last_seen_messages.items() if now - v < seen_ttl
            }
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

            if sender_name and sender_name == self.node_name:
                logger.debug("Self message detected; skipping.")
                continue

            logger.info(f"✉️  QUEUED: Incoming PRIV from [{sender_name or pubkey_prefix}]")
            logger.debug(f"      Text: {incoming[:150]}...")

            # Queue message for async processing instead of blocking here
            self._message_queue.append({
                "sender_pubkey": sender_pubkey,
                "sender_name": sender_name,
                "text": incoming,
                "timestamp": time.time(),  # Track when message arrived
            })
            logger.debug(f"      Queue size: {len(self._message_queue)}")
            self._last_monitor_line_time = time.time()

        self._stop_monitor()

    def _message_worker(self) -> None:
        """Background worker thread that processes messages from queue."""
        logger.info("🔄 Message worker running...")
        last_msg_arrival_time = None
        in_batch_mode = False
        queue_size_prev = 0
        
        while self.running:
            current_queue_size = len(self._message_queue)
            
            if current_queue_size == 0:
                time.sleep(0.2)  # Check queue every 200ms
                last_msg_arrival_time = None  # Reset batch tracking when queue empty
                in_batch_mode = False
                queue_size_prev = 0
                continue
            
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
            
            logger.info(f"🤖 PROCESSING: Message from [{sender_name or sender_pubkey[:16]}] ({current_queue_size} in queue)")
            start_time = time.time()
            
            resp = self.call_ai(text)
            elapsed = time.time() - start_time
            
            if not resp:
                logger.error(f"❌ AI FAILED: No response generated (took {elapsed:.1f}s)")
                continue
            
            logger.info(f"✅ AI RESPONSE: Generated {len(resp)} bytes in {elapsed:.1f}s")
            
            ok = self.send_priv_sync(sender_pubkey, resp)
            logger.info(f"📨 PRIV SENT: {ok} to [{sender_name or sender_pubkey[:16]}]")
            
            # 🆕 FALLBACK: Write response to shared file for web UI consumption
            self._write_response_to_file(text, resp)
            
            # WEBHOOK DISABLED - causes deadlock, non-critical anyway
            # webhook_ok = self.push_response_to_webui(text, resp)
            
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


def main() -> None:
    cfg = load_config()
    bot = AutoReplyBot(cfg)
    bot._start_openwebui()
    bot._wait_for_openwebui(timeout=60)  # Wait up to 60 seconds
    
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
