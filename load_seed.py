"""Load the seed tickets and customers into app.db.

Usage: uv run python load_seed.py
"""

import csv
import sqlite3
from contextlib import closing
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
DB_PATH = REPO_ROOT / "app.db"
SEED_DIR = REPO_ROOT / "seed"

_CREATE_TICKETS = """
CREATE TABLE tickets (
    ticket_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    text TEXT NOT NULL
)
"""

_CREATE_CUSTOMERS = """
CREATE TABLE customers (
    customer_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    plan TEXT NOT NULL,
    open_tickets INTEGER NOT NULL
)
"""


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_seed(db_path: Path = DB_PATH, seed_dir: Path = SEED_DIR) -> None:
    """Load `seed_dir`'s tickets.csv and customers.csv into `db_path`.

    Drops and recreates both tables on every call, so running this twice
    (or against a database that already has other data in these tables)
    always leaves the same `tickets`/`customers` content -- the load is
    idempotent by construction, not by upserting.
    """
    tickets = _read_csv(seed_dir / "tickets.csv")
    customers = _read_csv(seed_dir / "customers.csv")

    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute("DROP TABLE IF EXISTS tickets")
        conn.execute("DROP TABLE IF EXISTS customers")
        conn.execute(_CREATE_TICKETS)
        conn.execute(_CREATE_CUSTOMERS)
        conn.executemany(
            "INSERT INTO tickets (ticket_id, customer_id, created_at, text) VALUES (?, ?, ?, ?)",
            [(r["ticket_id"], r["customer_id"], r["created_at"], r["text"]) for r in tickets],
        )
        conn.executemany(
            "INSERT INTO customers (customer_id, name, plan, open_tickets) VALUES (?, ?, ?, ?)",
            [(r["customer_id"], r["name"], r["plan"], int(r["open_tickets"])) for r in customers],
        )
        conn.commit()

    print(f"Loaded {len(tickets)} tickets and {len(customers)} customers into {db_path.name}")


if __name__ == "__main__":
    load_seed()
