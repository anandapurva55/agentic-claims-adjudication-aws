"""The agent to agent conversation is bounded, ordered and can be switched off. Tested with stub agents, no AWS."""
import asyncio

import pytest
from app.config import settings
from app.events import EventBus, use_bus
from app.runner import _collaborate
from app.runstate import RunState, set_state


class StubAgent:
    def __init__(self, name, state, reply):
        self.name, self.state, self.reply, self.calls = name, state, reply, []

    async def invoke_async(self, prompt):
        self.calls.append(prompt)
        self.state.notes.append({"sender": self.name, "to": self.reply["to"], "kind": "answer", "text": self.reply["text"]})
        return type("R", (), {"metrics": None})()


class StubTeam:
    def __init__(self, agents):
        self.agents = agents


def _setup():
    use_bus(EventBus())
    s = RunState("CLM-TEST")
    set_state(s)
    return s


def run(coro):
    return asyncio.run(coro)


def test_a_question_is_routed_to_the_addressee_and_answered_once():
    async def go():
        s = _setup()
        intake = StubAgent("intake", s, {"to": "fraud", "text": "Reconsidered: still not intoxicated."})
        s.notes.append({"sender": "fraud", "to": "intake", "kind": "question", "text": "Narrative mentions a wedding. Sure?"})
        await _collaborate(s, StubTeam({"intake": intake}))
        assert len(intake.calls) == 1 and "wedding" in intake.calls[0]
        assert [n["kind"] for n in s.notes] == ["question", "answer"]
        return s
    run(go())


def test_collaboration_is_bounded_by_rounds(monkeypatch):
    monkeypatch.setattr(settings, "collab_rounds", 1)

    async def go():
        s = _setup()

        class Chatty(StubAgent):
            async def invoke_async(self, prompt):  # every answer provokes a new question: an endless argument if unbounded
                await super().invoke_async(prompt)
                self.state.notes.append({"sender": "intake", "to": "fraud", "kind": "question", "text": "And another thing?"})
                return type("R", (), {"metrics": None})()

        intake = Chatty("intake", s, {"to": "fraud", "text": "answer"})
        fraud = StubAgent("fraud", s, {"to": "intake", "text": "ok"})
        s.notes.append({"sender": "fraud", "to": "intake", "kind": "question", "text": "first question"})
        await _collaborate(s, StubTeam({"intake": intake, "fraud": fraud}))
        assert len(intake.calls) == 1 and len(fraud.calls) == 0, "round two must not happen with collab_rounds=1"
    run(go())


def test_collab_rounds_zero_turns_it_off(monkeypatch):
    monkeypatch.setattr(settings, "collab_rounds", 0)

    async def go():
        s = _setup()
        intake = StubAgent("intake", s, {"to": "fraud", "text": "x"})
        s.notes.append({"sender": "fraud", "to": "intake", "kind": "question", "text": "q"})
        await _collaborate(s, StubTeam({"intake": intake}))
        assert intake.calls == []
    run(go())


def test_questions_to_unknown_agents_are_ignored():
    async def go():
        s = _setup()
        s.notes.append({"sender": "fraud", "to": "adjudicator", "kind": "question", "text": "hello?"})
        agent = StubAgent("intake", s, {"to": "fraud", "text": "x"})
        await _collaborate(s, StubTeam({"intake": agent}))
        assert agent.calls == []
    run(go())


@pytest.mark.parametrize("kind", ["delete", "", "order"])
def test_post_note_rejects_bad_kinds(kind):
    from app.tools import post_note

    async def go():
        set_state(RunState("CLM-TEST"))
        use_bus(EventBus())
        fn = getattr(post_note, "_tool_func", None) or post_note.__wrapped__
        return fn("fraud", "intake", kind, "text")
    assert asyncio.run(go()).startswith("rejected")
