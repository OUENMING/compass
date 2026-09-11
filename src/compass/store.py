"""Loading and mutating the school dataset.

This is the single source of truth for both access paths Compass supports:

* the **MCP server** (``compass.tools.school_mcp_server``) wraps a ``SchoolStore``
  in FastMCP tools, and
* the **direct-tool fallback** (``compass.tools.school_tools``) wraps the same
  store in Strands ``@tool`` functions.

Keeping one store behind both means the fallback is a genuine drop-in rather
than a second implementation that can drift.

Writes go straight to disk, and so do reads. Files are small and the demo is not
concurrent, so re-parsing on every access is simpler and more debuggable than any
in-process cache invalidation — and the alternative is a real bug rather than a
theoretical one: the agent's tools and the orchestrator are different objects,
often in different processes, so a cached course list goes stale the moment one
of them takes a seat.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date
from pathlib import Path

from .models import (
    Announcement,
    CalendarEvent,
    Course,
    DegreeRequirements,
    Receipt,
    StudentRecord,
)


def default_data_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "data"


class SchoolStore:
    """Read/write access to a generated dataset directory."""

    def __init__(self, data_dir: Path | str | None = None):
        self.dir = Path(data_dir) if data_dir else default_data_dir()
        if not (self.dir / "meta.json").exists():
            raise FileNotFoundError(
                f"No dataset in {self.dir}. Generate one first:\n"
                f"    python -m compass.data.generate"
            )

    # -- low-level ---------------------------------------------------------

    def _read(self, name: str):
        return json.loads((self.dir / f"{name}.json").read_text())

    def _write_atomic(self, name: str, data) -> None:
        """Write via a temp file + rename so a crash can't leave half a file."""
        target = self.dir / f"{name}.json"
        fd, tmp = tempfile.mkstemp(dir=self.dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
                fh.write("\n")
            os.replace(tmp, target)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    # -- reads -------------------------------------------------------------

    @property
    def meta(self) -> dict:
        return self._read("meta")

    @property
    def today(self) -> date:
        """The demo's 'today'. Fixed in the dataset so the demo is repeatable."""
        return date.fromisoformat(self.meta["demo_today"])

    @property
    def courses(self) -> list[Course]:
        return [Course(**c) for c in self._read("courses")]

    def course(self, code: str) -> Course | None:
        code = code.strip().upper()
        return next((c for c in self.courses if c.code == code), None)

    @property
    def requirements(self) -> DegreeRequirements:
        return DegreeRequirements(**self._read("degree_requirements"))

    @property
    def student(self) -> StudentRecord:
        """Always re-read: actions in another process may have changed it."""
        return StudentRecord(**self._read("student"))

    @property
    def calendar(self) -> list[CalendarEvent]:
        return [CalendarEvent(**e) for e in self._read("calendar")]

    @property
    def announcements(self) -> list[Announcement]:
        return [Announcement(**a) for a in self._read("announcements")]

    def event(self, event_id: str) -> CalendarEvent | None:
        return next((e for e in self.calendar if e.id == event_id), None)

    # -- writes ------------------------------------------------------------

    def save_student(self, student: StudentRecord) -> None:
        self._write_atomic("student", student.model_dump(mode="json"))

    def take_seat(self, code: str, delta: int) -> Course | None:
        """Adjust a module's enrolment and persist it. Returns the updated course.

        Seats are the only part of the catalogue that moves, and they have to
        move from a *fresh* read. ``self.course(code)`` hands back a new object
        on every call — mutating that copy and saving would quietly do nothing,
        which is exactly the kind of bug that makes a demo look like it worked.
        """
        courses = self.courses
        target = next((c for c in courses if c.code == code.strip().upper()), None)
        if target is None:
            return None
        target.enrolled = max(target.enrolled + delta, 0)
        self._write_atomic("courses", [c.model_dump(mode="json") for c in courses])
        return target

    def record_receipt(self, receipt: Receipt) -> None:
        """Append to the audit trail.

        Every action Compass takes writes here, including the ones it took
        without asking. That is what makes "it did real work" checkable rather
        than a claim in a video.
        """
        with (self.dir / "receipts.jsonl").open("a") as fh:
            fh.write(json.dumps(receipt.model_dump(mode="json")) + "\n")

    def receipts(self) -> list[Receipt]:
        path = self.dir / "receipts.jsonl"
        if not path.exists():
            return []
        out = []
        for line in path.read_text().splitlines():
            if line.strip():
                out.append(Receipt(**json.loads(line)))
        return out
