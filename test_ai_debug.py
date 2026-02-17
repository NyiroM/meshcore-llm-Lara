#!/usr/bin/env python3
"""
test_ai_debug.py - Debug AI API connectivity and response

Tests:
1. Is AI API reachable?
2. Does API return valid response?
3. How long does response take?
4. What format is the response?
"""

import requests
import json
import time
import sys
import yaml

CONFIG_PATH = "lara_config.yaml"

try:
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f) or {}
except Exception as e:
    print(f"ERROR: Config load failed: {e}")
    sys.exit(1)

ai_cfg = cfg.get('ai', {})
api_url = ai_cfg.get('api_url')
api_key = ai_cfg.get('api_key')

if not api_url or not api_key:
    print("ERROR: api_url or api_key not configured")
    sys.exit(1)

print(f"[DEBUG] Testing AI API")
print(f"[DEBUG] URL: {api_url}")
print(f"[DEBUG] Key: {api_key[:20]}...")

headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json"
}

test_messages = [
    {"role": "user", "content": "Mondj egy viccet!"},
]

payload = {
    "model": ai_cfg.get('model_id', 'mistral'),
    "messages": test_messages
}

print(f"[DEBUG] Sending request...")
start = time.time()

try:
    response = requests.post(api_url, headers=headers, json=payload, timeout=45)
    elapsed = time.time() - start
    
    print(f"[DEBUG] Response time: {elapsed:.2f}s")
    print(f"[DEBUG] HTTP Status: {response.status_code}")
    print(f"[DEBUG] Response headers: {dict(response.headers)}")
    
    if response.status_code == 200:
        try:
            data = response.json()
            print(f"[DEBUG] Response JSON: {json.dumps(data, ensure_ascii=False, indent=2)[:500]}")
            
            # Try to extract answer
            try:
                answer = data['choices'][0]['message']['content']
                print(f"\n[SUCCESS] AI Response:\n{answer}")
            except (KeyError, IndexError) as e:
                print(f"\n[ERROR] Could not extract answer from response: {e}")
                print(f"[DEBUG] Full response: {json.dumps(data, ensure_ascii=False, indent=2)}")
        except json.JSONDecodeError as e:
            print(f"[ERROR] Response is not JSON: {e}")
            print(f"[DEBUG] Response text: {response.text[:500]}")
    else:
        print(f"[ERROR] HTTP Error {response.status_code}")
        print(f"[DEBUG] Response: {response.text[:500]}")
        
except requests.exceptions.Timeout:
    print(f"[ERROR] Request timeout (>45s)")
except requests.exceptions.ConnectionError as e:
    print(f"[ERROR] Connection failed: {e}")
except Exception as e:
    print(f"[ERROR] Exception: {e}")
    import traceback
    traceback.print_exc()

print("\n[DEBUG] Test complete")
