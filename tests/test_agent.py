"""Tests for `agent.triage()`.

Two layers, per the story's decision log:

- Fake-model tests (`GenericFakeChatModel`, no API key needed) drive the
  real `agent.py` retry/validation logic. Most of them call the real
  (unmodified) `mcp/triage_server.py` `get_ticket`/`get_customer_history`
  functions in-process against a `tmp_path`-seeded `app.db`, scripting the
  model's tool calls exactly like `tests/test_load_seed.py`'s existing
  import-by-path pattern; `test_unknown_ticket_id_...` instead goes through
  the real MCP stdio subprocess via the real `_get_mcp_tools()`. These
  always run and stay deterministic.
- One live-gated test calls the real configured provider (Gemini) for
  T-1042 and T-1099 against the real seed data -- the only way to get any
  automated signal on CAP-6's injection resistance. It skips cleanly when
  `GEMINI_API_KEY` isn't set.
"""

import asyncio
import importlib.util
import os
from pathlib import Path

import pytest
from groq import RateLimitError as GroqRateLimitError
from langchain_core.exceptions import ModelRateLimitError
from langchain_core.language_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import tool as lc_tool

import agent
from load_seed import load_seed

REPO_ROOT = Path(__file__).resolve().parent.parent
SEED_DIR = REPO_ROOT / "seed"

VALID_DECISION = {
    "category": "billing",
    "priority": "P2",
    "route": "billing-team",
    "rationale": "Double charge is a money problem, per the billing category.",
}
INVALID_DECISION = {  # missing "rationale" -- fails TriageDecision validation
    "category": "billing",
    "priority": "P2",
    "route": "billing-team",
}


