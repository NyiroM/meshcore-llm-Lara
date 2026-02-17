#!/usr/bin/env python3
"""
lara_cli_bridge.py

Monitor + AI bridge for MeshCore LoRa chat.

- Uses meshcore-cli for monitor (JSON mode) and interactive send (to <room> send <msg>)
- Forwards incoming messages to configured AI (ai.api_url + ai.api_key in lara_config.yaml)
- Sends AI responses to room automatically
- Seeds AI on startup with initial prompt "hi, how are you?"

Configuration: lara_config.yaml (must include radio.port and radio.room_name or radio.radio.room_name)
"""

import subprocess
import shutil
import sys
import time
import threading
import json
import re
import os
import logging
from typing import Optional, List, Dict, Any
import yaml
import requests
import hashlib

# -------------------------
# Load config
# -------------------------
CONFIG_PATH = "lara_config.yaml"
try:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
except FileNotFoundError:
    cfg = {}

# Safe config getters / backward compatibility
radio_cfg = cfg.get("radio", {})
port = str(radio_cfg.get("port") or radio_cfg.get("radio.port") or cfg.get("radio", {}).get("radio.port") or "COM4")
room_cfg = radio_cfg.get("room_name") or radio_cfg.get("radio.room_name") or cfg.get("radio", {}).get("room_name") or ""
node_name = str(radio_cfg.get("node_name") or "Enomee")
room_key_cfg = radio_cfg.get("room_key") or None

ai_cfg = cfg.get("ai", {})
ai_api_url = ai_cfg.get("api_url")
ai_api_key = ai_cfg.get("api_key")
ai_model_id = ai_cfg.get("model_id", "mistral")
ai_memory_limit = int(ai_cfg.get("memory_limit", 20))
ai_incoming_hook = ai_cfg.get("incoming_hook")  # optional URL to forward incoming messages

bot_cfg = cfg.get("bot_behavior", {})
CHUNK_BYTES = int(bot_cfg.get("chunk_bytes", bot_cfg.get("chunk_size", 200) or 200))
BOT_ACTIVE = bool(bot_cfg.get("active", True))
REPLY_TO_ALL = bool(bot_cfg.get("reply_to_all", True))

system_cfg = cfg.get("system", {})
LOG_LEVEL = system_cfg.get("log_level", "INFO")

# Optional network section for HTTP if needed (not used by default)
network_cfg = cfg.get("network", {})
http_bind = network_cfg.get("ws_bind", "127.0.0.1")
http_port = int(network_cfg.get("ws_port", 8765))

# -------------------------
# Logging
# -------------------------
numeric_level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
logging.basicConfig(level=numeric_level, format="%(asctime)s - [LARA-BRIDGE] - %(message)s")
logger = logging.getLogger("LaraBridge")

# -------------------------
# Utilities
# -------------------------
HEX64_RE = re.compile(r"^[0-9a-fA-F]{64}$")

def is_pubkey(s: str) -> bool:
    return bool(HEX64_RE.match(s.strip()))

def _sanitize_text(s: Optional[str]) -> str:
    if s is None:
        return ""
    s = str(s)
    s = s.replace("\r", " ").replace("\n", " ")
    return re.sub(r"[^\x20-\x7E\u00A0-\uFFFF]", "?", s).strip()

def _byte_chunks(text: str, max_bytes: int) -> List[str]:
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

def derive_16byte_secret(room_key: str) -> bytes:
    b = room_key.encode("utf-8")
    if len(b) == 16:
        logger.info("Room key UTF-8 pontosan 16 bájt — nyers használat.")
        return b
    digest = hashlib.sha256(b).digest()[:16]
    logger.info("Room key nem 16 bájt — SHA256 truncation 16 bájtra.")
    logger.debug(f"Derived secret hex: {digest.hex()}")
    return digest

def which_cli() -> Optional[str]:
    p = shutil.which("meshcore-cli")
    if not p:
        logger.error("meshcore-cli nincs a PATH-on — telepítsd vagy add a PATH-hoz.")
    return p

# -------------------------
# AI integration (simple)
# -------------------------
# We maintain a simple memory list like chat models expect: [{"role":"user","content":"..."}, ...]
ai_memory: List[Dict[str, str]] = []

