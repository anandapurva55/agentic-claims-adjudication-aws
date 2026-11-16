"""Runs are serialised per task, and CloudFront gives up on a response that sends nothing for 60 seconds. A request waiting for its turn used to send nothing, so the
fourth simultaneous user got a 504. Now a waiting request says where it is in the queue at a steady interval (which also keeps the connection alive), and a long
queue is refused up front with a clear message. These tests use a real server and real streamed requests, because the test clients buffer a whole response and would
hide the thing that matters: when the bytes arrive."""
import asyncio
import json
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
import uvicorn
from app.api import main
from app.api.main import app
from app.config import settings

CLAIM = json.load(open("evals/golden/cases.json"))[0]["claim_id"]


def wait_until(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def server(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "runtime_dir", tmp_path)
    monkeypatch.setattr(settings, "queue_keepalive_s", 0.05)
    monkeypatch.setattr(settings, "max_queue", 2)
    gate, started = threading.Event(), []

    async def fake_run(claim_id, mode, **kw):  # a run that takes as long as the test lets it
        started.append(claim_id)
        n = len(started)
        while not gate.is_set():
            await asyncio.sleep(0.01)
        yield {"type": "result", "n": n}
    monkeypatch.setattr(main, "run_claim", fake_run)
    monkeypatch.setattr(main, "_live_lock", asyncio.Semaphore(1))  # fresh for every test, bound to the server's own loop
    monkeypatch.setattr(main, "_queue", [])
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="off"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    assert wait_until(lambda: srv.started), "the test server did not start"
    port = srv.servers[0].sockets[0].getsockname()[1]
    yield SimpleNamespace(url=f"http://127.0.0.1:{port}", gate=gate, started=started)
    gate.set()
    srv.should_exit = True
    thread.join(timeout=5)


def start(server, results: dict, key: str, stop_after_lines: int | None = None) -> threading.Thread:
    """Start a run in a thread, collecting every line as it arrives. stop_after_lines closes the connection early, like a browser tab that was closed."""
    results[key] = {"status": None, "lines": [], "headers": {}}

    def work():
        with httpx.stream("POST", f"{server.url}/api/claims/{CLAIM}/run?mode=replay", timeout=30) as r:
            results[key]["status"], results[key]["headers"] = r.status_code, dict(r.headers)
            for line in r.iter_lines():
                results[key]["lines"].append(line)
                if stop_after_lines and len(results[key]["lines"]) >= stop_after_lines:
                    return
    t = threading.Thread(target=work, daemon=True)
    t.start()
    return t


def queued(lines) -> list[int]:
    return [json.loads(lines[i + 1][6:])["position"] for i, line in enumerate(lines) if line == "event: queued"]


def results_of(lines) -> list[int]:
    return [json.loads(line[6:])["n"] for line in lines if line.startswith("data: ") and '"n"' in line]


def test_a_waiting_request_keeps_saying_where_it_is_and_runs_when_its_turn_comes(server):
    out = {}
    a = start(server, out, "a")
    assert wait_until(lambda: len(server.started) == 1)
    b = start(server, out, "b")
    assert wait_until(lambda: len(queued(out["b"]["lines"])) >= 3), "the waiting request must send a queued event at every interval, not only once"
    assert queued(out["a"]["lines"]) == []  # the run that holds the turn is not told it is queued
    assert set(queued(out["b"]["lines"])) == {1}
    server.gate.set()
    a.join(5), b.join(5)
    assert results_of(out["a"]["lines"]) == [1] and results_of(out["b"]["lines"]) == [2]  # a second run only after the first
    assert out["b"]["lines"][-2:] == ["event: end", "data: {}"] or "event: end" in out["b"]["lines"]


def test_the_queue_is_first_come_first_served_and_positions_are_honest(server):
    out = {}
    threads = [start(server, out, "a")]
    assert wait_until(lambda: len(server.started) == 1)
    threads.append(start(server, out, "b"))
    assert wait_until(lambda: queued(out["b"]["lines"]) != [])
    threads.append(start(server, out, "c"))
    assert wait_until(lambda: queued(out["c"]["lines"]) != [])
    assert queued(out["b"]["lines"])[0] == 1 and queued(out["c"]["lines"])[0] == 2
    server.gate.set()
    for t in threads:
        t.join(5)
    assert [results_of(out[k]["lines"]) for k in "abc"] == [[1], [2], [3]]


def test_a_queue_that_is_full_is_refused_up_front_with_a_retry_hint_and_the_others_are_unaffected(server):
    out = {}
    threads = [start(server, out, "a")]
    assert wait_until(lambda: len(server.started) == 1)
    for key in ("b", "c"):  # max_queue is 2
        threads.append(start(server, out, key))
        assert wait_until(lambda key=key: queued(out[key]["lines"]) != [])
    d = start(server, out, "d")
    d.join(5)
    assert out["d"]["status"] == 503 and out["d"]["headers"].get("retry-after") == "30"
    server.gate.set()
    for t in threads:
        t.join(5)
    assert [results_of(out[k]["lines"]) for k in "abc"] == [[1], [2], [3]]


def test_a_client_that_gives_up_while_waiting_does_not_hold_a_place_or_the_lock(server):
    out = {}
    a = start(server, out, "a")
    assert wait_until(lambda: len(server.started) == 1)
    b = start(server, out, "b", stop_after_lines=2)  # reads the first queued event, then closes the connection
    b.join(5)
    assert wait_until(lambda: main._queue == []), "the abandoned request still holds a place in the queue"
    c = start(server, out, "c")
    assert wait_until(lambda: queued(out["c"]["lines"]) != [])
    assert queued(out["c"]["lines"])[0] == 1, "the abandoned request still counts ahead of c"
    server.gate.set()
    a.join(5), c.join(5)
    assert results_of(out["c"]["lines"]) == [2]  # c ran right after a: the lock was not leaked by b
    assert wait_until(lambda: not main._live_lock.locked() and main._queue == [])


def test_waiters_run_in_arrival_order_even_when_their_keepalives_do_not_line_up(server, monkeypatch):
    """The failure this pins: a waiter that said 'still waiting' used to issue a fresh acquire, which sent it to the back of the lock's line. Waiters whose timeouts
    fall in a different order from their arrivals then ran out of order, and the place each was told did not match who ran next. Arrivals 0.035 s apart against a
    0.05 s keepalive make the timeouts wrap around, so with the old code the order is scrambled on every run, not only on a slow machine."""
    monkeypatch.setattr(settings, "max_queue", 5)
    out = {}
    threads = [start(server, out, "a")]
    assert wait_until(lambda: len(server.started) == 1)
    for key in "bcde":
        threads.append(start(server, out, key))
        time.sleep(0.035)
    assert wait_until(lambda: all(len(queued(out[k]["lines"])) >= 3 for k in "bcde")), "every waiter must keep saying where it is"
    for rank, key in enumerate("bcde", start=1):  # nobody has left yet, so each place is exactly the arrival rank, at every keepalive
        assert set(queued(out[key]["lines"])) == {rank}, key
    server.gate.set()
    for t in threads:
        t.join(5)
    assert [results_of(out[k]["lines"]) for k in "abcde"] == [[1], [2], [3], [4], [5]]  # the place shown was who ran next


def test_a_wait_that_is_given_up_never_holds_a_place_or_the_lock(monkeypatch):
    """_abandon covers the three moments a request can stop waiting: after the lock was granted to it, while it is still in line, and before it ever ran."""
    async def scenario():
        lock = asyncio.Semaphore(1)
        monkeypatch.setattr(main, "_live_lock", lock)
        granted = asyncio.ensure_future(lock.acquire())  # the lock is granted at the very moment the client goes away
        await asyncio.sleep(0)
        assert lock.locked()
        main._abandon(granted)
        await asyncio.sleep(0.01)
        assert not lock.locked(), "a grant nobody will use must be handed back, or the lock stays held until the task restarts"
        await lock.acquire()  # someone else is running
        pending = asyncio.ensure_future(lock.acquire())  # still in line
        await asyncio.sleep(0)
        assert not pending.done()
        main._abandon(pending)
        await asyncio.sleep(0.01)
        lock.release()  # the runner finishes: a cancelled waiter must not take the lock
        assert pending.cancelled() and not lock.locked()
        early = asyncio.ensure_future(lock.acquire())  # given up before it ever started
        main._abandon(early)
        await asyncio.sleep(0.01)
        assert not lock.locked()
        await asyncio.wait_for(lock.acquire(), 0.1)  # and the next request can still run at once
    asyncio.run(scenario())
