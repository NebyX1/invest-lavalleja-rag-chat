"""Planificación de la consulta: intención, perfil del inversor y consultas de búsqueda autosuficientes."""
import json
import re

import httpx

from prompt import MODES, PLANNER_PROMPT

CODE_RE = re.compile(r"\bO(0[1-9]|1[0-6])\b", re.I)
ZONE_RE = re.compile(r"\bZ([1-7])\b", re.I)


def find_focus(text: str):
    codes = list(dict.fromkeys("O" + m.group(1) for m in CODE_RE.finditer(text)))
    zones = list(dict.fromkeys("Z" + m.group(1) for m in ZONE_RE.finditer(text)))
    return codes, zones


def fallback_plan(msgs) -> dict:
    users = [m.content for m in msgs if m.role == "user"]
    q = users[-1]
    if len(q.split()) < 8 and len(users) > 1:
        q = f"{users[-2]} {q}"
    codes, zones = find_focus(users[-1])
    return {"intent": "profundizar" if codes else "explorar", "profile": "", "codes": codes, "zones": zones,
            "queries": [q[:400]], "depth": "media"}


def _clean(raw: dict, msgs) -> dict:
    fb = fallback_plan(msgs)
    intent = raw.get("intent") if raw.get("intent") in MODES else fb["intent"]
    codes = [c.upper() for c in raw.get("codes", []) if isinstance(c, str) and CODE_RE.fullmatch(c.strip())]
    zones = [z.upper() for z in raw.get("zones", []) if isinstance(z, str) and ZONE_RE.fullmatch(z.strip())]
    queries = [q[:400] for q in raw.get("queries", []) if isinstance(q, str) and q.strip()][:3] or fb["queries"]
    # lo que el usuario nombra explícitamente en su último mensaje siempre cuenta
    fc, fz = find_focus(msgs[-1].content)
    return {
        "intent": intent,
        "profile": str(raw.get("profile", ""))[:500],
        "codes": list(dict.fromkeys(fc + codes))[:2],
        "zones": list(dict.fromkeys(fz + zones))[:2],
        "queries": queries,
        "depth": raw.get("depth", "media"),
    }


async def plan(client: httpx.AsyncClient, host: str, key: str, model: str, msgs) -> dict:
    transcript = "\n".join(
        f"{'Usuario' if m.role == 'user' else 'Asesora'}: {m.content[:600]}" for m in msgs[-6:]
    )
    payload = {
        "model": model,
        "stream": False,
        "think": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": PLANNER_PROMPT},
            {"role": "user", "content": f"CONVERSACIÓN:\n{transcript}\n\nJSON:"},
        ],
        "options": {"temperature": 0, "num_predict": 350},
    }
    try:
        r = await client.post(
            f"{host}/api/chat", json=payload, headers={"Authorization": f"Bearer {key}"}, timeout=12
        )
        if r.status_code == 400:  # algunos modelos no admiten 'think'
            payload.pop("think")
            r = await client.post(
                f"{host}/api/chat", json=payload, headers={"Authorization": f"Bearer {key}"}, timeout=12
            )
        r.raise_for_status()
        text = r.json()["message"]["content"]
        raw = json.loads(text[text.index("{") : text.rindex("}") + 1])
        return _clean(raw, msgs)
    except Exception as e:  # noqa: BLE001
        print("Planner falló, uso heurística:", e)
        return fallback_plan(msgs)