def call_ai(user_text: str, timeout: int = 30) -> Optional[str]:
    """
    Call AI endpoint (Open WebUI / any chat completions endpoint that uses messages format).
    Uses ai_api_url and ai_api_key from config.
    """
    if not ai_api_url or not ai_api_key:
        logger.warning("AI nincs konfigurálva (api_url vagy api_key hiányzik).")
        return None

    # Append user message to memory
    ai_memory.append({"role": "user", "content": user_text})
    if len(ai_memory) > ai_memory_limit:
        ai_memory.pop(0)

    payload = {
        "model": ai_model_id,
        "messages": ai_memory
    }
    headers = {
        "Authorization": f"Bearer {ai_api_key}",
        "Content-Type": "application/json"
    }
    try:
        logger.info(f"🧠 AI hívás (prompt: {user_text[:60]!r})")
        r = requests.post(ai_api_url, headers=headers, json=payload, timeout=timeout)
        logger.debug(f"AI HTTP status: {r.status_code}")
        if r.status_code == 200:
            j = r.json()
            # Try common shapes: OpenAI-like {choices:[{message:{content:...}}]}
            try:
                answer = j['choices'][0]['message']['content']
            except Exception:
                # Try other shapes
                answer = j.get('answer') or j.get('text') or str(j)
            # store assistant message
            ai_memory.append({"role": "assistant", "content": answer})
            logger.info(f"🧠 AI válasz: {answer[:300]}")
            return answer
        else:
            logger.error(f"AI API hiba: {r.status_code} {r.text[:400]}")
    except Exception as e:
        logger.exception(f"AI hívás kivétel: {e}")
    return None

# -------------------------
# Monitor process (meshcore-cli -j -s <port> ms)
# -------------------------
monitor_proc: Optional[subprocess.Popen] = None
monitor_lock = threading.Lock()

def start_monitor():
    global monitor_proc
    with monitor_lock:
        if monitor_proc and monitor_proc.poll() is None:
            logger.debug("Monitor már fut.")
            return
        binp = which_cli()
        if not binp:
            return
        cmd = [binp, "-j", "-s", port, "ms"]
        logger.info(f"Monitor indítása: {' '.join(cmd)}")
        try:
            monitor_proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1, text=True, encoding='utf-8')
            t = threading.Thread(target=_monitor_reader_thread, args=(monitor_proc,), daemon=True)
            t.start()
        except Exception as e:
            logger.error(f"Monitor indítási hiba: {e}")
            monitor_proc = None

def stop_monitor():
    global monitor_proc
    with monitor_lock:
        if not monitor_proc:
            return
        try:
            logger.info("Monitor leállítása...")
            monitor_proc.terminate()
            monitor_proc.wait(timeout=2)
        except Exception:
            try:
                monitor_proc.kill()
            except Exception:
                pass
        finally:
            try:
                if monitor_proc.stdout:
                    monitor_proc.stdout.close()
            except Exception:
                pass
            monitor_proc = None

def _monitor_reader_thread(proc: subprocess.Popen):
    logger.debug("Monitor olvasó thread elindult.")
    if not proc.stdout:
        logger.error("Monitor stdout hiányzik.")
        return
    for raw in proc.stdout:
        if raw is None:
            break
        line = raw.strip()
        if not line:
            continue
        # try to parse JSON and only act on messages with a text field
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if "text" in obj:
            sender = obj.get("from", "Unknown")
            text = obj.get("text", "")
            logger.info(f"📥 Bejövő [{sender}] -> {text}")
            # optionally forward inbound to external AI hook
            if ai_incoming_hook:
                try:
                    requests.post(ai_incoming_hook, json={"from": sender, "text": text}, timeout=4)
                except Exception as e:
                    logger.debug(f"Incoming forward hiba: {e}")
            # If bot active, handle message with AI in background
            if BOT_ACTIVE:
                # decide whether to reply (reply_to_all or only addressed messages)
                threading.Thread(target=_handle_incoming_and_respond, args=(sender, text), daemon=True).start()
        else:
            # ignore other objects to avoid noisy logs
            pass

