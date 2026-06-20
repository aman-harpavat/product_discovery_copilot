from __future__ import annotations

from uuid import uuid4


def make_run_id() -> str:
    return f"run_{uuid4().hex[:8]}"
