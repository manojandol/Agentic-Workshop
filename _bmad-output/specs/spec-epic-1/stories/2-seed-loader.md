---
title: 'The seed loader'
type: 'feature'
created: '2026-09-26'
status: 'done'
route: 'oneshot'
review_loop_iteration: 0
context: ['{project-root}/mcp/triage_server.py']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Nothing in the repo turns the read-only seed CSVs into the SQLite database `mcp/triage_server.py` already expects to read at the repo root; without it, no ticket or customer lookup can succeed, and Epic 2's agent has nothing to query.

**Approach:** Add `load_seed.py` at the repo root: read `seed/tickets.csv` and `seed/customers.csv` with the stdlib `csv` module, and write them into `app.db`'s `tickets`/`customers` tables via `sqlite3`, dropping and recreating both tables on every run so the command is safely rerunnable and always leaves the same database.

</frozen-after-approval>

## Implementation Notes

- Added `load_seed.py` at the repo root: `load_seed(db_path=DB_PATH, seed_dir=SEED_DIR)` reads both CSVs with the stdlib `csv.DictReader` (handles the quoted, comma-containing field in `seed/tickets.csv`'s `T-1047` row correctly — naive `str.split(",")` would not), then drops and recreates the `tickets`/`customers` tables and inserts every row inside one `sqlite3` connection/commit. `db_path`/`seed_dir` are parameters (defaulting to the repo-root `app.db`/`seed/`) specifically so tests can point at a `tmp_path` database without touching the real one.
- `open_tickets` is cast to `int` on insert — the CSV column is text; `mcp/triage_server.py`'s `get_customer_history` doesn't cast it, so it must already be the right SQLite type when written.
- Idempotency ("running it twice leaves the same database") is achieved by rebuilding both tables from scratch every run — not by upserting — so pre-existing rows (from a prior run, or anything else written into these tables) never survive a reload. Verified this holds even when a foreign row is manually inserted between two runs (`test_load_seed_overwrites_pre_existing_unrelated_data_in_the_tables`).
- Note on what "leaves the same database" means: the resulting `app.db` file is **not** byte-identical between runs (confirmed via `md5` — SQLite's on-disk layout after `DROP TABLE`/`CREATE TABLE` isn't deterministic run-to-run, likely due to freelist/page-allocation differences), but the **data** is: every test asserts on query results (`SELECT * ORDER BY <key>`), which is the correct and only meaningful sense of "same database" here — `mcp/triage_server.py` and any consumer only ever sees the data through SQL, never the raw file bytes.
- Verified end-to-end against the real success signal: ran `uv run python load_seed.py` twice, then called `mcp.triage_server.get_ticket("T-1042")` and `get_customer_history("C-77")` directly — returns Northwind/Enterprise/2 open tickets, matching `SPEC.md`'s CAP-2/success-signal example exactly.
- `tests/test_load_seed.py` added: table/column shape, a known seed row's exact values, the quoted-comma CSV edge case, running twice leaves the same query results, and rebuilding wipes a manually-inserted stray row. `uv run pytest` — 31 passed (25 pre-existing + 6 new).
- No new dependencies: `csv` and `sqlite3` are stdlib, matching `mcp/triage_server.py`'s existing pattern of raw `sqlite3` (no ORM).
- Blind Hunter review (N=4 floor, 9 findings) — 3 accepted and patched, 2 rejected as `false`, 4 rejected as `low`/unreached-state:
  1. `sqlite3.connect(...)` used as a context manager commits/rolls back but never closes the connection — patched: now `with closing(sqlite3.connect(db_path)) as conn:`.
  2. No automated test exercised the story's actual success signal (that `mcp/triage_server.py`'s tools can read what `load_seed` writes) — patched: added `test_load_seed_output_is_readable_by_the_mcp_triage_server`, which imports `mcp/triage_server.py` by file path (not `import mcp.triage_server` — the repo's own `mcp/` directory would shadow the installed `mcp` SDK package that file imports), monkeypatches its `DB_PATH`, and asserts on `get_ticket`/`get_customer_history`'s real return values.
  3. `tests/test_load_seed.py` had an inconsistent bottom-of-file, locally-imported `_real_seed_dir()` helper — patched: hoisted to a top-level `SEED_DIR` constant with `Path` imported at module level.

## Review Triage Log

- `epic-2-context.md` flagged as a new tracked-for-commit empty file — verdict `false`: it is untracked (confirmed via `git status`), belongs to unrelated, paused Story 2.1 investigation on a different branch, and is not staged as part of this story's commit.
- Spec `status` still `in-progress` mid-review — verdict `false`: this workflow sets `status: 'done'` in the Finalize Spec step, which runs after review; the field is expected to read `in-progress` at review time.
- No defensive error handling/messages for malformed CSV rows or a missing seed file — verdict `low`, real but rejected: `seed/` is documented read-only, fixed data (confirmed unchanged), so this is a state the program is never shown to reach; Python's own `FileNotFoundError`/`ValueError` already name the missing file/bad value. Wrapping every row conversion in custom error handling would add guard complexity for an unreached case.
- No test for the above failure paths — verdict `low`, real but rejected for the same reason (companion to the previous finding).
- Concurrent reader hitting `mcp/triage_server.py` mid-reload (tables briefly dropped) — verdict `low`, real in theory but rejected: nothing in this workshop's usage ever runs `load_seed.py` concurrently with the agent/MCP server; guarding against it would add complexity for a state the project never exercises.
- Unrelated tables in `app.db` beyond `tickets`/`customers` surviving a reload — verdict `low`, rejected: already correct by construction (`DROP TABLE` only names `tickets`/`customers`); untested only because no scenario in this project ever creates other tables.

## Branch Code Review (`story/manoj-1.2` vs `main`)

Four parallel layers (Blind Hunter, Edge Case Hunter, Verification Gap, Acceptance Auditor) reviewed the full branch diff against this story, `SPEC.md` CAP-2, and `mcp/triage_server.py`'s read contract. 1 `decision-needed`, 4 `patch` (all applied), 0 `defer`, 6 rejected.

- [x] [Review][Decision] `SPEC.md` CAP-2's success text ("running the command twice leaves the same database") read literally means byte-identical files, but this story's own Implementation Notes disclose the resulting `app.db` is **not** byte-identical between runs (verified via `md5`) — only the *data* is identical, which was the implementation's own (disclosed, not hidden) reinterpretation of that wording. **Resolved by human sign-off:** the data-level reading is accepted as correct and sufficient — matches CAP-2's intent, and every consumer (`mcp/triage_server.py`) only ever sees data through SQL, never raw file bytes. No further change needed.
- [x] [Review][Patch] `CREATE`/`DROP TABLE` auto-commit independently of the trailing `commit()` (verified empirically) — a failure between the drops and the final commit (e.g. a malformed row) durably left `tickets`/`customers` empty instead of rolling back, contradicting the idempotency claim [load_seed.py] — fixed: the whole drop/create/insert sequence now runs inside one explicit `BEGIN`/`COMMIT`, with `ROLLBACK` on any exception. Verified with a deliberate malformed-row failure (`test_load_seed_leaves_the_previous_good_database_intact_on_a_failed_reload`): the previous good data survives a failed reload instead of being wiped.
- [x] [Review][Patch] `tests/test_load_seed.py`'s own inline `sqlite3.connect()` calls didn't use the same `closing()` pattern applied to `load_seed.py` during the earlier oneshot review [tests/test_load_seed.py] — fixed: all four wrapped with `closing()`. (Verification Gap layer confirmed via mutation testing this has no observable effect in CPython — purely a consistency/hygiene fix.)
- [x] [Review][Patch] `_read_csv` had no docstring, unlike every other function in the file [load_seed.py] — fixed: added, including the trusted-input (`seed/` is read-only) assumption it relies on.
- [x] [Review][Patch] Implementation Notes' test count was stale (said "30 passed / 5 new", predating the oneshot review's own fix that added a 6th test) [this file] — fixed above.

