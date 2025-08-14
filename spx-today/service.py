from __future__ import annotations

import os
import socket
import time
import uuid
from typing import Any, Dict, Optional

import httpx
import yfinance as yf
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

try:
    from anthropic import Anthropic
except Exception:
    Anthropic = None  # optional

PORT = 8744
TICKER = "^GSPC"  # S&P 500 index


# ----- models -----

class Health(BaseModel):
    ok: bool
    service: str
    version: str
    id: str
    uptime_s: int
    requests: int


class SpxSummary(BaseModel):
    asof: str
    date: str
    open: float
    high: float
    low: float
    close: float
    change: float
    change_pct: float
    source: str
    human: Optional[str] = None


class ServiceCatalog(BaseModel):
    ident: str
    title: str
    endpoints: Dict[str, str]
    about: Dict[str, Any]


# ----- small helpers -----

def _local_addr() -> str:
    try:
        return socket.gethostbyname(socket.gethostname())
    except Exception:
        return "127.0.0.1"


def _r(x: float, n: int = 2) -> float:
    try:
        return round(float(x), n)
    except Exception:
        return float("nan")


def _nl_blurb(s: SpxSummary) -> str:
    # If Anthropic isn't available or no key is set, just return a terse one-liner.
    if Anthropic is None or not os.getenv("ANTHROPIC_API_KEY"):
        updown = "up" if s.change >= 0 else "down"
        return f"S&P 500 closed {updown} {abs(s.change):.2f} ({s.change_pct:.2f}%) at {s.close:.2f}."

    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    model = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
    prompt = (
        "Write one sentence summarizing today's S&P 500 move in a neutral tone. "
        f"Close: {s.close:.2f}. Change: {s.change:+.2f} ({s.change_pct:+.2f}%). "
        "Keep it under 20 words. No emojis."
    )

    try:
        msg = client.messages.create(
            model=model,
            max_tokens=60,
            temperature=0.2,
            messages=[{"role": "user", "content": prompt}],
        )
        text = ""
        for part in getattr(msg, "content", []):
            t = getattr(part, "text", None)
            if t:
                text += t
        text = (text or "").strip()
        return text or f"S&P 500 moved {s.change:+.2f} ({s.change_pct:+.2f}%)."
    except Exception:
        updown = "up" if s.change >= 0 else "down"
        return f"S&P 500 closed {updown} {abs(s.change):.2f} ({s.change_pct:.2f}%)."


def _fetch_spx_snapshot() -> SpxSummary:
    # Grab a few recent daily bars to handle weekends/holidays.
    hist = yf.Ticker(TICKER).history(period="5d", interval="1d", auto_adjust=False)
    if hist is None or hist.empty or hist.dropna().empty:
        raise RuntimeError("no data returned")

    clean = hist.dropna()
    last = clean.iloc[-1]
    prev = clean.iloc[-2] if len(clean) >= 2 else None

    close = float(last["Close"])
    open_ = float(last["Open"])
    high = float(last["High"])
    low = float(last["Low"])

    prev_close = float(prev["Close"]) if prev is not None else close
    change = close - prev_close
    change_pct = (change / prev_close * 100.0) if prev_close else 0.0

    idx = clean.index[-1]
    try:
        date_str = idx.date().isoformat()
        asof = idx.isoformat()
    except Exception:
        date_str = str(idx)
        asof = str(idx)

    return SpxSummary(
        asof=str(asof),
        date=str(date_str),
        open=_r(open_),
        high=_r(high),
        low=_r(low),
        close=_r(close),
        change=_r(change),
        change_pct=_r(change_pct),
        source="yfinance",
    )


# ----- service -----

class SpxToday:
    def __init__(self, name: str = "spx-today", version: str = "0.1.0"):
        self.name = name
        self.version = version
        self.ident = f"spx-{uuid.uuid4().hex[:8]}"
        self.started = time.time()
        self.req_count = 0

        app = FastAPI(title="SPX Today")

        @app.get("/svc/healthz", response_model=Health)
        def healthz():
            return Health(
                ok=True,
                service=self.name,
                version=self.version,
                id=self.ident,
                uptime_s=int(time.time() - self.started),
                requests=self.req_count,
            )

        @app.get("/svc/summary", response_model=SpxSummary)
        def summary(human: bool = Query(default=False, description="include short NL blurb if available")):
            self.req_count += 1
            try:
                snap = _fetch_spx_snapshot()
                if human:
                    snap.human = _nl_blurb(snap)
                return snap
            except Exception as e:
                raise HTTPException(status_code=502, detail=f"data fetch failed: {e}")

        @app.get("/svc/catalog", response_model=ServiceCatalog)
        def catalog():
            base = os.getenv("PUBLIC_URL") or f"http://{_local_addr()}:{PORT}"
            return ServiceCatalog(
                ident=self.ident,
                title="SPX Today (latest S&P 500 daily summary)",
                endpoints={
                    "healthz": f"{base}/svc/healthz",
                    "summary": f"{base}/svc/summary",
                },
                about={
                    "ticker": TICKER,
                    "implementation": "python-fastapi",
                    "anthropic": bool(os.getenv("ANTHROPIC_API_KEY")),
                },
            )

        @app.post("/svc/announce")
        async def announce():
            # Registers this service with a Nanda index / registry.
            public = (os.getenv("PUBLIC_URL") or "").strip()
            registry = (os.getenv("REGISTRY_URL") or "").strip()
            if not public or not registry:
                raise HTTPException(status_code=400, detail="PUBLIC_URL and REGISTRY_URL must be set")

            payload = {
                "agent_id": self.ident,
                "agent_url": public,
                "protocols": ["https", "http"],
                "facts": {"service": self.name, "version": self.version, "role": "spx-today"},
            }

            try:
                async with httpx.AsyncClient(timeout=6.0) as client:
                    r = await client.post(f"{registry}/register", json=payload)
                    r.raise_for_status()
                return {"ok": True, "announced_to": registry, "as": self.ident}
            except Exception as e:
                raise HTTPException(status_code=502, detail=f"announce failed: {e}")

        self.app = app

    def run(self):
        import uvicorn
        uvicorn.run(self.app, host="0.0.0.0", port=PORT)
