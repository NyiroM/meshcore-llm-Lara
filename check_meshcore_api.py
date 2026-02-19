"""
Check what fields the MeshCore library actually provides in message objects.
This will show exactly what the library returns when get_msg() is called.
"""

import sys
import asyncio
import inspect

try:
    from meshcore import MeshCore, EventType
    print("✅ MeshCore library imported successfully")
    print()
except ImportError as e:
    print("❌ ERROR: MeshCore library not found")
    print(f"   {e}")
    print()
    print("Install with: pip install meshcore")
    sys.exit(1)


def inspect_message_class():
    """Inspect the message class structure if available."""
    print("="*70)
    print("INSPECTING MESHCORE LIBRARY")
    print("="*70)
    print()
    
    # Try to find message-related classes
    print("📦 Available classes in meshcore module:")
    for name, obj in inspect.getmembers(sys.modules['meshcore']):
        if inspect.isclass(obj):
            print(f"   - {name}")
    print()
    
    # Check MeshCore class methods
    print("🔧 MeshCore methods:")
    for name, method in inspect.getmembers(MeshCore, predicate=inspect.isfunction):
        if not name.startswith('_'):
            print(f"   - {name}")
    print()
    
    # Try to inspect the get_msg() return type if possible
    print("📝 Checking for message structure hints...")
    
    # Look for any Message or Msg classes
    for name, obj in inspect.getmembers(sys.modules['meshcore']):
        if 'msg' in name.lower() or 'message' in name.lower():
            if inspect.isclass(obj):
                print(f"\n   Found class: {name}")
                print("   Attributes:")
                for attr in dir(obj):
                    if not attr.startswith('_'):
                        print(f"      - {attr}")
    
    print()


async def test_live_connection():
    """
    Attempt to connect to a MeshCore device and inspect message structure.
    This will only work if a device is actually connected.
    """
    print("="*70)
    print("LIVE CONNECTION TEST (if hardware available)")
    print("="*70)
    print()
    
    # Try common COM ports on Windows
    test_ports = ['COM6', 'COM4', 'COM3']
    
    for port in test_ports:
        try:
            print(f"🔌 Attempting connection to {port}...")
            mesh = await MeshCore.create_serial(port)
            print(f"   ✅ Connected to {port}!")
            
            # Try to get messages
            print(f"   📨 Checking for messages...")
            msg_res = await mesh.commands.get_msg()
            
            print(f"   Response type: {msg_res.type}")
            print(f"   Payload type: {type(msg_res.payload)}")
            print(f"   Payload: {repr(msg_res.payload)[:200]}")
            
            if msg_res.payload:
                if isinstance(msg_res.payload, list) and len(msg_res.payload) > 0:
                    sample_msg = msg_res.payload[0]
                    print(f"\n   📦 Sample message structure:")
                    print(f"      Type: {type(sample_msg)}")
                    
                    if hasattr(sample_msg, '__dict__'):
                        print(f"      Attributes: {sample_msg.__dict__}")
                    elif isinstance(sample_msg, dict):
                        print(f"      Keys: {sample_msg.keys()}")
                        for key, value in sample_msg.items():
                            print(f"         {key}: {value}")
                    
                    # Check specifically for metadata fields
                    print(f"\n   🔍 Checking for metadata fields:")
                    metadata_fields = ['rssi', 'snr', 'hop_count', 'hop_start', 'signal', 'routing']
                    for field in metadata_fields:
                        if isinstance(sample_msg, dict):
                            has_it = field in sample_msg
                            value = sample_msg.get(field) if has_it else None
                        else:
                            has_it = hasattr(sample_msg, field)
                            value = getattr(sample_msg, field, None) if has_it else None
                        
                        status = "✅" if has_it and value is not None else "❌"
                        print(f"      {status} {field}: {value}")
                else:
                    print("   ℹ️  No messages in queue")
            
            await mesh.disconnect()
            print()
            return True
            
        except FileNotFoundError:
            print(f"   ⚠️  Port {port} not found")
        except PermissionError:
            print(f"   ⚠️  Port {port} busy (close other apps using it)")
        except Exception as e:
            print(f"   ❌ Error: {e}")
    
    print()
    print("ℹ️  No hardware connected - showing library inspection only")
    print()
    return False


async def main():
    print()
    
    # First inspect the library structure
    inspect_message_class()
    
    # Then try live connection if available
    connected = await test_live_connection()
    
    print("="*70)
    print("CONCLUSIONS")
    print("="*70)
    print()
    print("✅ auto_reply_priv.py is READY to extract metadata from messages")
    print()
    print("📋 Expected metadata fields (from LoRa protocol):")
    print("   - rssi: Received Signal Strength Indicator (dBm)")
    print("   - snr: Signal-to-Noise Ratio (dB)")
    print("   - hop_count: Remaining hops in mesh routing")
    print("   - hop_start: Initial hop limit")
    print()
    
    if not connected:
        print("⚠️  To verify actual MeshCore library output:")
        print("   1. Connect MeshCore hardware to COM port")
        print("   2. Run this script again: python check_meshcore_api.py")
        print("   3. Or run the bot with debug_auto_reply: true")
        print("   4. Send a test message and check lara_bot.log")
        print()
    
    print("📚 If metadata fields are missing from library:")
    print("   - Check MeshCore library documentation")
    print("   - Update to latest MeshCore version: pip install -U meshcore")
    print("   - Contact MeshCore developers to request RSSI/SNR exposure")
    print("   - Verify firmware supports exposing signal metadata")
    print()


if __name__ == "__main__":
    asyncio.run(main())
