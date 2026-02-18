# Compact Context (2026-02-17)

## Goal
End-to-end test: COM6 -> COM4 -> AI reply visible. OpenWebUI autostart from bot, no send before AI response ready.

## Current State
- auto_reply_priv.py: OpenWebUI autostart added, streaming toggle (ai.streaming). Non-streaming default.
- lara_config.yaml: ai.streaming=false, openwebui_autostart=true, OpenWebUI env vars set.
- OpenWebUI sometimes not reachable on http://127.0.0.1:8080.
- Error seen: JSONDecodeError "Unexpected token 'd' ... data: {...}" due to SSE-style responses parsed as JSON.

## Changes in This Step
- auto_reply_priv.py: non-streaming call now tolerates SSE "data:" lines and falls back to normal JSON.
- lara_cli_bridge.py: forces "stream": false and tolerates SSE "data:" responses.

## How To Run Quick Test
1) Start OpenWebUI (or rely on bot autostart).
2) Start auto_reply_priv.py.
3) Send test message from COM6 to COM4.
4) Expect AI response after full completion.

## Known Risks
- If OpenWebUI returns SSE even with stream=false, parsing should now handle first JSON line.
- If OpenWebUI not running, bot falls back to stub AI.

## Files of Interest
- auto_reply_priv.py
- lara_cli_bridge.py
- lara_config.yaml
