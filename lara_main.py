#!/usr/bin/env python3
# lara_main.py
# Full regenerated file — binary-interactive meshcore-cli (Windows-safe)
# - uses bytes for stdin/stdout to avoid OSError: [Errno 22] Invalid argument on Windows
# - monitor runs in its own subprocess, stopped/restarted around interactive sends
# - byte-aware chunking, robust cleanup

import subprocess
import asyncio
import shutil
import re
import time
import logging
import yaml
import requests
import json
import sys
import os
import signal
import threading
import hashlib
from typing import Optional, List, Tuple

# Try to import meshcore library for async sends (fallback to CLI if failing)
try:
    from meshcore import MeshCore, EventType
    HAS_MESHCORE_LIB = True
except ImportError:
    HAS_MESHCORE_LIB = False
    logger_temp = logging.getLogger("LaraMain")
    logger_temp.warning("meshcore library not available — will use CLI-based sends (may fail on Windows)")

# -------------------------
# Config
# -------------------------
CONFIG_PATH = "lara_config.yaml"
try:
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f) or {}
except FileNotFoundError:
    print("❌ Hiba: A lara_config.yaml nem található!")
    sys.exit(1)

# -------------------------
# Logging
# -------------------------
log_level = cfg.get('system', {}).get('log_level', 'INFO')
numeric_level = getattr(logging, log_level.upper(), logging.INFO)
logging.basicConfig(level=numeric_level, format='%(asctime)s - [LARA-CORE] - %(message)s')
logger = logging.getLogger("LaraMain")

# -------------------------
# subprocess.run fallback wrapper
# -------------------------
def _has_subprocess_run() -> bool:
    return hasattr(subprocess, "run") and callable(getattr(subprocess, "run"))

class _Completed:
    def __init__(self, returncode: int, stdout: Optional[str], stderr: Optional[str]):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

def safe_run(cmd: List[str], timeout: Optional[float] = None, capture_output: bool = True, text: bool = True, encoding: Optional[str] = None, errors: Optional[str] = None) -> _Completed:
    """
    Use subprocess.run if available, otherwise Popen+communicate fallback.
    """
    if _has_subprocess_run():
        try:
            kwargs = {"capture_output": capture_output, "text": text, "timeout": timeout}
            if encoding is not None:
                kwargs["encoding"] = encoding
            if errors is not None:
                kwargs["errors"] = errors
            res = subprocess.run(cmd, **kwargs)
            return _Completed(res.returncode, res.stdout, res.stderr)
        except subprocess.TimeoutExpired:
            raise
        except Exception as e:
            logger.error(f"safe_run exception: {e}")
            return _Completed(1, None, str(e))
    # fallback
    try:
        p = subprocess.Popen(cmd,
                             stdout=subprocess.PIPE if capture_output else None,
                             stderr=subprocess.PIPE if capture_output else None,
                             text=text,
                             encoding=encoding,
                             errors=errors)
        out, err = p.communicate(timeout=timeout)
        return _Completed(p.returncode, out, err)
    except subprocess.TimeoutExpired:
        p.kill()
        raise
    except Exception as e:
        logger.error(f"safe_run fallback exception: {e}")
        return _Completed(1, None, str(e))

# -------------------------
# Utilities
# -------------------------
def _sanitize_text(s: str) -> str:
    if s is None:
        return ""
    s = str(s)
    s = s.replace("\r", " ").replace("\n", " ")
    s = re.sub(r"[^\x20-\x7E\u00A0-\uFFFF]", "?", s)
    return s.strip()

def _byte_chunk_text(text: str, max_bytes: int) -> List[str]:
    """Chunk text by UTF-8 byte length — do not split multi-byte chars."""
    if not text:
        return []
    chunks = []
    buf = ""
    for ch in text:
        if len((buf + ch).encode('utf-8')) > max_bytes:
            if buf:
                chunks.append(buf)
            buf = ch
        else:
            buf += ch
    if buf:
        chunks.append(buf)
    return chunks

