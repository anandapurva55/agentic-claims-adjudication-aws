"""Run events. The UI draws the agent graph from this stream, so the lightning shows real execution."""
from __future__ import annotations

import asyncio
import contextvars
import time
from dataclasses import dataclass, field
from typing import Any

_bus: contextvars.ContextVar["EventBus | None"] = contextvars.ContextVar("bus", default=None)


_current: "EventBus | None" = None  # fallback for tool code running on worker threads


@dataclass
class EventBus:
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    seq: int = 0
    t0: float = field(default_factory=time.perf_counter)
    loop: asyncio.AbstractEventLoop = field(default_factory=asyncio.get_running_loop)

    def _put(self, item: Any) -> None:
        self.loop.call_soon_threadsafe(self.queue.put_nowait, item)

    def emit(self, type: str, **data: Any) -> None:
        self.seq += 1
        self._put({"seq": self.seq, "t": round(time.perf_counter() - self.t0, 3), "type": type, **data})

    def close(self) -> None:
        self._put(None)


def use_bus(bus: EventBus) -> None:
    global _current
    _current = bus
    _bus.set(bus)


def emit(type: str, **data: Any) -> None:
    bus = _bus.get() or _current
    if bus:
        bus.emit(type, **data)


def node(id: str, state: str, detail: str = "") -> None:
    emit("node", id=id, state=state, detail=detail)


def edge(src: str, dst: str, label: str = "") -> None:
    emit("edge", src=src, dst=dst, label=label)


def log(node_id: str, text: str) -> None:
    emit("log", node=node_id, text=text)
