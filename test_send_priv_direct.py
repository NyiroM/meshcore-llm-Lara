#!/usr/bin/env python3
"""
test_send_priv_direct.py - Test sending PRIV message via meshcore-cli directly
"""

import subprocess
import time

port = "COM4"
sender = "Enomee B"
message = "Test PRIV response from Enomee"

print(f"[TEST] Testing direct PRIV send via meshcore-cli")
print(f"[TEST] Port: {port}")
print(f"[TEST] Sender/To: {sender}")
print(f"[TEST] Message: {message}")

# Method 1: With quote prefix (mesh room syntax)
cmd = f"""to {sender}
"{message}
quit
"""

print(f"\n[TEST] Commands:\n{cmd}")
print(f"\n[TEST] Running meshcore-cli -s {port}...")

try:
    proc = subprocess.Popen(
        ["meshcore-cli", "-s", port],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding='utf-8',
        errors='replace'
    )
    
    stdout, stderr = proc.communicate(input=cmd, timeout=10)
    
    print(f"\n[TEST] STDOUT:\n{stdout}")
    if stderr:
        print(f"\n[TEST] STDERR:\n{stderr}")
        
    print(f"\n[TEST] Complete (return code: {proc.returncode})")
    
except subprocess.TimeoutExpired:
    print(f"[ERROR] Timeout")
    proc.kill()
except Exception as e:
    print(f"[ERROR] {e}")

print("\n[TEST] Now check the webapp or monitor on the receiver side!")