# -------------------------
# LaraApp
# -------------------------
class LaraApp:
    def __init__(self):
        self.radio_cfg = cfg.get('radio', {})
        self.ai_cfg = cfg.get('ai', {})
        self.bot_cfg = cfg.get('bot_behavior', {})
        self.running = True
        self.memory = []
        self.monitor_proc: Optional[subprocess.Popen] = None

        # Determine port and node_name: check for active_instance first, fallback to radio config
        self.default_port = str(self.radio_cfg.get('port', 'COM4'))
        self.node_name = str(self.radio_cfg.get('node_name', 'Enomee'))
        nodes = cfg.get('nodes', {})
        for node_key, node_data in nodes.items():
            if isinstance(node_data, dict) and node_data.get('active_instance', False):
                self.default_port = str(node_data.get('port', self.default_port))
                self.node_name = str(node_data.get('name', self.node_name))
                logger.info(f"✅ Active instance: node '{node_key}' ({self.node_name}) on port {self.default_port}")
                break
        # Prefer human-friendly room name (radio.room_name) for interactive sends,
        # fallback to pubkey (room_name) for library/fallback; can also be manually overridden
        self.room_name_friendly = str(self.radio_cfg.get('radio.room_name', '')) or str(self.radio_cfg.get('room_name', ''))
        self.room_name = str(self.radio_cfg.get('room_name', ''))
        # radio_enabled allows disabling any actual TX for safe testing
        self.radio_enabled = bool(self.radio_cfg.get('enabled', True))
        self.chunk_bytes = int(self.bot_cfg.get('chunk_bytes', 200))
        self.send_retries = int(self.bot_cfg.get('send_retries', 1))
        self.send_retry_delay = float(self.bot_cfg.get('send_retry_delay', 0.5))

        self._send_lock = threading.Lock()

        # Ctrl+C handler
        try:
            signal.signal(signal.SIGINT, lambda sig, frame: self._signal_stop(sig))
        except Exception:
            pass

    def _signal_stop(self, sig):
        logger.info("⚠️ Signal received — shutting down...")
        self.running = False
        self._cleanup_monitor()

    # AI integration (unchanged)
    def call_ai(self, user_text: str) -> Optional[str]:
        api_url = self.ai_cfg.get('api_url')
        api_key = self.ai_cfg.get('api_key')
        if not api_url or not api_key:
            logger.warning("⚠️ AI API nincs konfigurálva (api_url/api_key hiányzik).")
            return None

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        self.memory.append({"role": "user", "content": user_text})
        memory_limit = int(self.ai_cfg.get('memory_limit', 20))
        messages = self.memory[-memory_limit:]

        payload = {"model": self.ai_cfg.get('model_id', 'mistral'), "messages": messages}
        try:
            logger.debug(f"🧠 AI request -> {api_url} (len={len(user_text)})")
            res = requests.post(api_url, headers=headers, json=payload, timeout=45)
            logger.debug(f"🧠 AI HTTP status: {res.status_code}")
            if res.status_code == 200:
                j = res.json()
                try:
                    answer = j['choices'][0]['message']['content']
                except Exception:
                    logger.error("❌ AI válasz formátum ismeretlen (debug: full json).")
                    logger.debug(json.dumps(j, ensure_ascii=False))
                    return None
                self.memory.append({"role": "assistant", "content": answer})
                return answer
            else:
                logger.error(f"❌ AI API hiba: {res.status_code} - {res.text[:300]}")
        except Exception as e:
            logger.error(f"❌ AI hívás sikertelen: {e}")
        return None

    # -------------------------
    # LIBRARY-BASED ASYNC ROOM SEND (Windows-safe)
    # -------------------------
    async def send_room_message_async(self, text: str) -> bool:
        """
        Send room message using meshcore Python library (async, no interactive CLI).
        This avoids Windows console errors from prompt_toolkit.
        """
        if not HAS_MESHCORE_LIB:
            logger.warning("meshcore library not available — returning False.")
            return False

        if not self.radio_enabled:
            logger.info("📡 Radio disabled by config — skipping send.")
            return True

        text = _sanitize_text(text)
        if not text:
            logger.warning("⚠️ Empty message — not sending.")
            return False

        port = str(self.default_port)
        room_pubkey = str(self.room_name)
        room_key = str(self.radio_cfg.get('room_key', ''))

        try:
            logger.debug(f"🔗 Connecting to MeshCore on port {port}...")
            mesh = await MeshCore.create_serial(port)

            # Fetch contacts
            contacts_res = await mesh.commands.get_contacts()
            if contacts_res.type == EventType.ERROR:
                logger.error(f"get_contacts failed: {contacts_res.payload}")
                await mesh.disconnect()
                return False

            contacts = contacts_res.payload or {}
            logger.debug(f"Found {len(contacts)} contacts")

            # Find room object by pubkey
            room_obj = contacts.get(room_pubkey)
            if not room_obj:
                logger.error(f"Room with pubkey {room_pubkey[:16]}... not found in contacts.")
                await mesh.disconnect()
                return False

            logger.debug(f"Target room: {room_obj.get('adv_name', 'Unknown')}")

            # Set channel key if provided
            if room_key:
                secret16 = hashlib.sha256(room_key.encode('utf-8')).digest()[:16]
                logger.debug("Setting channel with derived secret...")
                set_res = await mesh.commands.set_channel(1, room_pubkey, secret16)
                if set_res.type == EventType.ERROR:
                    logger.error(f"set_channel failed: {set_res.payload}")
                    await mesh.disconnect()
                    return False
                await asyncio.sleep(0.35)

            # Send message chunks
            chunks = _byte_chunk_text(text, self.chunk_bytes)
            for i, chunk in enumerate(chunks, 1):
                logger.debug(f"📤 Sending chunk {i}/{len(chunks)}: {chunk[:50]}...")
                send_res = await mesh.commands.send_msg(room_obj, chunk)
                if send_res.type == EventType.ERROR:
                    logger.error(f"send_msg chunk {i} failed: {send_res.payload}")
                    await mesh.disconnect()
                    return False
                await asyncio.sleep(0.2)

            await mesh.disconnect()
            logger.info("✅ Message sent successfully via library.")
            return True

        except Exception as e:
            logger.error(f"❌ Library send failed: {e}")
            return False

    def send_room_message_sync_wrapper(self, text: str) -> bool:
        """
        Synchronous wrapper for the async send_room_message_async.
        """
        try:
            result = asyncio.run(self.send_room_message_async(text))
            return result
        except Exception as e:
            logger.error(f"❌ Async wrapper error: {e}")
            return False

    # -------------------------
    # INTERACTIVE SEND (binary pipes)
    # -------------------------
    def send_to_room(self, text: str, timeout: float = 25.0) -> bool:
        """
        Send message to room using meshcore-cli interactive mode (binary pipes for Windows safety).
        Workflow:
          1. Start meshcore-cli in interactive mode (binary pipes)
          2. Send: to <room>\\n
          3. Send: "<message>\\n (quote prefix for room server)
          4. Send: quit\\n
        """
        # if radio is disabled by config, skip any interactive sends
        if not self.radio_enabled:
            logger.info("📡 Radio disabled by config — skipping send.")

            return True

        # Use friendly room name if available, else pubkey
        room = str(self.room_name_friendly) if self.room_name_friendly else str(self.room_name)
        port = str(self.default_port)
        bin_path = shutil.which("meshcore-cli")
        if not bin_path:
            logger.error("❌ meshcore-cli nem található a PATH-on!")
            return False

        text = _sanitize_text(text)
        if not text:
            logger.warning("⚠️ Üres üzenet — nem küldöm.")
            return False

        chunks = _byte_chunk_text(text, self.chunk_bytes)
        if not chunks:
            logger.warning("⚠️ Nincsenek chunkok — kilépés.")
            return False

        with self._send_lock:
            monitor_was_running = self.monitor_proc is not None
            if monitor_was_running:
                logger.debug("🔁 Monitor fut — leállítom a monitor-t a küldéshez.")
                self._cleanup_monitor()
                time.sleep(0.6)

            try:
                # Start interactive meshcore-cli process with text encoding (Windows safe)
                proc = subprocess.Popen(
                    [bin_path, "-s", port],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    encoding='utf-8',
                    errors='replace'
                )
            except Exception as e:
                logger.error(f"❌ meshcore-cli indítás sikertelen: {e}")
                if monitor_was_running:
                    self._start_monitor()
                return False

            try:
                # Build all commands at once
                cmd_lines = [f"to {room}"]
                
                # Add each chunk with quote prefix (required for room server)
                for idx, ch_text in enumerate(chunks, start=1):
                    logger.info(f"📡 Küldés chunk {idx}/{len(chunks)}: {ch_text[:80]}")
                    cmd_lines.append(f'"{ch_text}')
                
                # Add quit command
                cmd_lines.append("quit")
                
                # Join all commands with newline
                all_input = "\n".join(cmd_lines) + "\n"
                
                # Send all at once using communicate()
                try:
                    stdout, stderr = proc.communicate(input=all_input, timeout=timeout)
                    logger.debug(f"🔍 CLI stdout:\n{stdout}")
                    if stderr:
                        logger.debug(f"🔍 CLI stderr:\n{stderr}")
                except subprocess.TimeoutExpired:
                    logger.error(f"❌ meshcore-cli timeout (>= {timeout}s)")
                    proc.kill()
                    if monitor_was_running:
                        self._start_monitor()
                    return False

                logger.info("✅ Interactive room send sikeres.")
                return True

            except Exception as e:
                logger.error(f"❌ Interactive send exception: {e}")
                try:
                    proc.kill()
                except Exception:
                    pass
                if monitor_was_running:
                    self._start_monitor()
                return False

            finally:
                # Ensure process is cleaned up
                try:
                    if proc.poll() is None:
                        proc.terminate()
                        try:
                            proc.wait(timeout=1)
                        except Exception:
                            proc.kill()
                except Exception:
                    pass
                # Restart monitor if it was running
                if monitor_was_running:
                    time.sleep(0.4)
                    self._start_monitor()

    def send_via_library(self, text: str) -> bool:
        """
        Fallback: use the library-backed sender in meshcore_send.py (async) to send the message.
        """
        # if radio is disabled by config, skip library sends as well
        if not self.radio_enabled:
            logger.info("📡 Radio disabled by config — skipping library send.")
            return True

        try:
            # import on demand so presence of meshcore package is optional
            import meshcore_send
        except Exception as e:
            logger.warning(f"⚠️ Library fallback not available (couldn't import meshcore_send): {e}")
            return False

        port = str(self.default_port)
        room = str(self.room_name)
        room_key = str(self.radio_cfg.get('room_key', '')).strip() or None
        try:
            logger.info("🔁 Próbálkozás könyvtáras fallback küldéssel (meshcore)...")
            wait_for_ack = bool(self.bot_cfg.get('wait_for_ack', True))
            res = asyncio.run(meshcore_send.send_room_message(port=port, room_input=room, message=text, room_key=room_key, wait_for_ack=wait_for_ack))
            payload = None
            ok = False
            if isinstance(res, (tuple, list)):
                ok = bool(res[0])
                payload = res[1] if len(res) > 1 else None
            else:
                ok = bool(res)

            logger.info(f"Library fallback result: {ok}")
            # surface useful payload hints
            try:
                if payload and isinstance(payload, dict):
                    exp = payload.get('expected_ack')
                    sug = payload.get('suggested_timeout')
                    if exp is not None:
                        # show hex-friendly expected ack
                        try:
                            logger.info(f"Library send expected_ack: {exp.hex() if isinstance(exp, (bytes,bytearray)) else repr(exp)}")
                        except Exception:
                            logger.info(f"Library send expected_ack: {repr(exp)}")
                    if sug is not None:
                        logger.info(f"Library send suggested_timeout (ms): {sug}")
                    # If an expected_ack was provided, check the monitor output for it
                    try:
                        exp_hex = None
                        if isinstance(exp, (bytes, bytearray)):
                            exp_hex = exp.hex()
                        elif isinstance(exp, str):
                            # maybe already hex string
                            exp_hex = exp
                        if exp_hex and self.monitor_proc:
                            logger.info("🔎 Waiting up to 5s for expected ACK in radio monitor...")
                            fd = None
                            try:
                                fd = self.monitor_proc.stdout.fileno()
                                try:
                                    os.set_blocking(fd, False)
                                except Exception:
                                    pass
                            except Exception:
                                fd = None

                            buf = b""
                            deadline = time.time() + 5.0
                            seen = False
                            while time.time() < deadline:
                                try:
                                    if fd is None:
                                        break
                                    chunk = None
                                    try:
                                        chunk = os.read(fd, 4096)
                                    except BlockingIOError:
                                        chunk = b""
                                    except Exception:
                                        chunk = b""
                                    if not chunk:
                                        time.sleep(0.05)
                                        continue
                                    buf += chunk
                                    while b"\n" in buf:
                                        line, buf = buf.split(b"\n", 1)
                                        try:
                                            s = line.decode('utf-8', errors='replace').strip()
                                        except Exception:
                                            s = ''
                                        if not s.startswith('{'):
                                            continue
                                        try:
                                            # quick string match for expected ack hex
                                            if exp_hex.lower() in s.lower():
                                                seen = True
                                                break
                                        except Exception:
                                            pass
                                    if seen:
                                        break
                                except Exception:
                                    time.sleep(0.05)
                            try:
                                if fd is not None:
                                    try:
                                        os.set_blocking(fd, True)
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                            if seen:
                                logger.info("✅ Expected ACK seen in monitor within 5s.")
                            else:
                                logger.info("⚠️ No expected ACK seen in monitor within 5s.")
                    except Exception:
                        logger.debug("ACK monitoring attempt failed (non-fatal).")
            except Exception:
                pass

            return bool(ok)
        except Exception as e:
            logger.exception(f"Exception during library fallback send: {e}")
            return False

    def send_message(self, text: str) -> bool:
        """Try library-based send first (Windows-safe), fallback to interactive CLI.

        If `radio.enabled` is false in config, short-circuit and do not transmit.
        """
        if not self.radio_enabled:
            logger.info("📡 Radio disabled by config — not sending message.")
            return True

        # Try library-based send first (Windows-safe, no console issues)
        if HAS_MESHCORE_LIB:
            logger.debug("📚 Trying library-based room send...")
            ok = self.send_room_message_sync_wrapper(text)
            if ok:
                return True
            logger.warning("⚠️ Library send failed — trying interactive CLI fallback...")

        # Fallback to interactive CLI
        ok = self.send_to_room(text)
        if ok:
            return True

        logger.error("❌ All send methods failed.")
        return False

    def send_reply_to_sender(self, text: str, sender: str) -> bool:
        """
        Send AI response directly to the message sender (node name or contact).
        Uses meshcore-cli interactive mode to send PRIV message.
        """
        if not self.radio_enabled:
            logger.info("📡 Radio disabled by config — not sending reply.")
            return True
        
        if not sender or sender == "Ismeretlen":
            logger.warning("⚠️ Sender ismeretlen — alapértelmezett roomba küldés helyette.")
            return self.send_message(text)

        port = str(self.default_port)
        bin_path = shutil.which("meshcore-cli")
        if not bin_path:
            logger.error("❌ meshcore-cli nem található a PATH-on!")
            return False

        text = _sanitize_text(text)
        if not text:
            logger.warning("⚠️ Üres válasz — nem küldöm.")
            return False

        chunks = _byte_chunk_text(text, self.chunk_bytes)
        if not chunks:
            logger.warning("⚠️ Nincsenek chunkok — kilépés.")
            return False

        with self._send_lock:
            monitor_was_running = self.monitor_proc is not None
            if monitor_was_running:
                logger.debug("🔁 Monitor fut — leállítom a monitor-t a küldéshez.")
                self._cleanup_monitor()
                time.sleep(0.6)

            try:
                proc = subprocess.Popen(
                    [bin_path, "-s", port],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    encoding='utf-8',
                    errors='replace'
                )
            except Exception as e:
                logger.error(f"❌ meshcore-cli indítás sikertelen: {e}")
                if monitor_was_running:
                    self._start_monitor()
                return False

            try:
                # Build commands to reply to sender (PRIV message via 'to <sender>' + quoted message)
                cmd_lines = [f"to {sender}"]
                
                for idx, ch_text in enumerate(chunks, start=1):
                    logger.info(f"📡 Válasz küldés {sender}-nek chunk {idx}/{len(chunks)}: {ch_text[:80]}")
                    # For PRIV messages after 'to <sender>', use quoted format (same as room)
                    # meshcore-cli will interpret this as a message to the selected contact
                    cmd_lines.append(f'"{ch_text}')
                
                cmd_lines.append("quit")
                
                all_input = "\n".join(cmd_lines) + "\n"
                
                try:
                    stdout, stderr = proc.communicate(input=all_input, timeout=25.0)
                    logger.debug(f"🔍 Reply CLI stdout:\n{stdout}")
                    if stderr:
                        logger.debug(f"🔍 Reply CLI stderr:\n{stderr}")
                except subprocess.TimeoutExpired:
                    logger.error(f"❌ meshcore-cli timeout reply-nél")
                    proc.kill()
                    if monitor_was_running:
                        self._start_monitor()
                    return False

                logger.info(f"✅ Válasz sikeresen elküldve {sender}-nek.")
                return True

            except Exception as e:
                logger.error(f"❌ Reply send exception: {e}")
                try:
                    proc.kill()
                except Exception:
                    pass
                if monitor_was_running:
                    self._start_monitor()
                return False

            finally:
                try:
                    if proc.poll() is None:
                        proc.terminate()
                        try:
                            proc.wait(timeout=1)
                        except Exception:
                            proc.kill()
                except Exception:
                    pass
                if monitor_was_running:
                    time.sleep(0.4)
                    self._start_monitor()

    # -------------------------
    # Monitor control (start/loop/cleanup)
    # -------------------------
    def _start_monitor(self):
        if self.monitor_proc:
            return
        bin_path = shutil.which("meshcore-cli")
        if not bin_path:
            logger.error("❌ meshcore-cli hiányzik! Monitor nem indítható.")
            return
        port = str(self.default_port)
        cmd = [bin_path, "-j", "-s", port, "ms"]
        logger.info(f"📡 Indítom a monitor: {' '.join(cmd)}")
        try:
            self.monitor_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0
            )
        except Exception as e:
            logger.error(f"❌ Monitor indítás sikertelen: {e}")
            self.monitor_proc = None

    def monitor_loop(self):
        self._start_monitor()
        if not self.monitor_proc:
            logger.error("❌ Monitor indítható — kilépés.")
            return

        try:
            # read binary lines and decode per-line
            logger.info("📡 Monitor loop started, listening for messages...")
            while self.running:
                try:
                    raw = self.monitor_proc.stdout.readline()
                except Exception as e:
                    logger.error(f"Error reading from monitor: {e}")
                    raw = b""
                if not raw:
                    # logger.debug("No data from monitor")
                    time.sleep(0.05)
                    continue
                try:
                    line = raw.decode('utf-8', errors='replace').strip()
                except Exception as e:
                    logger.error(f"Decode error: {e}")
                    line = ""
                if not line:
                    continue
                logger.debug(f"Monitor raw line: {line[:200]}")
                if not line.startswith('{'):
                    logger.debug(f"Non-JSON monitor line: {line[:200]}")
                    continue
                try:
                    data = json.loads(line)
                    logger.debug(f"Parsed JSON: {data}")
                except json.JSONDecodeError as e:
                    logger.error(f"JSON decode error: {e} for line: {line[:200]}")
                    continue

                if "text" in data:
                    incoming = data.get("text", "")
                    # Extract sender from pubkey_prefix (primary), fallback to "from"
                    pubkey_prefix = data.get("pubkey_prefix", "")
                    sender = None
                    
                    if pubkey_prefix:
                        # Try to resolve pubkey_prefix to node name from config
                        nodes = cfg.get("nodes", {})
                        for node_key, node_cfg in nodes.items():
                            node_pubkey = str(node_cfg.get("pubkey", "")).lower()
                            if node_pubkey.startswith(pubkey_prefix.lower()):
                                sender = node_cfg.get("name", node_key)
                                break
                        if not sender:
                            sender = pubkey_prefix  #  fallback to prefix itself
                    
                    if not sender:
                        sender = data.get("from", "Ismeretlen")
                    
                    logger.info(f"📨 Bejövő [{sender}]: {incoming[:200]}")
                    if sender == self.node_name:
                        logger.debug("Önhurok — átugorva.")
                        continue
                    if self.bot_cfg.get('active', True) and incoming:
                        resp = None
                        try:
                            logger.info(f"🤖 AI feldolgozása: {sender} üzenetéből")
                            resp = self.call_ai(incoming)
                        except Exception as e:
                            logger.error(f"AI feldolgozási hiba: {e}")
                            resp = None
                        if resp:
                            # ✅ Send AI response to room (both sides see it)
                            # Note: Using room send instead of PRIV (Windows CLI limitations)
                            ok = self.send_message(resp)
                            logger.info(f"📡 AI válasz a roomba küldve: {ok}")
        except KeyboardInterrupt:
            logger.info("⚠️ Monitor: KeyboardInterrupt.")
        except Exception as e:
            logger.error(f"⚠️ Monitor exception: {e}")
        finally:
            self._cleanup_monitor()

    def _cleanup_monitor(self):
        self.running = False
        if self.monitor_proc:
            logger.info("🧹 Monitor lezárása...")
            try:
                self.monitor_proc.terminate()
                self.monitor_proc.wait(timeout=2)
            except Exception:
                try:
                    self.monitor_proc.kill()
                except Exception:
                    pass
            try:
                if self.monitor_proc.stdout:
                    try:
                        self.monitor_proc.stdout.close()
                    except Exception:
                        pass
            except Exception:
                pass
            self.monitor_proc = None

    # -------------------------
    # Start lifecycle
    # -------------------------
    def start(self):
        bin_path = shutil.which("meshcore-cli")
        if not bin_path:
            logger.error("❌ meshcore-cli nem található a PATH-on — telepítsd vagy add a PATH-hoz.")
            return

        try:
            port = str(self.default_port)
            room_id = str(self.room_name)
            room_key = str(self.radio_cfg.get('room_key', '')).strip()

            if room_key:
                logger.info("🔑 Csatorna kulcs szinkronizálása...")
                setup_cmd = [bin_path, "-s", port, "set_channel", "1", room_id, room_key]
                try:
                    res = safe_run(setup_cmd, timeout=10, capture_output=True, text=True, encoding='utf-8', errors='replace')
                    logger.debug(f"Set channel stdout: {res.stdout}")
                    logger.debug(f"Set channel stderr: {res.stderr}")
                    if res.returncode != 0:
                        logger.warning(f"Set_channel visszatérési kód: {res.returncode}")
                except Exception as e:
                    logger.warning(f"Set channel parancs futtatása sikertelen: {e}")
                time.sleep(1.0)

            # Note: Disabled startup test send due to Windows interactive CLI issues.
            # Monitor will listen for actual incoming messages instead.
            # logger.info("🧪 Indítási teszt üzenet generálása...")
            # test_prompt = "how are you?"
            # test_resp = self.call_ai(test_prompt)
            # if test_resp:
            #     ok = self.send_message(test_resp)
            #     logger.info(f"Teszt küldés eredménye: {ok}")
            # else:
            #     logger.warning("Teszt AI hívás nem adott választ — továbbmegyünk a monitorra.")

            self.running = True
            logger.info("🚀 Starting monitor loop (waiting for incoming messages)...")
            self.monitor_loop()

        except KeyboardInterrupt:
            logger.info("👋 Lara leállt (KeyboardInterrupt).")
            self.running = False
        except Exception as e:
            logger.error(f"💥 Kritikus hiba a start() során: {e}")
        finally:
            self._cleanup_monitor()

# -------------------------
# Main
# -------------------------
if __name__ == "__main__":
    app = LaraApp()
    app.start()
