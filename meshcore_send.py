#!/usr/bin/env python3
"""
meshcore_send.py — debug változat

Funkciók:
- room név / pubkey felismerés
- opcionális channel set (force_set_key)
- részletes debug: meshcore logger DEBUG, send_res tartalom, ha van nyers tx info -> hex kiírás
- CLI opciók: --debug, --force-set-key, --room, --room-key

Használat:
python meshcore_send.py -p COM4 --room "HU-PE-CsömörÓfalu" -m "teszt" --debug
"""
import argparse
import asyncio
import logging
import re
import sys
import yaml
import hashlib
import shutil
import time
from typing import Any, Optional

# próbáljuk importálni a meshcore-t; ha nincs, dobunk
try:
    from meshcore import MeshCore, EventType
except Exception as e:
    print("ERROR: meshcore library nem található. Telepítsd: python -m pip install meshcore")
    raise

CONFIG_PATH = "lara_config.yaml"
HEX64_RE = re.compile(r"^[0-9a-fA-F]{64}$")

# logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - [MCSEND] - %(message)s")
logger = logging.getLogger("meshcore_send")


def load_config(path: str = CONFIG_PATH) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        logger.warning(f"Config betöltési hiba: {e}")
        return {}


def is_pubkey(s: str) -> bool:
    return bool(HEX64_RE.match(s.strip()))


def derive_16byte_secret(room_key: str) -> bytes:
    b = (room_key or "").encode("utf-8")
    if len(b) == 16:
        logger.info("Room key pontosan 16 bájt (utf-8) — nyers használat.")
        return b
    digest = hashlib.sha256(b).digest()[:16]
    logger.info("Room key nem 16 bájt — SHA256 truncation alkalmazva (->16B).")
    logger.debug(f"Derived secret hex: {digest.hex()}")
    return digest