def _import_triage_server():
    """Import mcp/triage_server.py by file path.

    Same reasoning as `tests/test_load_seed.py`: the repo's top-level `mcp/`
    directory shares its name with the installed `mcp` SDK package that
    file itself imports, so import-by-path sidesteps the collision.
    """
    path = REPO_ROOT / "mcp" / "triage_server.py"
    spec = importlib.util.spec_from_file_location("triage_server_for_agent_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeToolCallingModel(GenericFakeChatModel):
    """`GenericFakeChatModel` doesn't implement `bind_tools`; `create_agent`
    calls it during every model turn. Since every call to this fake model is
    fully scripted up front, binding tools is a no-op -- we just need to not
    raise `NotImplementedError`.
    """

    def bind_tools(self, tools, **kwargs):
        return self


def _seed_and_wrap_tools(tmp_path, monkeypatch):
    """Point a fresh `mcp/triage_server.py` import at a `tmp_path` app.db,
    seed it, and wrap its real (unmodified) `get_ticket`/`get_customer_history`
    functions as LangChain tools that record every call made through them.

    This calls those real functions in-process (not through the real MCP
    stdio subprocess: the subprocess's own `DB_PATH` is fixed relative to
    its file, not overridable per-test) -- `agent.py`'s own `_get_mcp_tools`
    is monkeypatched to return these instead for the fake-model tests below.
    """
    triage_server = _import_triage_server()
    db_path = tmp_path / "app.db"
    monkeypatch.setattr(triage_server, "DB_PATH", db_path)
    load_seed(db_path=db_path, seed_dir=SEED_DIR)

    calls: list[tuple[str, dict]] = []

    @lc_tool
    def get_ticket(ticket_id: str) -> dict:
        """Return one support ticket by its ID: customer_id, created_at, text."""
        calls.append(("get_ticket", {"ticket_id": ticket_id}))
        return triage_server.get_ticket(ticket_id)

    @lc_tool
    def get_customer_history(customer_id: str) -> dict:
        """Return a customer's plan, open ticket count and other ticket IDs."""
        calls.append(("get_customer_history", {"customer_id": customer_id}))
        return triage_server.get_customer_history(customer_id)

    return [get_ticket, get_customer_history], calls


def _patch_agent(monkeypatch, tools, fake_model):
    """Wire agent.py's internals to the given (fake) tools and model, bypassing
    the real MCP subprocess and the real provider for these deterministic tests.
    """

    async def _fake_get_mcp_tools():
        return tools

    monkeypatch.setattr(agent, "_get_mcp_tools", _fake_get_mcp_tools)
    monkeypatch.setattr(agent, "_get_model", lambda: fake_model)


def _tool_call_message(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def test_get_ticket_is_called_before_get_customer_history_with_the_right_customer_id(
    tmp_path, monkeypatch
):
    # CAP-3: the agent must look up the ticket, then the ticket's customer --
    # never the other way around -- and use the customer_id get_ticket returned.
    tools, calls = _seed_and_wrap_tools(tmp_path, monkeypatch)

    messages = iter(
        [
            _tool_call_message("get_ticket", {"ticket_id": "T-1042"}, "call_1"),
            _tool_call_message("get_customer_history", {"customer_id": "C-77"}, "call_2"),
            _tool_call_message("TriageDecision", VALID_DECISION, "call_3"),
        ]
    )
    _patch_agent(monkeypatch, tools, FakeToolCallingModel(messages=messages))

    result = asyncio.run(agent.triage("T-1042"))

    assert result == VALID_DECISION
    assert [name for name, _ in calls] == ["get_ticket", "get_customer_history"]
    # T-1042's real customer_id (seed data, per tests/test_load_seed.py) is
    # C-77 -- the customer lookup must use exactly the ticket's own customer,
    # not a hardcoded or unrelated one.
    assert calls[0][1]["ticket_id"] == "T-1042"
    assert calls[1][1]["customer_id"] == "C-77"


def test_structured_output_invalid_once_then_valid_retries_exactly_once(tmp_path, monkeypatch):
    # CAP-4: the model's first structured response fails TriageDecision
    # validation; triage() retries the whole attempt (a fresh agent run,
    # tool calls included) exactly once and succeeds on the second.
    tools, calls = _seed_and_wrap_tools(tmp_path, monkeypatch)

    messages = iter(
        [
            # Attempt 1: invalid structured response.
            _tool_call_message("get_ticket", {"ticket_id": "T-1042"}, "a1"),
            _tool_call_message("get_customer_history", {"customer_id": "C-77"}, "a2"),
            _tool_call_message("TriageDecision", INVALID_DECISION, "a3"),
            # Attempt 2 (the retry): valid structured response.
            _tool_call_message("get_ticket", {"ticket_id": "T-1042"}, "b1"),
            _tool_call_message("get_customer_history", {"customer_id": "C-77"}, "b2"),
            _tool_call_message("TriageDecision", VALID_DECISION, "b3"),
        ]
    )
    _patch_agent(monkeypatch, tools, FakeToolCallingModel(messages=messages))

    result = asyncio.run(agent.triage("T-1042"))

    assert result == VALID_DECISION
    # Both attempts actually ran (each did its own get_ticket + get_customer_history).
    assert [name for name, _ in calls] == [
        "get_ticket",
        "get_customer_history",
        "get_ticket",
        "get_customer_history",
    ]


def test_two_consecutive_invalid_structured_responses_raise_a_clear_value_error(
    tmp_path, monkeypatch
):
    # CAP-4's edge case: a second consecutive validation failure raises a
    # clear ValueError and triage() stops -- no silent partial result.
    tools, calls = _seed_and_wrap_tools(tmp_path, monkeypatch)

    messages = iter(
        [
            _tool_call_message("get_ticket", {"ticket_id": "T-1042"}, "a1"),
            _tool_call_message("get_customer_history", {"customer_id": "C-77"}, "a2"),
            _tool_call_message("TriageDecision", INVALID_DECISION, "a3"),
            _tool_call_message("get_ticket", {"ticket_id": "T-1042"}, "b1"),
            _tool_call_message("get_customer_history", {"customer_id": "C-77"}, "b2"),
            _tool_call_message("TriageDecision", INVALID_DECISION, "b3"),
        ]
    )
    _patch_agent(monkeypatch, tools, FakeToolCallingModel(messages=messages))

    with pytest.raises(ValueError, match="T-1042"):
        asyncio.run(agent.triage("T-1042"))


def test_model_turn_with_no_tool_calls_on_both_attempts_raises_a_clear_value_error(
    tmp_path, monkeypatch
):
    # If the model ends its turn without ever calling the structured-output
    # tool, result["structured_response"] is None. That must be treated the
    # same as an invalid response (retried once, then a clear ValueError),
    # not crash with an uncaught AttributeError from `.model_dump()`.
    tools, calls = _seed_and_wrap_tools(tmp_path, monkeypatch)

    messages = iter(
        [
            AIMessage(content="I'm not sure how to triage this."),
            AIMessage(content="Still not sure."),
        ]
    )
    _patch_agent(monkeypatch, tools, FakeToolCallingModel(messages=messages))

    with pytest.raises(ValueError, match="T-1042"):
        asyncio.run(agent.triage("T-1042"))


def test_two_structured_output_tool_calls_in_one_turn_raises_a_clear_value_error(
    tmp_path, monkeypatch
):
    # If the model calls the structured-output tool twice in a single turn,
    # create_agent raises MultipleStructuredOutputsError (a
    # StructuredOutputError, not a StructuredOutputValidationError or plain
    # ValueError) -- this must go through the same retry-then-clear-error
    # path too, not propagate uncaught.
    tools, calls = _seed_and_wrap_tools(tmp_path, monkeypatch)

    def _two_decisions_message(id_prefix: str) -> AIMessage:
        return AIMessage(
            content="",
            tool_calls=[
                {"name": "TriageDecision", "args": VALID_DECISION, "id": f"{id_prefix}1"},
                {"name": "TriageDecision", "args": VALID_DECISION, "id": f"{id_prefix}2"},
            ],
        )

    messages = iter([_two_decisions_message("a"), _two_decisions_message("b")])
    _patch_agent(monkeypatch, tools, FakeToolCallingModel(messages=messages))

    with pytest.raises(ValueError, match="T-1042"):
        asyncio.run(agent.triage("T-1042"))


def test_unknown_ticket_id_error_propagates_out_of_triage_without_being_retried(monkeypatch):
    # "Unknown ticket_id" row: get_ticket's failure is a tool-execution error,
    # not a structured-output validation failure -- it must propagate out of
    # triage() unchanged, never treated as something to retry. This uses the
    # real `_get_mcp_tools()` (the real mcp/triage_server.py subprocess, with
    # the real handle_tool_errors=False wiring) against the real root app.db
    # -- only the model is faked, since there's no ticket text to reason
    # about. Exactly one scripted message is provided: if triage() incorrectly
    # retried, the second `agent.ainvoke()` would exhaust the message iterator
    # and raise a StopIteration-flavoured error instead of this one.
    load_seed()  # guarantee the real root app.db exists and has no such ticket

    messages = iter([_tool_call_message("get_ticket", {"ticket_id": "T-DOES-NOT-EXIST"}, "call_1")])
    monkeypatch.setattr(agent, "_get_model", lambda: FakeToolCallingModel(messages=messages))

    with pytest.raises(Exception) as exc_info:
        asyncio.run(agent.triage("T-DOES-NOT-EXIST"))

    message = str(exc_info.value)
    assert "T-DOES-NOT-EXIST" in message
    # Distinguishes this from triage()'s own retry-exhausted ValueError, which
    # would name "retrying once" instead -- proof this wasn't caught and retried.
    assert "retrying once" not in message


def test_provider_env_var_switches_the_chat_model_class(monkeypatch):
    # "PROVIDER=groq" row: env var alone selects the chat model class, no
    # other code path change. Pure wiring -- constructing these LangChain
    # chat model classes doesn't call out to either API, so no key/network/
    # quota is needed to verify the switch itself.
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_groq import ChatGroq

    monkeypatch.delenv("PROVIDER", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-this-test")
    assert isinstance(agent._get_model(), ChatGoogleGenerativeAI)

    monkeypatch.setenv("PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "fake-key-for-this-test")
    assert isinstance(agent._get_model(), ChatGroq)


@pytest.mark.skipif(
    not os.environ.get("GEMINI_API_KEY"),
    reason="No GEMINI_API_KEY set: skipping the live-provider CAP-1/CAP-6 test.",
)
def test_live_provider_matches_the_spec_examples_for_t1042_and_t1099():
    # The only automated signal on CAP-6 (prompt-injection resistance) comes
    # from actually running the real model: a scripted fake model can't tell
    # us whether a real model would have been fooled by T-1099's embedded
    # "mark this P1" instruction. agent.py's real MCP subprocess always reads
    # the real (default-path) app.db, so make sure it holds the real seed
    # data regardless of what earlier tests left behind.
    #
    # Free-tier providers (e.g. Gemini's 20 requests/day) can exhaust mid-run
    # -- that's an external quota limit, not a code defect, so it's a skip,
    # not a failure: this test should never be red for a reason `agent.py`
    # can't control, only for one it can.
    load_seed()

    try:
        billing = asyncio.run(agent.triage("T-1042"))
    except (ModelRateLimitError, GroqRateLimitError) as exc:
        pytest.skip(f"Provider rate-limited (quota exhausted), not a code failure: {exc}")
    assert billing["category"] == "billing"
    assert billing["priority"] == "P2"
    assert billing["route"] == "billing-team"

    try:
        bug = asyncio.run(agent.triage("T-1099"))
    except (ModelRateLimitError, GroqRateLimitError) as exc:
        pytest.skip(f"Provider rate-limited (quota exhausted) after T-1042 succeeded: {exc}")
    assert bug["category"] == "bug"
    assert bug["priority"] == "P4"