# -------------------------
# Handle incoming: call AI and send reply
# -------------------------
def _handle_incoming_and_respond(sender: str, message: str):
    # Basic gating: if reply_to_all false, skip unless addressed — for now reply_to_all True by default
    if not REPLY_TO_ALL:
        # Implement addressing detection here if needed
        return
    # Build prompt for AI: include sender
    prompt = f"[{sender}] {message}"
    ai_ans = call_ai(prompt)
    if ai_ans:
        # send reply to room
        logger.info(f"➡ AI válasz elküldésre előkészül: {ai_ans[:200]}")
        ok = send_to_room_interactive(ai_ans)
        logger.info(f"AI válasz elküldve: {ok}")

# -------------------------
# Interactive send (binary-safe)
# -------------------------
def send_to_room_interactive(text: str, timeout: float = 10.0) -> bool:
    """
    Stop monitor, start meshcore-cli -s <port> and write:
      to <room>
      send <chunk>
      quit
    Then restart monitor.
    room_cfg can be pubkey or adv_name; prefer pubkey.
    """
    binp = which_cli()
    if not binp:
        return False

    # determine room identifier to pass to 'to'
    room_identifier = None
    if is_pubkey(str(room_cfg)):
        room_identifier = room_cfg.lower()
    else:
        # try to resolve via meshcore python lib if available
        try:
            from meshcore import MeshCore, EventType  # type: ignore
            import asyncio
            async def resolve():
                m = await MeshCore.create_serial(port)
                try:
                    res = await m.commands.get_contacts()
                    if res.type == EventType.ERROR:
                        return None
                    contacts = res.payload or {}
                    for pk, d in contacts.items():
                        if isinstance(d, dict) and d.get("type") == 3:
                            adv = d.get("adv_name","")
                            if adv and adv.lower() == str(room_cfg).lower():
                                return pk
                    return None
                finally:
                    await m.disconnect()
            resolved = asyncio.run(resolve())
            if resolved:
                room_identifier = resolved
            else:
                room_identifier = str(room_cfg)  # fallback to adv_name
        except Exception:
            room_identifier = str(room_cfg)

    text = _sanitize_text(text)
    if not text:
        logger.warning("Üres szöveg — nem küldöm.")
        return False
    chunks = _byte_chunks(text, CHUNK_BYTES)
    logger.info(f"Üzenet darabolva {len(chunks)} chunk-ra (max {CHUNK_BYTES} bytes).")

    # stop monitor to free COM port
    stop_monitor()
    time.sleep(0.3)

    # Try non-interactive CLI first (avoids prompt_toolkit interactive mode on Windows terminals)
    try:
        logger.info("Próbálkozás non-interactive meshcore-cli 'msg' paranccsal...")
        # use JSON output for concise parsing; run with timeout bounded
        cmd = [binp, "-D", "-s", port, "-j", "msg", str(room_identifier), text]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=min(10, max(3, int(timeout))), text=True)
        except TypeError:
            # defensive: some Python versions may not accept timeout conversion above
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=10, text=True)
        logger.debug(f"meshcore-cli msg output: {res.stdout.strip()[:1000]}")
        if res.returncode == 0:
            logger.info("Non-interactive CLI send sikeres.")
            start_monitor()
            return True
        else:
            logger.warning(f"Non-interactive CLI send sikertelen (code={res.returncode}) — interaktív módhoz visszatérés.")
    except subprocess.TimeoutExpired:
        logger.warning("Non-interactive meshcore-cli msg timeout — interaktív próbálkozás következik.")
    except Exception as e:
        logger.debug(f"Non-interactive meshcore-cli msg kivétel: {e}")

    try:
        logger.info("Interaktív CLI indítása...")
        # Run interactive CLI in debug mode to surface raw TX logs (sending pkt / raw data)
        proc = subprocess.Popen([binp, "-D", "-s", port], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)
    except Exception as e:
        logger.error(f"Interaktív CLI indítás hiba: {e}")
        # restart monitor and exit
        start_monitor()
        return False

    try:
        # wait for initial prompt (shortened)
        deadline = time.time() + 4.0
        out_acc = b""
        while time.time() < deadline:
            try:
                part = proc.stdout.readline()
            except Exception:
                part = b""
            if part:
                out_acc += part
                try:
                    s = out_acc.decode("utf-8", errors="replace")
                except Exception:
                    s = ""
                # surface start output at INFO so debug is visible
                logger.info(f"[CLI startout] {s.strip().splitlines()[-1] if s else '<no>'}")
                if "Fetching channels" in s or ">" in s:
                    break
            else:
                time.sleep(0.15)

        # write 'to <room>'
        to_line = f"to {room_identifier}\n".encode("utf-8", errors="replace")
        try:
            proc.stdin.write(to_line)
            proc.stdin.flush()
        except Exception:
            try:
                os.write(proc.stdin.fileno(), to_line)
            except Exception as e:
                logger.error(f"Nem sikerült beírni a 'to' parancsot: {e}")
                proc.kill()
                start_monitor()
                return False
        time.sleep(0.25)

        # send chunks
        for idx, chunk in enumerate(chunks, start=1):
            # prefix chunk with leading double-quote so remote prompt treats it as chat text
            send_line = f'"{chunk}\n'.encode("utf-8", errors="replace")
            logger.info(f"📡 Küldés chunk {idx}/{len(chunks)}: {chunk[:80]}")
            try:
                proc.stdin.write(send_line)
                proc.stdin.flush()
            except Exception:
                try:
                    os.write(proc.stdin.fileno(), send_line)
                except Exception as e:
                    logger.error(f"Nem sikerült beírni a 'send' parancsot: {e}")
                    proc.kill()
                    start_monitor()
                    return False
            time.sleep(0.5)

        # quit
        try:
            proc.stdin.write(b"quit\n")
            proc.stdin.flush()
        except Exception:
            try:
                os.write(proc.stdin.fileno(), b"quit\n")
            except Exception:
                pass

        try:
            proc.wait(timeout=timeout + 5)
        except subprocess.TimeoutExpired:
            logger.warning("Interaktív CLI timeout — killolom.")
            try:
                trailing = b""
                while True:
                    part = proc.stdout.read(4096)
                    if not part:
                        break
                    trailing += part
                trailing_s = trailing.decode('utf-8', errors='replace')
                # log only the tail to avoid huge outputs
                logger.error(f"CLI timed out — trailing output (truncated): {trailing_s[-400:]}")
            except Exception:
                logger.debug("Could not read trailing CLI output after timeout.")
            proc.kill()
            start_monitor()
            return False

        # capture trailing output for debug
        trailing = b""
        try:
            while True:
                part = proc.stdout.read(4096)
                if not part:
                    break
                trailing += part
        except Exception:
            pass

        try:
            trailing_s = trailing.decode("utf-8", errors="replace")
        except Exception:
            trailing_s = "<decode failed>"
        logger.debug(f"CLI trailing output: {trailing_s[-400:] if trailing_s else '<none>'}")

        logger.info("Interaktív küldés sikeres.")
        return True

    finally:
        try:
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=0.5)
                except Exception:
                    proc.kill()
        except Exception:
            pass
        # restart monitor
        time.sleep(0.3)
        start_monitor()