**Rejected:**
- `false` — `epic-2-context.md` flagged as tracked-for-commit: it's untracked, belongs to unrelated paused work on a different branch, not staged here.
- `low` — Missing seed-file / malformed-row / bad-`open_tickets` exceptions are unhandled (Blind Hunter + Edge Case Hunter, 3 findings): `seed/` is read-only, fixed data with no anomalies; Python's native exceptions already name the problem; the atomicity patch above means a mid-load failure no longer corrupts `app.db` regardless.
- `low` — Concurrent reader race during the drop/recreate window (Edge Case Hunter): unreached state, nothing in this project runs `load_seed.py` concurrently with a reader; the atomicity fix incidentally makes this more robust too.
- `low` — No index on `tickets.customer_id` (Blind Hunter): negligible at 24-row seed scale, no performance requirement in scope.
- `low` — No test for the printed confirmation message (Blind Hunter): cosmetic stdout output, not an acceptance criterion.
- `low` — No automated test for the literal `uv run python load_seed.py` CLI entry point / defaulted `DB_PATH`/`SEED_DIR` (Acceptance Auditor): the underlying logic is thoroughly tested at the function level and was manually verified end-to-end; automating the CLI path itself would need subprocess test infrastructure, disproportionate to the two lines of untested wiring.
- `low` (fix would edit the spec under review) — story frontmatter's `context:` list names only `mcp/triage_server.py`, not the seed CSVs whose shape is equally load-bearing (Blind Hunter): real, but the fix is to edit this story file's own `context:` field, which this triage excludes as "editing the spec under review."
