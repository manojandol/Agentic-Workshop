---
title: 'The triage-decision schema'
type: 'feature'
created: '2026-09-26'
status: 'done'
route: 'oneshot'
review_loop_iteration: 0
context: ['{project-root}/_bmad-output/specs/spec-epic-1/decision-schema.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Nothing in the repo can accept or reject a triage decision's shape yet. The agent (Epic 2) and the eval (Epic 3) both need one source of truth that checks a decision has exactly `category`, `priority`, `route` and `rationale`, each within its allowed values, and rejects anything else with a clear error.

**Approach:** Add `schema.py` at the repo root: the allowed value tuples plus a strict Pydantic `TriageDecision` model (no extra fields) matching `decision-schema.md`, and a `validate_decision(data)` helper that raises `ValueError` with a clear message on any mismatch. Cover it with unit tests for the valid case, every allowed value, and each way a decision can be invalid (missing field, extra field, bad enum value, wrong type).

</frozen-after-approval>

## Implementation Notes

- Added `schema.py` at the repo root: `CATEGORIES`/`PRIORITIES`/`ROUTES` tuples, a strict (`extra="forbid"`) Pydantic `TriageDecision` model with `Literal` fields for `category`/`priority`/`route` and a plain `str` for `rationale`, and `validate_decision(data)` which wraps `TriageDecision.model_validate` and re-raises `pydantic.ValidationError` as `ValueError("Invalid triage decision: ...")`.
- Added an empty root-level `conftest.py` so `tests/test_schema.py` can `import schema` — without it, pytest's default import mode only puts `tests/` on `sys.path`, not the repo root, since there is no `src/`-layout or installed package here.
- Added `tests/test_schema.py`: the valid-decision case, every allowed `category`/`priority`/`route` value individually, and each rejection case (missing field, extra field, invalid enum value, wrong type). `uv run pytest` — 21 passed.
- Kept validation purely structural (field names + per-field allowed values), per `decision-schema.md`. Did not enforce the `TRIAGE_POLICY.md` category→route pairing (e.g. `billing`→`billing-team`) — that's policy application, which is out of scope for CAP-1's generic schema check and belongs to whichever epic applies the policy.
- Blind Hunter review (N=3 floor, 6 findings) — all six accepted as real, all patched: (1) added a test that the `Literal` field annotations stay in sync with the `CATEGORIES`/`PRIORITIES`/`ROUTES` tuples; (2) rejection tests now assert the error message names the offending field, not just `ValueError`'s type; (3) added `test_empty_rationale_is_accepted` documenting that `decision-schema.md`'s "no enum" on `rationale` is intentionally permissive; (4) added `test_non_object_payload_is_rejected` for non-dict top-level input; (5) added a test for a payload with two simultaneous violations; (6) documented the category↔route non-validation scope boundary directly in `TriageDecision`'s docstring, not only in `epic-1-context.md`. Re-ran `uv run pytest` after each patch — 25 passed.

## Review Triage Log

- Literal/tuple drift risk — verdict `low`, real: no test enforced the two hand-written lists stayed equal. Not rejected (fix was a simple test addition): patched with `test_literal_fields_stay_in_sync_with_allowed_value_tuples`.
- Rejection tests didn't check error-message content — verdict `medium`, real: the spec's success signal is "rejected with a clear error," which the type-only assertions didn't verify. Patched: each rejection test now uses `pytest.raises(..., match=<field name>)`.
- Untested empty/whitespace `rationale` — verdict `low`, real gap in coverage, not a bug: `decision-schema.md` deliberately gives `rationale` no enum, so accepting `""` is correct behavior. Patched by adding a test that documents this as intentional rather than leaving it silently untested.
- Untested non-object top-level payload — verdict `low`, real gap in coverage: manually confirmed `validate_decision` already raises `ValueError` for a string/list/int/`None`, but no test locked in that behavior. Patched with `test_non_object_payload_is_rejected`.
- Untested multiple-simultaneous-violations case — verdict `low`, real gap in coverage; fix was a simple test addition so not rejected despite low severity. Patched with `test_multiple_simultaneous_violations_still_raises_one_clear_error`.
- Category↔route scope boundary undocumented in code — verdict `low`, real: the deliberate choice not to validate the `TRIAGE_POLICY.md` category→route pairing was recorded only in `epic-1-context.md`, one level removed from `schema.py`. Patched by adding it to `TriageDecision`'s docstring.
