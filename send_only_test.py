#!/usr/bin/env python3
"""
send_only_test.py — Küld egy PRIV üzenetet két node között ANÉLKÜL hogy beolvasná.
Így az üzenet az inbox-ban marad és a webapp láthatja.
"""
import asyncio
import sys
import yaml

# Mentés előtt ellenőrizzük hogy van-e meshcore library
try:
    from meshcore import MeshCore
except ImportError:
    print("ERROR: meshcore library not found. Install: pip install meshcore")
    sys.exit(1)

CONFIG_PATH = "lara_config.yaml"


def load_config(path=CONFIG_PATH) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        print(f"Failed to load config: {e}")
        return {}


async def send_only(sender_port: str, receiver_pubkey: str, message: str):
    """Küld egy PRIV üzenetet, de NEM olvassa be az inbox-ot."""
    mesh = None
    try:
        print(f"[SEND-ONLY] Opening sender port {sender_port}")
        mesh = await MeshCore.create_serial(sender_port)
        
        print(f"[SEND-ONLY] Fetching contacts...")
        contacts_res = await mesh.commands.get_contacts()
        
        if not hasattr(contacts_res, 'payload') or not contacts_res.payload:
            print(f"ERROR: get_contacts returned no payload")
            return False
        
        contacts = contacts_res.payload
        
        # Keresünk contact-ot pubkey prefix alapján
        receiver = None
        for pk, data in contacts.items():
            if not isinstance(data, dict):
                continue
            if pk.startswith(receiver_pubkey[:12]):
                receiver = data
                receiver["pubkey"] = pk  # Store pubkey in data for easier access
                break
        
        if not receiver:
            print(f"ERROR: Contact not found with pubkey prefix {receiver_pubkey[:12]}")
            return False
        
        print(f"[SEND-ONLY] Sending message to {receiver.get('pubkey')[:12]}...")
        print(f"[SEND-ONLY] Message: {message}")
        
        send_res = await mesh.commands.send_msg(receiver.get("pubkey"), message)
        
        if send_res:
            print(f"[SEND-ONLY] ✅ Message sent successfully (type: {send_res.type})")
            print(f"[SEND-ONLY] Expected ACK: {send_res.expected_ack if hasattr(send_res, 'expected_ack') else 'N/A'}")
            print(f"[SEND-ONLY] *** NOT reading receiver inbox - message should remain for webapp ***")
            return True
        else:
            print(f"[SEND-ONLY] ❌ send_msg returned None")
            return False
            
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        if mesh:
            await mesh.disconnect()


def main():
    cfg = load_config()
    nodes = cfg.get("nodes", {})
    
    node_a = nodes.get("node_a", {})
    node_b = nodes.get("node_b", {})
    
    # Megkérdezzük melyik irányba küldjön
    direction = cfg.get("node_test", {}).get("direction", "a_to_b")
    
    if direction == "a_to_b":
        sender_port = node_a.get("port")
        receiver_pubkey = node_b.get("pubkey")
        direction_label = f"{node_a.get('name')} -> {node_b.get('name')}"
    else:
        sender_port = node_b.get("port")
        receiver_pubkey = node_a.get("pubkey")
        direction_label = f"{node_b.get('name')} -> {node_a.get('name')}"
    
    message = cfg.get("node_test", {}).get("message", "Test message (inbox should keep this)")
    
    print(f"[SEND-ONLY] Direction: {direction_label}", file=sys.stderr)
    print(f"[SEND-ONLY] Sender port: {sender_port}", file=sys.stderr)
    print(f"[SEND-ONLY] Receiver pubkey: {receiver_pubkey[:12]}...", file=sys.stderr)
    print(f"[SEND-ONLY] Message: {message}", file=sys.stderr)
    print("", file=sys.stderr)
    
    success = asyncio.run(send_only(sender_port, receiver_pubkey, message))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
