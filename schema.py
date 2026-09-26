"""The triage-decision schema.

Epic 1 CAP-1: every triage decision is a JSON object the rest of the workshop
can accept or reject. A decision matching `decision-schema.md` is accepted;
anything else is rejected with a clear error.

The allowed value tuples and the `TriageDecision` model must stay in sync with
`_bmad-output/specs/spec-epic-1/decision-schema.md`, the canonical contract.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

CATEGORIES: tuple[str, ...] = ("billing", "bug", "access", "performance", "how-to")
PRIORITIES: tuple[str, ...] = ("P1", "P2", "P3", "P4")
ROUTES: tuple[str, ...] = (
    "billing-team",
    "bug-team",
    "access-team",
    "performance-team",
    "how-to-team",
)


class TriageDecision(BaseModel):
    """A validated triage decision: category, priority, route and a one-sentence rationale.

    This only checks the shape CAP-1 owns: exactly these four fields, each
    within its allowed values. It does not check that `category` and `route`
    are the pair `TRIAGE_POLICY.md` maps them to (e.g. `billing` with
    `billing-team`) — applying that policy is a later epic's job, not this
    schema's.
    """

    model_config = ConfigDict(extra="forbid")

    category: Literal["billing", "bug", "access", "performance", "how-to"]
    priority: Literal["P1", "P2", "P3", "P4"]
    route: Literal[
        "billing-team", "bug-team", "access-team", "performance-team", "how-to-team"
    ]
    rationale: str


def validate_decision(data: object) -> TriageDecision:
    """Validate a candidate triage decision.

    `data` is typed `object`, not `dict`, because this function's job is
    exactly to reject non-dict payloads (see `test_non_object_payload_is_rejected`)
    alongside every other way a decision can be malformed.

    Returns a `TriageDecision` when `data` matches the schema exactly.
    Raises `ValueError` with a clear, specific message otherwise (missing
    field, extra field, a value outside the allowed lists, or a wrong type).
    """
    try:
        return TriageDecision.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"Invalid triage decision: {exc}") from exc
