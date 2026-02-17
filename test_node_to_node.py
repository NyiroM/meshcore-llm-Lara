#!/usr/bin/env python3
"""
test_node_to_node.py — simple node-to-node test using MeshCore library + meshcore-cli monitor

⚠️  DEPRECATED: This script has been replaced by send_only_test.py

Original Workflow (which caused the bug):
- Started meshcore-cli monitor on receiver port
- Sent a message from sender port using meshcore library
- ❌ BUG: Tried to read the message back using get_msg() / get_messages()
- ❌ This EMPTIED the inbox, preventing webapp/Android apps from seeing the message!

New Workflow (correct):
- Use send_only_test.py instead
- Just SEND the message, don't read it
- Leave inbox intact for webapp/Android clients to retrieve

Safety: script reads message from config and will NOT forward to any public channel.
"""
import asyncio
import logging
import sys
import yaml
import shutil
from typing import List

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [NODE-TEST] - %(message)s')
logger = logging.getLogger("test_node_to_node")

CONFIG_PATH = "lara_config.yaml"


def load_config(path=CONFIG_PATH) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return {}


async def _read_stdout_lines(proc, out_lines: List[tuple], stop_event: asyncio.Event):
    try:
        while not proc.stdout.at_eof():
            line = await proc.stdout.readline()
            if not line:
                break
            try:
                text = line.decode('utf-8', errors='replace')
            except Exception:
                text = str(line)
            out_lines.append((asyncio.get_event_loop().time(), text))
            logger.debug(f"MONITOR: {text.strip()}")
            if stop_event.is_set():
                break
    except asyncio.CancelledError:
        return
    except Exception as e:
        logger.exception(f"Exception reading monitor stdout: {e}")