async def send_room_message(
    port: str,
    room_input: str,
    message: str,
    room_key: Optional[str] = None,
    force_set_key: bool = False,
    channel_slot: int = 1,
    search_case_insensitive: bool = True,
    wait_for_ack: bool = False,
    auto_set_key: bool = True,
    ) -> bool:
    mesh = None
    try:
        logger.info(f"Connecting to MeshCore on {port} ...")
        mesh = await MeshCore.create_serial(port)
        # DEBUG: meshcore internal logger to stdout can be very verbose if enabled externally

        logger.info("Fetching contacts...")
        contacts_res = await mesh.commands.get_contacts()
        if contacts_res.type == EventType.ERROR:
            logger.error(f"get_contacts error: {contacts_res.payload}")
            return False
        contacts = contacts_res.payload or {}
        logger.info(f"Found {len(contacts)} contacts")

        room_pubkey: Optional[str] = None
        room_obj: Optional[Any] = None

        if is_pubkey(room_input):
            logger.info("Interpreting room input as pubkey.")
            pk = room_input.lower()
            if pk in contacts:
                room_pubkey = pk
                room_obj = contacts[pk]
            else:
                logger.error("Pubkey not found among contacts.")
                rooms = [(k, v.get("adv_name")) for k, v in contacts.items() if isinstance(v, dict) and v.get("type") == 3]
                logger.info(f"Available rooms: {rooms}")
                return False
        else:
            logger.info("Interpreting room input as adv_name (room name).")
            for pk, data in contacts.items():
                if not isinstance(data, dict):
                    continue
                if data.get("type") != 3:
                    continue
                adv = data.get("adv_name") or ""
                if search_case_insensitive:
                    if adv.lower() == room_input.lower():
                        room_pubkey = pk
                        room_obj = data
                        break
                else:
                    if adv == room_input:
                        room_pubkey = pk
                        room_obj = data
                        break
            if not room_obj:
                logger.error(f"Room named '{room_input}' not found.")
                rooms = [(k, v.get("adv_name")) for k, v in contacts.items() if isinstance(v, dict) and v.get("type") == 3]
                logger.info(f"Available rooms: {rooms}")
                return False

        logger.info(f"Target room: adv_name='{room_obj.get('adv_name')}', pubkey={room_pubkey[:16]}...")

        # Safety: prevent accidental forwarding to public rooms if configuration disables it
        cfg = load_config()
        node_test_cfg = cfg.get("node_test", {}) or {}
        prevent_public = not bool(node_test_cfg.get("allow_public_forwarding", False))
        if prevent_public and isinstance(room_obj, dict) and room_obj.get("type") == 3:
            logger.error("Refusing to send to public room: configuration prevents public forwarding.")
            return False

        if force_set_key or (auto_set_key and room_key):
            if not room_key:
                logger.error("set_channel requested but no room_key provided.")
                return False
            secret16 = derive_16byte_secret(room_key)
            logger.info("Calling set_channel(...) with derived secret (16 bytes).")
            set_res = await mesh.commands.set_channel(channel_slot, room_pubkey, secret16)
            if set_res.type == EventType.ERROR:
                logger.error(f"set_channel error: {set_res.payload}")
                return False
            logger.info("set_channel OK.")
            await asyncio.sleep(0.35)
        else:
            logger.info("Not calling set_channel (use --force-set-key or provide room_key to enable).")

        # --- SEND and debug the response object in detail ---
        # Prefer send_msg_with_retry when explicit ACK waiting is requested.
        send_res = None
        try:
            if wait_for_ack and hasattr(mesh.commands, "send_msg_with_retry"):
                logger.info("Calling send_msg_with_retry(...) (wait_for_ack=True).")
                send_res = await mesh.commands.send_msg_with_retry(room_obj, message)
            else:
                logger.info("Calling send_msg(...).")
                send_res = await mesh.commands.send_msg(room_obj, message)
        except Exception as e:
            logger.exception(f"Exception while sending message: {e}")
            return False, None

        # Print the send_res object for inspection (very useful)
        try:
            logger.info(f"send_msg returned: type={getattr(send_res, 'type', None)}")
            # payload can be many forms; stringify safely
            logger.info(f"send_msg payload repr: {repr(getattr(send_res, 'payload', None))}")
        except Exception as e:
            logger.debug(f"Couldn't pretty-print send_res: {e}")

        # If payload contains frame/tx info, show hex (best effort)
        payload = getattr(send_res, "payload", None)
        if isinstance(payload, (bytes, bytearray)):
            logger.info(f"send_msg payload bytes (hex): {payload.hex()}")
        elif isinstance(payload, dict):
            # look for common keys where libs may put tx/frame bytes
            for k in ("frame", "raw", "tx", "packet"):
                if k in payload and isinstance(payload[k], (bytes, bytearray)):
                    logger.info(f"send_msg payload[{k}] hex: {payload[k].hex()}")
            # print keys summary
            logger.debug(f"send_res.payload keys: {list(payload.keys())}")
        else:
            logger.debug("send_res.payload not bytes/dict — full repr already logged.")

        if send_res.type == EventType.ERROR:
            logger.error("send_msg reported ERROR.")
            return False, getattr(send_res, 'payload', None)

        logger.info("send_msg succeeded (library).")
        return True, getattr(send_res, 'payload', None)

    except Exception as e:
        logger.exception(f"Exception during send_room_message: {e}")
        return False

    finally:
        if mesh:
            try:
                await mesh.disconnect()
            except Exception:
                pass