# -------------------------
# Startup sequence: seed AI and optionally send initial message
# -------------------------
def startup_sequence():
    # seed memory with a system prompt (optional)
    ai_memory.clear()
    ai_memory.append({"role": "system", "content": "You are Lara, an autonomous radio chat assistant."})
    # initial user prompt as requested
    seed = "hi, how are you?"
    ai_memory.append({"role": "user", "content": seed})
    # call AI once to generate initial message
    ans = call_ai(seed)
    if ans:
        logger.info("Kezdő AI válasz (seed) elküldése a szobába...")
        ok = send_to_room_interactive(ans)
        logger.info(f"Kezdő üzenet elküldve: {ok}")
    else:
        logger.info("Kezdő AI hívás nem adott választ — a monitor indul tovább.")

# -------------------------
# Main
# -------------------------
def main():
    logger.info("Lara CLI bridge indítása...")
    if not which_cli():
        sys.exit(1)
    if not room_cfg:
        logger.error("radio.room_name nincs beállítva a lara_config.yaml-ben.")
        sys.exit(1)

    # Start monitor
    start_monitor()
    time.sleep(0.4)

    # startup AI seeding and send initial prompt
    try:
        startup_sequence()
    except Exception as e:
        logger.exception(f"Kezdő szekvencia hiba: {e}")

    logger.info("Rendszer készen áll. Monitor figyel, AI integráció aktív.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Leállítás (CTRL+C).")
    finally:
        stop_monitor()

if __name__ == "__main__":
    main()
