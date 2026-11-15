"""Per run mutable state shared by tools. One instance per claim run, held in a context variable."""
from __future__ import annotations

import contextvars
import uuid
from dataclasses import dataclass, field

from app.rules import Decision, Facts

_state: contextvars.ContextVar["RunState | None"] = contextvars.ContextVar("run_state", default=None)


@dataclass
class RunState:
    claim_id: str
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    variant: str = "hardened"
    calls: list[dict] = field(default_factory=list)  # every model call made during this run, for cost and latency
    extracted: dict = field(default_factory=dict)
    flags: dict = field(default_factory=dict)
    evidence: dict = field(default_factory=dict)
    facts: Facts | None = None
    calc: dict = field(default_factory=dict)
    citations: list[dict] = field(default_factory=list)
    consistency: dict = field(default_factory=dict)
    decision: Decision | None = None
    memo: str = ""
    model_calls: int = 0
    tokens_by_model: dict = field(default_factory=dict)  # model id -> {input, output}, for exact cost per claim
    input_tokens: int = 0
    output_tokens: int = 0
    guardrail: dict = field(default_factory=dict)
    notes: list[dict] = field(default_factory=list)  # short-term memory: what the agents say to each other during this claim
    lessons: list[dict] = field(default_factory=list)  # long-term memory recalled for this claim
    signals: list[dict] = field(default_factory=list)  # advisory risk signals: they inform the human, never decide


_current: "RunState | None" = None  # fallback for tool code running on worker threads (one live run at a time)


def set_state(s: RunState) -> None:
    global _current
    _current = s
    _state.set(s)


def state() -> RunState:
    s = _state.get() or _current
    if s is None:
        raise RuntimeError("no active run")
    return s
