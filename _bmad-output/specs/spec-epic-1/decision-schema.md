# Triage decision schema

A triage decision is a JSON object with these fields. Anything else is rejected with a clear error.

| Field | Allowed values |
|---|---|
| `category` | `billing`, `bug`, `access`, `performance`, `how-to` |
| `priority` | `P1`, `P2`, `P3`, `P4` |
| `route` | `billing-team`, `bug-team`, `access-team`, `performance-team`, `how-to-team` |
| `rationale` | one sentence |

`rationale` has no enum. Extra fields, missing fields, or a value outside the lists above are invalid.
