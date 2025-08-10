import os
import re
import json
import time
from datetime import datetime
from typing import Dict, Any, List

from nanda_adapter import NANDA  

MEM_PATH = os.path.join(os.path.dirname(__file__), "memory.json")
RATE_LIMIT_PER_MIN = 60  

def load_mem() -> Dict[str, Any]:
    if os.path.exists(MEM_PATH):
        try:
            with open(MEM_PATH, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"notes": [], "metrics": {"messages": 0, "start_ts": time.time()}}

def save_mem(mem: Dict[str, Any]) -> None:
    tmp = MEM_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(mem, f, indent=2)
    os.replace(tmp, MEM_PATH)

mem = load_mem()
_last_bucket = int(time.time() // 60)
_msgs_in_bucket = 0

def ratelimit_ok() -> bool:
    global _last_bucket, _msgs_in_bucket
    now_bucket = int(time.time() // 60)
    if now_bucket != _last_bucket:
        _last_bucket = now_bucket
        _msgs_in_bucket = 0
    if _msgs_in_bucket >= RATE_LIMIT_PER_MIN:
        return False
    _msgs_in_bucket += 1
    return True

# ---------------- tools ----------------

def tool_calc(expr: str) -> str:
    """Very basic, no external deps. Avoids names and builtins."""
    expr = re.sub(r"[^0-9+\-*/(). ]", "", expr)
    try:
        val = eval(expr, {"__builtins__": {}}, {})
        return f"{expr} = {val}"
    except Exception as e:
        return f"Calc error: {e}"

def tool_remember(text: str) -> str:
    item = {"text": text.strip(), "ts": datetime.utcnow().isoformat() + "Z"}
    mem["notes"].append(item)
    save_mem(mem)
    return f"Saved: “{text.strip()}”"

def tool_recall(query: str) -> str:
    q = query.strip().lower()
    hits: List[Dict[str, Any]]
    if q:
        hits = [n for n in mem["notes"] if q in n["text"].lower()]
    else:
        hits = mem["notes"][-5:]
    if not hits:
        return "No memory found."
    lines = [f"- {h['text']} (@{h['ts']})" for h in hits[-5:]]
    return "Recent memory:\n" + "\n".join(lines)

def try_tools(message_text: str) -> str | None:
    m = re.match(r"^/(calc|remember|recall)\s*(.*)$", message_text.strip(), flags=re.I)
    if not m:
        return None
    cmd, arg = m.group(1).lower(), m.group(2)
    if cmd == "calc":
        return tool_calc(arg)
    if cmd == "remember":
        return tool_remember(arg)
    if cmd == "recall":
        return tool_recall(arg)
    return f"Unknown command: /{cmd}"

# -------------- improvement fn (what NANDA calls) --------------

def create_improvement_fn():
    """
    Return a function(message_text:str) -> str that NANDA will call.
    We keep it deterministic & offline for easy local demo.
    """
    def improve(message_text: str) -> str:
        # 1) Rate limit
        if not ratelimit_ok():
            return "Rate limit exceeded. Try again in a minute."

        # 2) Tooling
        tool_out = try_tools(message_text)
        if tool_out is not None:
            mem["metrics"]["messages"] += 1
            save_mem(mem)
            return tool_out

        # 3) Tiny "LLM-lite": safe transform + memory hint
        user = str(message_text)
        if "ignore previous" in user.lower():
            resp = "I can’t ignore my instructions, but happy to help."
        else:
            resp = (
                user.replace("hello", "greetings")
                    .replace("Hello", "Greetings")
                    .replace("goodbye", "farewell")
            )

        memory_hint = ""
        if mem["notes"]:
            recent = ", ".join(n["text"] for n in mem["notes"][-2:])
            memory_hint = f" (FYI I remember: {recent})"

        mem["metrics"]["messages"] += 1
        save_mem(mem)
        return f"[nanda] {resp}{memory_hint}"
    return improve



if __name__ == "__main__":

    nanda = NANDA(create_improvement_fn())


    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    domain = os.getenv("DOMAIN_NAME", "localhost")

    # Starts the local HTTP server that exposes /api/health, /api/send, etc.
    # Default bind is 127.0.0.1:5000 (works great for local testing).
    nanda.start_server_api(anthropic_key, domain)