# Epic 1 Context: triage data and schema

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

This epic lays the two foundations the rest of the workshop depends on: a strict, machine-checkable shape for a triage decision, and a local `app.db` populated from the seed data so the MCP tools have something to read. Nothing else in the workshop — the agent, its tools, or the evals — can run until a decision can be validated and the database exists. Note: this project uses a spec-first workflow instead of classic BMad planning artifacts (PRD, architecture, UX doc); there is no separate planning-artifacts directory to draw from, so everything below is compiled directly from the epic's own spec files.

## Stories

- Story 1.1: The triage-decision schema
- Story 1.2: The seed loader

## Requirements & Constraints

- A triage decision is a JSON object with exactly four fields: `category`, `priority`, `route`, `rationale`. Extra fields, missing fields, or a value outside the allowed lists makes the whole decision invalid.
- Allowed values:
  - `category`: `billing`, `bug`, `access`, `performance`, `how-to`
  - `priority`: `P1`, `P2`, `P3`, `P4`
  - `route`: `billing-team`, `bug-team`, `access-team`, `performance-team`, `how-to-team`
  - `rationale`: free text, one sentence; no enum
- Validation must accept a matching decision and reject anything else with a clear, specific error (not a generic failure).
- The seed loader must be runnable as `uv run python load_seed.py`, must be idempotent (running it twice leaves the same `app.db`), and must source data only from `seed/tickets.csv` and `seed/customers.csv`.
- After loading, `mcp/triage_server.py` must be able to look up a seed ticket (e.g. `T-1042`) without any changes to that file.
- Scope boundary: the agent itself, the MCP tool implementations, evals, and any UI are explicitly out of scope for this epic — this epic only produces the data and the validation contract they'll later rely on.

## Technical Decisions

- Python 3.12+, managed with `uv`; no `pip`.
- Files under `seed/` are read-only — the loader must read from them, never write to or modify them.
- No network calls and no API keys are involved anywhere in this epic.
- `app.db` is a SQLite database and must live at the repo root, matching where `mcp/triage_server.py` already looks for it.
- Table/column shape is fixed by the existing reader (`mcp/triage_server.py`) and must not change:
  - `tickets(ticket_id, customer_id, created_at, text)`
  - `customers(customer_id, name, plan, open_tickets)`
- Decision JSON field names (`category`, `priority`, `route`, `rationale`) are fixed nouns carried over from the project's intent doc — don't rename them.