async def run_test():
    cfg = load_config()
    nodes = cfg.get("nodes") or {}
    node_test = cfg.get("node_test") or {}

    if not nodes or "node_a" not in nodes or "node_b" not in nodes:
        logger.error("nodes.node_a and nodes.node_b must be configured in lara_config.yaml")
        return False

    a = nodes["node_a"]
    b = nodes["node_b"]

    # direction: 'a_to_b' or 'b_to_a'
    direction = node_test.get("direction") or "b_to_a"
    if direction == "a_to_b":
        sender = a
        receiver = b
    else:
        sender = b
        receiver = a

    port_a = sender.get("port")
    port_b = receiver.get("port")
    pk_b = receiver.get("pubkey")

    if not port_a or not port_b or not pk_b:
        logger.error("Invalid node configuration (missing port or pubkey).")
        return False

    message = node_test.get("message") or "Node-to-node test"
    timeout = float(node_test.get("timeout_seconds", 8))

    meshcore_cli = shutil.which("meshcore-cli")
    if not meshcore_cli:
        logger.error("meshcore-cli binary not found in PATH. Install it or add to PATH.")
        return False

    logger.info(f"Starting monitor on {port_b} (receiver)")
    proc = await asyncio.create_subprocess_exec(
        meshcore_cli, "-s", port_b,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    monitor_lines: List[str] = []
    stop_event = asyncio.Event()
    reader_task = asyncio.create_task(_read_stdout_lines(proc, monitor_lines, stop_event))

    # Give monitor time to initialize
    await asyncio.sleep(0.6)

    # Now send from node_a via meshcore library
    try:
        from meshcore import MeshCore, EventType
    except Exception as e:
        logger.error("meshcore library not available. Install with: pip install meshcore")
        stop_event.set()
        reader_task.cancel()
        proc.kill()
        return False

    sender_mesh = None
    try:
        logger.info(f"Connecting to sender node on {port_a} ...")
        sender_mesh = await MeshCore.create_serial(port_a)

        logger.info("Fetching contacts on sender...")
        contacts_res = await sender_mesh.commands.get_contacts()
        if contacts_res.type == EventType.ERROR:
            logger.error(f"get_contacts error: {contacts_res.payload}")
            return False
        contacts = contacts_res.payload or {}

        if not isinstance(pk_b, str) or len(pk_b.strip()) != 64:
            logger.error("Receiver pubkey in config looks invalid.")
            return False

        pk_b_lower = pk_b.lower()
        if pk_b_lower not in contacts:
            logger.error("Receiver pubkey not found in sender contacts. Make sure nodes have seen each other or contacts are provisioned.")
            # continue to send attempt by constructing minimal contact object
            target_obj = {"adv_name": "remote", "type": 1}
        else:
            target_obj = contacts[pk_b_lower]
            logger.info(f"Found recipient contact in sender contacts (pubkey prefix: {pk_b_lower[:12]}...).")

        logger.info(f"Sending message to {pk_b_lower[:12]}...: {message}")
        send_time = asyncio.get_event_loop().time()
        send_res = await sender_mesh.commands.send_msg(target_obj, message)

        logger.info(f"send_msg returned type={getattr(send_res, 'type', None)}")
        payload = getattr(send_res, 'payload', None)
        if isinstance(payload, dict):
            exp = payload.get('expected_ack')
            sug = payload.get('suggested_timeout')
            if exp:
                logger.info(f"expected_ack: {exp.hex() if isinstance(exp, (bytes, bytearray)) else repr(exp)}")
            if sug:
                logger.info(f"suggested_timeout: {sug}ms")

    except Exception as e:
        logger.exception(f"Exception while sending: {e}")
        return False
    finally:
        if sender_mesh:
            try:
                await sender_mesh.disconnect()
            except Exception:
                pass

    # Wait for monitor output up to timeout seconds, but filter by close timestamp to send_time
    window = float(node_test.get("window_seconds", timeout))
    logger.info(f"Waiting up to {timeout}s for monitor output on {port_b} (time-window {window}s)...")
    end_time = asyncio.get_event_loop().time() + timeout
    found_monitor = False
    while asyncio.get_event_loop().time() < end_time:
        # Check lines for either the message text or the receiver pubkey, within the time window
        for ts, ln in list(monitor_lines):
            if abs(ts - send_time) <= window and (message in ln or (pk_b_lower[:8] in ln.lower())):
                found_monitor = True
                logger.info(f"Found monitor evidence (t={ts-send_time:+.3f}s): {ln.strip()}")
                break
        if found_monitor:
            break
        await asyncio.sleep(0.2)

    stop_event.set()
    try:
        reader_task.cancel()
    except Exception:
        pass

    # Terminate the monitor process
    try:
        if proc.returncode is None:
            proc.kill()
    except Exception:
        pass

    # Requirement: Only accept success if receiver node can read the message from its inbox
    logger.info("Verifying receiver inbox for delivered message...")
    receiver_mesh = None
    try:
        try:
            receiver_mesh = await MeshCore.create_serial(port_b)
        except Exception as e:
            logger.debug(f"Could not open receiver serial port {port_b}: {e}")
            # Fallback to meshcore-cli messages output
            meshcore_cli = shutil.which("meshcore-cli")
            if meshcore_cli:
                try:
                    proc2 = await asyncio.create_subprocess_exec(
                        meshcore_cli, "-s", port_b,
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
            logger.error("❌ Node-to-node test FAIL: cannot open receiver serial port and CLI fallback failed.")
            return False
        # Try common inbox APIs on the receiver
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
        found_in_inbox = False
        
        # Poll inbox APIs for a short time window (messages may take time to become queryable)
        poll_end = asyncio.get_event_loop().time() + 3.0  # poll for 3s max
        poll_count = 0
        while asyncio.get_event_loop().time() < poll_end and not found_in_inbox:
            poll_count += 1
            for mname in inbox_methods:
                if hasattr(receiver_mesh.commands, mname):
                    try:
                        logger.debug(f"Poll #{poll_count} trying receiver command: {mname}()")
                        res = await getattr(receiver_mesh.commands, mname)()
                        if getattr(res, 'type', None) == EventType.ERROR:
                            logger.debug(f"{mname} returned ERROR: {getattr(res,'payload',None)}")
                            continue
                        payload = getattr(res, 'payload', None)
                        if poll_count == 1 or (poll_count % 5 == 0):
                            logger.info(f"Poll #{poll_count} {mname} payload repr: {repr(payload)[:500]}")
                        # payload may be list/dict; try to find message text and optional timestamps
                        if isinstance(payload, list):
                            for item in payload:
                                text = ""
                                ts = None
                                if isinstance(item, dict):
                                    for k in ("message", "text", "body", "payload"):
                                        if k in item:
                                            text = item[k]
                                            break
                                    # common timestamp keys
                                    for tkey in ("ts", "time", "timestamp", "recv_time", "sender_timestamp"):
                                        if tkey in item:
                                            try:
                                                ts = float(item[tkey])
                                            except Exception:
                                                pass
                                    if not text:
                                        text = repr(item)
                                else:
                                    text = str(item)
                                # If message text matches and timestamp is near send_time, accept
                                if message in text:
                                    if ts is None or abs(ts - send_time) <= window:
                                        found_in_inbox = True
                                        logger.info(f"Receiver inbox contains message (via {mname} poll #{poll_count}).")
                                        break
                                    else:
                                        logger.debug(f"Found message text in {mname} but timestamp {ts} not within window; ignoring.")
                        elif isinstance(payload, dict):
                            # single-message dict response (e.g., get_msg)
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
                                if ts is None or abs(ts - send_time) <= window:
                                    found_in_inbox = True
                                    logger.info(f"Receiver inbox contains message (via {mname} poll #{poll_count}).")
                                    break
                        if found_in_inbox:
                            break
                    except Exception as e:
                        logger.debug(f"Receiver command {mname}() poll #{poll_count} failed: {e}")
            if found_in_inbox:
                break
            await asyncio.sleep(0.4)
        if not found_in_inbox:
            # Try fallback: ask meshcore-cli on receiver to list stored messages
            meshcore_cli = shutil.which("meshcore-cli")
            if meshcore_cli:
                try:
                    proc2 = await asyncio.create_subprocess_exec(
                        meshcore_cli, "-s", port_b,
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    try:
                        stdout, stderr = await proc2.communicate(input=("messages\nquit\n").encode("utf-8"), timeout=5)
                        out = stdout.decode("utf-8", errors="replace")
                        # try to find message lines and check for recent timestamp surrounding send_time
                        if message in out:
                            # crude check: accept if message appears and monitor evidence existed nearby
                            if found_monitor:
                                found_in_inbox = True
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

            if not found_in_inbox:
                logger.error("❌ Node-to-node test FAIL: receiver inbox did not show the message (monitor evidence is insufficient).")
                # Format monitor lines safely (they are tuples: (timestamp, text))
                try:
                    last_lines = "\n".join([ln for ts,ln in monitor_lines[-20:]])
                except Exception:
                    last_lines = "\n".join(str(x) for x in monitor_lines[-20:])
                logger.debug("Last monitor lines:\n" + last_lines)
                return False
        else:
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


if __name__ == '__main__':
    ok = asyncio.run(run_test())
    sys.exit(0 if ok else 2)