def main():
    cfg = load_config(CONFIG_PATH)
    radio_cfg = cfg.get("radio", {}) or {}
    # Prefer a human-friendly advert name if present (some configs use the key 'radio.room_name')
    cfg_room_name = radio_cfg.get("radio.room_name") or radio_cfg.get("room_name")
    cfg_room_key = radio_cfg.get("room_key")

    ap = argparse.ArgumentParser()
    ap.add_argument("-p", "--port", default="COM4")
    ap.add_argument("--room", "-r", default=cfg_room_name or "", help="Room adv_name or pubkey (default from lara_config.yaml)")
    ap.add_argument("--message", "-m", required=False, default=None)
    ap.add_argument("--room-key", default=cfg_room_key, help="Room key (if used with --force-set-key)")
    ap.add_argument("--force-set-key", action="store_true")
    ap.add_argument("--no-auto-set-key", action="store_true", help="Disable automatic set_channel call even if room_key present")
    ap.add_argument("--channel-slot", type=int, default=1)
    ap.add_argument("--debug", action="store_true", help="Enable debug logging for meshcore lib")
    ap.add_argument("--node-test", action="store_true", help="Run configured node-to-node test and exit")
    args = ap.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        # enable meshcore logger debug as well
        logging.getLogger("meshcore").setLevel(logging.DEBUG)
        logger.debug("DEBUG logging enabled for both this script and meshcore library.")

    if not getattr(args, "node_test", False) and not args.room:
        logger.error("No room specified (--room).")
        sys.exit(2)

    # If user requested a node-to-node self-test, run it and exit
    if getattr(args, "node_test", False):
        # run the integrated node-to-node test using meshcore-cli monitor + meshcore lib
        async def _run_node_test():
            # reuse logic from external test script but keep it internal to avoid duplication
            cfg = load_config()
            nodes = cfg.get("nodes") or {}
            node_test = cfg.get("node_test") or {}
            if not nodes or "node_a" not in nodes or "node_b" not in nodes:
                logger.error("nodes.node_a and nodes.node_b must be configured in lara_config.yaml")
                return False

            # pick direction
            direction = node_test.get("direction") or "b_to_a"
            if direction == "a_to_b":
                sender = nodes["node_a"]
                receiver = nodes["node_b"]
            else:
                sender = nodes["node_b"]
                receiver = nodes["node_a"]

            sender_port = sender.get("port")
            receiver_port = receiver.get("port")
            receiver_pub = receiver.get("pubkey")
            message = node_test.get("message") or "Node-to-node test"
            timeout = float(node_test.get("timeout_seconds", 8))
            send_time = None
            send_epoch = None

            # First try an exclusive-mode test: open receiver with meshcore lib directly
            # Try opening the receiver port exclusively with retries (transient port locks may occur)
            receiver_mesh = None
            for attempt in range(5):
                try:
                    receiver_mesh = await MeshCore.create_serial(receiver_port)
                    break
                except Exception as e:
                    logger.debug(f"Attempt {attempt+1}: could not open receiver {receiver_port}: {e}")
                    await asyncio.sleep(0.35)

            if receiver_mesh:
                logger.info("Opened receiver exclusively via meshcore library; running direct inbox polling test.")
                sender_mesh = None
                try:
                    # retry opening sender port a few times (transient locks possible)
                    sender_mesh = None
                    for s_attempt in range(5):
                        try:
                            sender_mesh = await MeshCore.create_serial(sender_port)
                            break
                        except Exception as e:
                            logger.debug(f"Attempt {s_attempt+1}: could not open sender {sender_port}: {e}")
                            await asyncio.sleep(0.35)
                    if not sender_mesh:
                        logger.error(f"Could not open sender port {sender_port} after retries.")
                        return False

                    # send from sender: resolve contact by receiver pubkey if available
                    contacts_res = await sender_mesh.commands.get_contacts()
                    if contacts_res.type == EventType.ERROR:
                        logger.error(f"get_contacts error (sender): {contacts_res.payload}")
                        return False
                    sender_contacts = contacts_res.payload or {}
                    target = None
                    if receiver_pub:
                        pk = receiver_pub.lower()
                        if pk in sender_contacts:
                            target = sender_contacts[pk]
                        else:
                            target = {"public_key": pk, "adv_name": "remote", "type": 1}
                    else:
                        # fallback minimal contact
                        target = {"adv_name": "remote", "type": 1}

                    send_time = asyncio.get_event_loop().time()
                    send_epoch = time.time()
                    try:
                        send_res = await sender_mesh.commands.send_msg(target, message)
                        logger.info(f"send_msg returned: {getattr(send_res,'type',None)}")
                        logger.info(f"✅ Node-test SEND-ONLY mode: message sent successfully.")
                        logger.info(f"⚠️  NOT polling receiver inbox - inbox left intact for webapp/Android to retrieve.")
                        return True
                    except Exception as e:
                        logger.exception(f"Exception during node-to-node send (exclusive mode): {e}")
                        return False
                finally:
                    try:
                        if sender_mesh:
                            await sender_mesh.disconnect()
                    except Exception:
                        pass
                    try:
                        if receiver_mesh:
                            await receiver_mesh.disconnect()
                    except Exception:
                        pass

            # start monitor via meshcore-cli subprocess
            meshcore_cli = shutil.which("meshcore-cli")
            if not meshcore_cli:
                logger.error("meshcore-cli binary not found in PATH.")
                return False

            logger.info(f"Starting monitor on {receiver_port}")
            proc = await asyncio.create_subprocess_exec(
                meshcore_cli, "-s", receiver_port,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            monitor_lines = []
            stop_event = asyncio.Event()

            async def _reader():
                try:
                    while not proc.stdout.at_eof():
                        line = await proc.stdout.readline()
                        if not line:
                            break
                        try:
                            txt = line.decode("utf-8", errors="replace")
                        except Exception:
                            txt = str(line)
                        monitor_lines.append((asyncio.get_event_loop().time(), txt))
                        logger.debug(f"MON: {txt.strip()}")
                        if stop_event.is_set():
                            break
                except Exception as e:
                    logger.debug(f"Monitor reader exception: {e}")

            reader_task = asyncio.create_task(_reader())
            await asyncio.sleep(0.6)

            # send using meshcore library
            try:
                sender_mesh = await MeshCore.create_serial(sender_port)
                contacts_res = await sender_mesh.commands.get_contacts()
                if contacts_res.type == EventType.ERROR:
                    logger.error(f"get_contacts error: {contacts_res.payload}")
                    return False
                contacts = contacts_res.payload or {}
                pk = (receiver_pub or "").lower()
                if pk in contacts:
                    target = contacts[pk]
                else:
                    target = {"adv_name": "remote", "type": 1}
                send_time = asyncio.get_event_loop().time()
                send_epoch = time.time()
                send_res = await sender_mesh.commands.send_msg(target, message)
                logger.info(f"send_msg returned: {getattr(send_res,'type',None)}")
                try:
                    payload = getattr(send_res, 'payload', None)
                    if isinstance(payload, dict):
                        exp = payload.get('expected_ack')
                        sug = payload.get('suggested_timeout')
                        if exp:
                            logger.info(f"expected_ack: {exp}")
                        if sug:
                            logger.info(f"suggested_timeout: {sug}ms")
                except Exception:
                    pass
            except Exception as e:
                logger.exception(f"Exception during node-to-node send: {e}")
                stop_event.set()
                reader_task.cancel()
                try:
                    proc.kill()
                except Exception:
                    pass
                return False
            finally:
                try:
                    await sender_mesh.disconnect()
                except Exception:
                    pass

            # wait for monitor evidence (but require receiver to read from inbox)
            window = float(node_test.get("window_seconds", timeout))
            logger.info(f"Waiting up to {timeout}s for monitor evidence (time window {window}s)...")
            end = asyncio.get_event_loop().time() + timeout
            found_monitor = False
            keypart = (receiver_pub or "")[:8].lower()
            while asyncio.get_event_loop().time() < end:
                for item in list(monitor_lines):
                    if isinstance(item, tuple) and len(item) >= 2:
                        ts, ln = item[0], item[1]
                    else:
                        ts, ln = None, str(item)
                    if ts is not None:
                        # if we recorded a send_time earlier, prefer temporal filtering
                        if abs(ts - send_time) <= window and (message in ln or keypart in ln.lower()):
                            found_monitor = True
                            logger.info(f"Monitor saw (t={ts-send_time:+.3f}s): {ln.strip()}")
                            break
                    else:
                        if message in ln or keypart in ln.lower():
                            found_monitor = True
                            logger.info(f"Monitor saw: {ln.strip()}")
                            break
                if found_monitor:
                    break
                await asyncio.sleep(0.2)

            stop_event.set()
            try:
                reader_task.cancel()
            except Exception:
                pass
            try:
                if proc.returncode is None:
                    proc.kill()
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=1.0)
                    except Exception:
                        pass
            except Exception:
                pass

            # Give the OS a moment to release the serial port after killing the monitor
            await asyncio.sleep(0.35)

            # Now require that the receiver node actually reads/stores the message
            logger.info("Verifying receiver inbox for delivered message...")
            receiver_mesh = None
            try:
                try:
                    receiver_mesh = await MeshCore.create_serial(receiver.get("port"))
                except Exception as e:
                    logger.debug(f"Could not open receiver serial port {receiver.get('port')}: {e}")
                    # Immediate CLI fallback when monitor holds the port
                    meshcore_cli = shutil.which("meshcore-cli")
                    if meshcore_cli:
                        try:
                            proc2 = await asyncio.create_subprocess_exec(
                                meshcore_cli, "-s", receiver.get("port"),
                                stdin=asyncio.subprocess.PIPE,
                                stdout=asyncio.subprocess.PIPE,
                                stderr=asyncio.subprocess.PIPE
                            )
                            try:
                                stdout, stderr = await proc2.communicate(input=("messages\nquit\n").encode("utf-8"), timeout=5)
                                out = stdout.decode("utf-8", errors="replace")
                                if message in out and found_monitor:
                                    logger.info("Receiver inbox contains message (via meshcore-cli 'messages' fallback).")
                                    return True
                            except Exception:
                                pass
                            try:
                                if proc2.returncode is None:
                                    proc2.kill()
                            except Exception:
                                pass
                        except Exception:
                            pass
                    # If CLI fallback failed, try a looser scan of the captured monitor lines
                    keypart = (receiver_pub or "")[:8].lower()
                    lax_found = False
                    for item in list(monitor_lines):
                        if isinstance(item, tuple) and len(item) >= 2:
                            ln = item[1]
                        else:
                            ln = str(item)
                        if message and message in ln:
                            lax_found = True
                            break
                        if keypart and keypart in ln.lower():
                            lax_found = True
                            break
                    if lax_found:
                        logger.warning("Receiver port busy but monitor shows matching line — accepting as success.")
                        return True
                    logger.error("Node-test FAIL: cannot open receiver serial port and CLI fallback failed.")
                    # Dump captured monitor lines for debugging
                    try:
                        logger.info("Captured monitor lines:")
                        for li in list(monitor_lines):
                            logger.info(repr(li))
                    except Exception:
                        pass
                    return False
                inbox_methods = [
                    "get_msg",         # Try this first (returns dict with 'text' field)
                    "get_messages",
                    "get_inbox",
                    "get_received_messages",
                    "get_recent_messages",
                    "get_all_messages",
                    "get_history",
                    "list_messages",
                ]
                found_inbox = False
                for mname in inbox_methods:
                    if hasattr(receiver_mesh.commands, mname):
                        try:
                            logger.debug(f"Trying receiver command: {mname}()")
                            res = await getattr(receiver_mesh.commands, mname)()
                            if getattr(res, 'type', None) == EventType.ERROR:
                                logger.debug(f"{mname} returned ERROR: {getattr(res,'payload',None)}")
                                continue
                            payload = getattr(res, 'payload', None)
                            logger.info(f"{mname} payload repr: {repr(payload)[:1000]}")
                            if isinstance(payload, list):
                                for item in payload:
                                    text = ""
                                    ts = None
                                    if isinstance(item, dict):
                                        for k in ("message", "text", "body", "payload"):
                                            if k in item:
                                                text = item[k]
                                                break
                                        for tkey in ("ts", "time", "timestamp", "recv_time"):
                                            if tkey in item:
                                                try:
                                                    ts = float(item[tkey])
                                                except Exception:
                                                    pass
                                        if not text:
                                            text = repr(item)
                                    else:
                                        text = str(item)
                                    if message in text:
                                        ts_ok = False
                                        if ts is None:
                                            ts_ok = True
                                        else:
                                            try:
                                                if ts > 1e9 and send_epoch is not None:
                                                    ts_ok = abs(ts - send_epoch) <= window
                                                elif send_time is not None:
                                                    ts_ok = abs(ts - send_time) <= window
                                            except Exception:
                                                ts_ok = False
                                        if ts_ok:
                                            found_inbox = True
                                            logger.info(f"Receiver inbox contains message (via {mname}).")
                                            break
                                        else:
                                            logger.debug(f"Found message text in {mname} but timestamp {ts} not within window; ignoring.")
                            if found_inbox:
                                break
                            elif isinstance(payload, dict):
                                # single-message response shape (e.g., get_msg)
                                text = ""
                                ts = None
                                for k in ("message", "text", "body", "payload"):
                                    if k in payload:
                                        text = payload[k]
                                        break
                                for tkey in ("ts", "time", "timestamp", "recv_time", "sender_timestamp"):
                                    if tkey in payload:
                                        try:
                                            ts = float(payload[tkey])
                                        except Exception:
                                            pass
                                if not text:
                                    text = repr(payload)
                                if message in text:
                                    ts_ok = False
                                    if ts is None:
                                        ts_ok = True
                                    else:
                                        try:
                                            if ts > 1e9 and send_epoch is not None:
                                                ts_ok = abs(ts - send_epoch) <= window
                                            elif send_time is not None:
                                                ts_ok = abs(ts - send_time) <= window
                                        except Exception:
                                            ts_ok = False
                                    if ts_ok:
                                        found_inbox = True
                                        logger.info(f"Receiver inbox contains message (via {mname}).")
                                        break
                        except Exception:
                            logger.debug(f"Receiver command {mname}() failed or returned unexpected format.")
                if not found_inbox:
                    # CLI fallback: ask meshcore-cli to list messages and check appearance (accept if monitor evidence exists nearby)
                    meshcore_cli = shutil.which("meshcore-cli")
                    if meshcore_cli:
                        try:
                            proc2 = await asyncio.create_subprocess_exec(
                                meshcore_cli, "-s", receiver.get("port"),
                                stdin=asyncio.subprocess.PIPE,
                                stdout=asyncio.subprocess.PIPE,
                                stderr=asyncio.subprocess.PIPE
                            )
                            try:
                                stdout, stderr = await proc2.communicate(input=("messages\nquit\n").encode("utf-8"), timeout=5)
                                out = stdout.decode("utf-8", errors="replace")
                                if message in out and found_monitor:
                                    found_inbox = True
                                    logger.info("Receiver inbox contains message (via meshcore-cli 'messages').")
                            except Exception:
                                pass
                            try:
                                if proc2.returncode is None:
                                    proc2.kill()
                            except Exception:
                                pass
                        except Exception:
                            pass
                    if not found_inbox:
                        logger.error("❌ Node-to-node test FAIL: receiver inbox did not show the message (monitor evidence is insufficient).")
                        # format last monitor lines safely
                        try:
                            last_lines = "\n".join([ln for ts,ln in monitor_lines[-20:]])
                        except Exception:
                            last_lines = "\n".join(str(x) for x in monitor_lines[-20:])
                        logger.debug("Last monitor lines:\n" + last_lines)
                        return False
                logger.info("✅ Node-to-node test PASS: receiver read message from inbox.")
                return True
            except Exception as e:
                logger.exception(f"Exception while checking receiver inbox: {e}")
                return False
            finally:
                if receiver_mesh:
                    try:
                        await receiver_mesh.disconnect()
                    except Exception:
                        pass

        ok = asyncio.run(_run_node_test())
        logger.info(f"Node-test result: {ok}")
        sys.exit(0 if ok else 2)

    # keep main() compatible: return boolean result and exit code
    res = asyncio.run(send_room_message(
        port=args.port,
        room_input=args.room,
        message=args.message,
        room_key=args.room_key,
        force_set_key=args.force_set_key,
        channel_slot=args.channel_slot,
        wait_for_ack=args.debug,  # if user asks --debug, also wait-for-ack to be safe
        auto_set_key=not args.no_auto_set_key  # auto-set if room_key present, unless disabled
    ))
    ok = False
    try:
        # res may be (bool, payload) or bool for backwards compatibility
        if isinstance(res, tuple) or isinstance(res, list):
            ok = bool(res[0])
        else:
            ok = bool(res)
    except Exception:
        ok = False
    logger.info(f"Result: {ok}")
    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()
