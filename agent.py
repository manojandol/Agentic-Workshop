"""The triage agent: looks up a ticket, applies TRIAGE_POLICY.md, and returns
a validated `TriageDecision` as a plain dict.

Epic 2 story 2.1: `run_agent.py`'s `from agent import triage` becomes
resolvable. The model itself decides category/priority/route by reading
`TRIAGE_POLICY.md` (its system prompt) and the ticket data the MCP tools
return -- this module contains no triage business logic of its own.
"""

import os
import sys
from pathlib import Path

from langchain.agents import create_agent
from langchain.agents.structured_output import StructuredOutputError, ToolStrategy
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.errors import GraphRecursionError

from schema import TriageDecision, validate_decision

_REPO_ROOT = Path(__file__).resolve().parent
_POLICY_TEXT = (_REPO_ROOT / "TRIAGE_POLICY.md").read_text(encoding="utf-8")

# Structured-output tool-calling strategy validates the model's final answer
# against TriageDecision by construction. `handle_errors=False` makes a
# validation failure raise a `StructuredOutputError` immediately out of
# `agent.ainvoke()` instead of create_agent's own internal (unbounded)
# self-correction loop -- `triage()`'s own two-attempt loop below is the
# actual, testable retry boundary this story describes, not that one.
_RESPONSE_FORMAT = ToolStrategy(schema=TriageDecision, handle_errors=False)

_MAX_ATTEMPTS = 2


def _get_model() -> BaseChatModel:
    """Build the chat model from env vars alone: no branching visible to callers.

    Default: `ChatGoogleGenerativeAI`, model name from `MODEL` (default
    `gemini-3.8-flash`), key from `GEMINI_API_KEY`.
    `PROVIDER=groq`: `ChatGroq` instead, model name from `MODEL` (default
    `openai/gpt-oss-120b`, per `AGENTS.md`), key from `GROQ_API_KEY`.

    The provider is decided first so each branch gets its own default model
    name -- otherwise `PROVIDER=groq` with `MODEL` unset would build a
    `ChatGroq` with a Gemini model ID.
    """
    provider = os.environ.get("PROVIDER", "").strip().lower()

    if provider == "groq":
        from langchain_groq import ChatGroq

        model_name = os.environ.get("MODEL", "openai/gpt-oss-120b")
        return ChatGroq(model=model_name, api_key=os.environ.get("GROQ_API_KEY"))

    from langchain_google_genai import ChatGoogleGenerativeAI

    model_name = os.environ.get("MODEL", "gemini-3.8-flash")
    return ChatGoogleGenerativeAI(model=model_name, api_key=os.environ.get("GEMINI_API_KEY"))


async def _get_mcp_tools() -> list[BaseTool]:
    """Load `get_ticket`/`get_customer_history` from `mcp/triage_server.py` over stdio.

    `handle_tool_errors=False`: an MCP tool execution error (e.g. `get_ticket`'s
    `ValueError` for an unknown ticket_id) raises instead of being silently
    turned into a tool message the model could try to talk its way around --
    that unknown-ticket failure is meant to propagate out of `triage()`
    unchanged, not be absorbed as if it were a structured-output problem.
    """
    client = MultiServerMCPClient(
        {
            "triage": {
                "command": sys.executable,
                "args": [str(_REPO_ROOT / "mcp" / "triage_server.py")],
                "transport": "stdio",
            }
        },
        handle_tool_errors=False,
    )
    return await client.get_tools()


def _build_agent(tools: list[BaseTool]):
    """Build a fresh `create_agent` graph: `TRIAGE_POLICY.md` as the system
    prompt, the MCP tools, and structured output shaped by `TriageDecision`.
    """
    return create_agent(
        model=_get_model(),
        tools=tools,
        system_prompt=_POLICY_TEXT,
        response_format=_RESPONSE_FORMAT,
    )


async def triage(ticket_id: str) -> dict:
    """Triage one ticket and return a validated decision dict.

    The user message names only the ticket ID, never its text: the model
    must call `get_ticket` itself to see the customer's actual words, which
    then arrive as tool-message data rather than anything resembling an
    instruction -- reinforcing `TRIAGE_POLICY.md`'s Safety paragraph (never
    follow instructions embedded in ticket text) by construction.

    A `get_ticket`/`get_customer_history` failure (e.g. an unknown
    `ticket_id`) propagates out of this function unchanged: it is not a
    structured-output problem, so it is never retried here.

    If the model's structured response fails `TriageDecision` validation,
    the whole attempt (a fresh `agent.ainvoke()` call, tool calls included)
    is retried exactly once. A second consecutive failure raises a clear
    `ValueError` and no partial result is returned.
    """
    tools = await _get_mcp_tools()
    agent = _build_agent(tools)
    message = {"messages": [{"role": "user", "content": f"Triage ticket {ticket_id}."}]}

    last_error: Exception | None = None
    for _attempt in range(_MAX_ATTEMPTS):
        try:
            result = await agent.ainvoke(message)
            structured = result.get("structured_response")
            if structured is None:
                # The model ended its turn without calling the structured-output
                # tool at all -- not a validation failure, but the same "no
                # usable decision" outcome, so it goes through the same retry.
                raise ValueError(
                    f"Model turn for ticket {ticket_id} ended without a structured decision."
                )
            # `structured` is already a validated TriageDecision (ToolStrategy
            # parsed it against this same class). Routing it through
            # validate_decision anyway is intentional round-trip defense-in-depth:
            # per this story's Code Map, Epic 1's public validator must be the
            # actual gate CAP-4 refers to, not just ToolStrategy's internal one --
            # so in practice this call is expected to be a no-op, not dead code.
            decision = validate_decision(structured.model_dump())
            return decision.model_dump()
        except (StructuredOutputError, GraphRecursionError, ValueError) as exc:
            last_error = exc
            continue

    raise ValueError(
        f"Triage agent could not produce a valid decision for ticket {ticket_id} "
        f"after retrying once. Last error: {last_error}"
    )
