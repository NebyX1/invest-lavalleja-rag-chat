"""Conversación de prueba: python scripts/ask.py "turno 1" "turno 2" ... (puerto 8010)"""
import json
import sys
import time

import httpx

sys.stdout.reconfigure(encoding="utf-8")
history = []
for q in sys.argv[1:]:
    history.append({"role": "user", "content": q})
    t0, first, out = time.time(), None, []
    print(f"\n>>> {q}")
    with httpx.stream("POST", "http://127.0.0.1:8010/api/chat", json={"messages": history}, timeout=90) as r:
        ev = None
        for line in r.iter_lines():
            if line.startswith("event: "):
                ev = line[7:]
            elif line.startswith("data: ") and ev == "token":
                first = first or time.time() - t0
                out.append(json.loads(line[6:]))
            elif line.startswith("data: ") and ev == "reset":
                out.clear()
            elif line.startswith("data: ") and ev in ("status", "tools"):
                print(f"  ({ev}: {json.loads(line[6:])})")
            elif line.startswith("data: ") and ev == "error":
                print("ERROR:", line)
    answer = "".join(out)
    history.append({"role": "assistant", "content": answer})
    print(answer)
    print(f"[{first or 0:.1f}s / {time.time()-t0:.1f}s]")
