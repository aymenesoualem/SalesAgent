"""
Thread-safe, in-memory log of live call activity (transcripts, tool calls, status,
errors), shared between the async SIP agent (agents/sip_agent.py, running its own
background event loop) and the Streamlit console (sip_interface.py, polling from the
main thread). Deliberately not persisted anywhere — it's a live monitoring feed, not
an audit log (support tickets already cover persistent follow-up records).
"""

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Literal, Optional

EventKind = Literal["transcript_caller", "transcript_agent", "tool_call", "status", "error"]


@dataclass
class CallEvent:
    timestamp: float
    kind: EventKind
    text: str
    call_id: Optional[str] = None


_lock = threading.Lock()
_events: deque[CallEvent] = deque(maxlen=500)


def log_event(kind: EventKind, text: str, call_id: Optional[str] = None) -> None:
    with _lock:
        _events.append(CallEvent(timestamp=time.time(), kind=kind, text=text, call_id=call_id))


def get_events() -> list[CallEvent]:
    with _lock:
        return list(_events)


def clear_events() -> None:
    with _lock:
        _events.clear()
