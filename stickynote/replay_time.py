from __future__ import annotations

import time as _real_time
from datetime import datetime
from typing import Any

from stickynote.replay import _replay_context


def now(tz: Any = None) -> datetime:
    """Return recorded time during replay, real time otherwise."""
    session = _replay_context.get(None)
    if session is not None and session._deterministic_time:
        seq, recorded = session._replay_time()
        if recorded is not None:
            return datetime.fromisoformat(str(recorded))
        real = datetime.now(tz)
        session._record_time(seq, real.isoformat())
        return real
    return datetime.now(tz)


def monotonic() -> float:
    """Return recorded monotonic time during replay, real time otherwise."""
    session = _replay_context.get(None)
    if session is not None and session._deterministic_time:
        seq, recorded = session._replay_time()
        if recorded is not None:
            return float(recorded)
        real = _real_time.monotonic()
        session._record_time(seq, real)
        return real
    return _real_time.monotonic()
