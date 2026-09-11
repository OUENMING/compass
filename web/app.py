"""The Compass decision-card UI — a small FastAPI app around one Compass instance.

The screen has two states and the quiet one is the point:

* **Watching** — the default. Compass has swept, found things, and decided they
  do not earn your attention. The page says so, and lists *what it passed over
  and why*, because a system that only shows you what it surfaced gives you no
  way to tell its silence from its blindness.
* **One card** — a situation that is genuinely irreversible and genuinely yours
  to decide. What happened, what it costs if ignored, when the last safe moment
  is, and two or three buttons. Clicking one really executes it, against the
  student record, and the receipt is shown.

Nothing auto-refreshes on a timer and nothing polls a model in the background
during the demo: a sweep is something you ask for, and you watch it happen. The
stream is honest about the slow part — the model reading the rules is the only
slow step and it says so while it runs.
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Allow `python web/app.py` from the repo root without an install.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from compass.agents.compass import Compass, CompassError  # noqa: E402
from compass.llm import describe  # noqa: E402
from compass.store import SchoolStore  # noqa: E402

STATIC = Path(__file__).resolve().parent / "static"
DATA_DIR = Path(__file__).resolve().parents[1] / "data"

app = FastAPI(title="Compass", docs_url=None, redoc_url=None)


class AppState:
    """Everything the process needs to remember between two HTTP requests."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        # The decisive state: the last sweep's decisions, keyed by finding id,
        # so a click on a card can be resolved back to the finding and option
        # that produced it.
        self.decisions: dict[str, Any] = {}
        self.receipts: list[dict] = []
        self.sweeping = False
        # One queue per connected EventSource client. The sweep runs in a thread
        # and pushes into these via the event loop.
        self.subscribers: list[asyncio.Queue] = []
        self.loop: asyncio.AbstractEventLoop | None = None


STATE = AppState()


def _compass() -> Compass:
    return Compass(data_dir=DATA_DIR, use_mcp=True, on_event=_broadcast)


def _broadcast(event: dict) -> None:
    """Push one sweep event to every connected browser. Called from a thread."""
    loop, subs = STATE.loop, list(STATE.subscribers)
    if loop is None:
        return
    for q in subs:
        loop.call_soon_threadsafe(q.put_nowait, event)


# --------------------------------------------------------------------------
# Static
# --------------------------------------------------------------------------


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------


@app.get("/api/state")
def state() -> dict:
    """Who Compass is watching, and whether anything is currently waiting on her."""
    store = SchoolStore(DATA_DIR)
    student = store.student
    return {
        "model": describe(),
        "today": store.today.isoformat(),
        "student": {
            "name": student.name,
            "id": student.id,
            "programme": student.programme,
            "stage": student.stage,
            "specialisation": student.specialisation,
            "first_generation": student.first_generation,
            "international": student.international,
            "credits_earned": student.credits_earned,
            "holds": [
                {"id": h.id, "kind": h.kind, "cleared": h.cleared,
                 "description": h.description, "resolvable_by": h.resolvable_by}
                for h in student.holds
            ],
            "degree_plan_filed": student.degree_plan_filed,
        },
        "sweeping": STATE.sweeping,
        "swept": bool(STATE.decisions),
    }


@app.get("/api/decisions")
def decisions() -> dict:
    """The last sweep's cards, with the receipts its auto-actions produced."""
    return {
        "cards": [
            {
                "verdict": d.verdict.value,
                "reason": d.reason,
                "finding": d.finding.model_dump(mode="json") if d.finding else None,
            }
            for d in STATE.decisions.values()
        ],
        "receipts": STATE.receipts,
    }


# --------------------------------------------------------------------------
# Sweeping
# --------------------------------------------------------------------------


class DecideRequest(BaseModel):
    finding_id: str
    option_id: str | None = None


class AskRequest(BaseModel):
    question: str


def _run_sweep() -> None:
    try:
        sweep = _compass().sweep()
    except Exception as exc:  # surface it in the UI rather than dying silently
        _broadcast({"stage": "error", "error": f"{type(exc).__name__}: {exc}"})
        STATE.sweeping = False
        return

    with STATE.lock:
        STATE.decisions = {d.finding.id: d for d in sweep.decisions if d.finding}
        STATE.receipts = [r.model_dump(mode="json") for r in sweep.receipts]
        STATE.sweeping = False
    _broadcast({"stage": "ready"})


@app.post("/api/sweep")
def start_sweep() -> dict:
    """Kick off a sweep. Progress arrives on /api/events; the result on /api/decisions."""
    if STATE.sweeping:
        return {"started": False, "reason": "a sweep is already running"}
    STATE.sweeping = True
    threading.Thread(target=_run_sweep, daemon=True).start()
    return {"started": True}


@app.post("/api/decide")
def decide(request: DecideRequest) -> dict:
    """Execute the option the student clicked, and return the receipts."""
    decision = STATE.decisions.get(request.finding_id)
    if decision is None:
        raise HTTPException(404, f"No finding {request.finding_id!r} on screen.")
    try:
        receipts = _compass().execute(decision, request.option_id)
    except CompassError as exc:
        # A refusal is a real answer, not a crash: the tools check the same
        # rules the registrar would, and the student should see which one bit.
        return {"ok": False, "error": str(exc)}

    payload = [r.model_dump(mode="json") for r in receipts]
    with STATE.lock:
        STATE.receipts.extend(payload)
        # The card is answered; drop it so the page falls back to "watching".
        STATE.decisions.pop(request.finding_id, None)

    _broadcast({"stage": "executed", "finding_id": request.finding_id,
                "receipts": payload})
    return {"ok": True, "receipts": payload}


@app.post("/api/ask")
def ask(request: AskRequest) -> dict:
    """Answer a free-form question via Pathfinder / Explainer."""
    question = request.question.strip()
    if not question:
        raise HTTPException(400, "Ask something.")
    return {"question": question, "answer": _compass().ask(question)}


@app.post("/api/reset")
def reset() -> dict:
    """Regenerate the synthetic dataset so the demo can be run again."""
    from compass.data.generate import write_all

    with STATE.lock:
        STATE.decisions = {}
        STATE.receipts = []
        STATE.sweeping = False
    write_all(DATA_DIR)
    _broadcast({"stage": "reset"})
    return {"ok": True}


# --------------------------------------------------------------------------
# Streaming
# --------------------------------------------------------------------------


@app.get("/api/events")
async def events() -> StreamingResponse:
    """Server-sent events carrying sweep progress and resolutions."""
    STATE.loop = asyncio.get_running_loop()
    client: asyncio.Queue = asyncio.Queue()
    STATE.subscribers.append(client)

    async def stream():
        try:
            yield "retry: 3000\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(client.get(), timeout=20)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"  # keeps proxies from closing us
                    continue
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            STATE.subscribers.remove(client)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
