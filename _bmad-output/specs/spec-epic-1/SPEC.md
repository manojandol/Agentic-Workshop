---
id: SPEC-epic-1
companions: [decision-schema.md, ../../../mcp/triage_server.py]
sources: [../../../INTENT.md]
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# Epic 1: triage data and schema

## Why

The workshop agent cannot decide or look anything up until two foundations exist: a triage-decision shape later epics can validate against, and a local `app.db` that `mcp/triage_server.py` already knows how to read. This epic is the mandate that puts those in place before any model is called.

## Capabilities

- **CAP-1**
  - **intent:** Every triage decision is a JSON object the rest of the workshop can accept or reject.
  - **success:** A decision that matches `decision-schema.md` is accepted. Anything else is rejected with a clear error.

- **CAP-2**
  - **intent:** A person can load the seed tickets and customers into a local SQLite database with one command.
  - **success:** `uv run python load_seed.py` creates `app.db` with tables `tickets` (`ticket_id`, `customer_id`, `created_at`, `text`) and `customers` (`customer_id`, `name`, `plan`, `open_tickets`), copied from `seed/tickets.csv` and `seed/customers.csv`. Running the command twice leaves the same database.

## Constraints

- Python 3.12 or newer, managed with uv.
- Files under `seed/` are read-only.
- No network calls and no API keys in this epic.
- `mcp/triage_server.py` already reads `app.db` at the repo root. Tables and columns must stay `tickets(ticket_id, customer_id, created_at, text)` and `customers(customer_id, name, plan, open_tickets)`.

## Non-goals

- The agent, the MCP tools, evals, and any user interface.

## Success signal

`uv run python load_seed.py` run twice produces the same `app.db`, and `mcp/triage_server.py` can look up a seed ticket such as T-1042. A decision that violates `decision-schema.md` is rejected with a clear error; a valid one is accepted.

## Assumptions

- JSON field names are `category`, `priority`, `route`, and `rationale` — the nouns `INTENT.md` uses for the decision object.
- `app.db` lives at the repo root, which is where `mcp/triage_server.py` already looks.
