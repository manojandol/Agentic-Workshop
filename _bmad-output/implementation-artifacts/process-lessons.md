# Process lessons

Short, dated notes on deviations from `AGENTS.md`'s workflow rules, found by
auditing git history. Not a full retrospective — just enough to avoid
repeating the mistake.

## 2026-09-26: Story 1.1 merged before its review passed

**Rule violated:** `AGENTS.md` — "One branch per story. Merge a story only
after its review passes."

**What happened:** on `story/manoj-1.1`, the code-review findings were
recorded in a commit (`f4e6d9c`, "docs: record branch code review findings
on story 1.1"), but the branch was merged into `main` (`d94aada`) **before**
those findings were fixed. A second branch, `story/manoj-1.1-patches`, had
to be created off `main` afterward just to apply the fixes (`b697e94`),
which then required a second merge (`0115f21`) to actually close the loop.

```
*   0115f21 Merge story/manoj-1.1-patches: resolve Story 1.1 review action items
|\
| * b697e94 fix: resolve Story 1.1 code review patch findings
|/
*   d94aada Merge story/manoj-1.1: triage-decision schema (Story 1, CAP-1)
|\
| * f4e6d9c docs: record branch code review findings on story 1.1
| * 8de24e9 feat: add the triage-decision schema (CAP-1)
```

**Impact:** none on `main`'s current content — the patches did land before
Story 1.2 branched off, so nothing downstream inherited the bug. This is a
process/history deviation only, not a code defect. Left as-is rather than
rewriting already-pushed history, per an explicit decision on 2026-09-26 not
to force-push over shared `main` history for a resolved, non-destructive
issue.

**Contrast — done correctly since:**
- Story 1.2: review findings were patched on `story/manoj-1.2` itself, then
  merged exactly once (`74f8bf1` → `9df08eb` → `7348802`).
- Story 2.1: review findings are being patched on `story/manoj-2.1` itself,
  before any merge is attempted.

**Action item:** before running `git merge` / `git push origin main` for any
story branch, confirm the branch's own `## Review Triage Log` shows every
finding already routed to a verdict with no unapplied `patch` items left
open — i.e. the fix commits exist *on the story branch*, not as a follow-up
branch after the fact.
