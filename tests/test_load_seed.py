import importlib.util
import sqlite3
from pathlib import Path

from load_seed import load_seed

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"


def _rows(db_path, table, order_by):
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY {order_by}")]


def _import_triage_server():
    """Import mcp/triage_server.py by file path.

    Not `import mcp.triage_server`: the repo has a top-level `mcp/`
    directory (this MCP server's own code) that shares its name with the
    installed `mcp` SDK package that file itself imports
    (`from mcp.server.fastmcp import FastMCP`). Importing by file path
    sidesteps that name collision instead of relying on sys.path order.
    """
    path = Path(__file__).resolve().parent.parent / "mcp" / "triage_server.py"
    spec = importlib.util.spec_from_file_location("triage_server_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_load_seed_creates_expected_tables_and_columns(tmp_path):
    db_path = tmp_path / "app.db"
    load_seed(db_path=db_path, seed_dir=SEED_DIR)

    tickets = _rows(db_path, "tickets", "ticket_id")
    customers = _rows(db_path, "customers", "customer_id")

    assert tickets, "expected at least one ticket row"
    assert customers, "expected at least one customer row"
    assert set(tickets[0].keys()) == {"ticket_id", "customer_id", "created_at", "text"}
    assert set(customers[0].keys()) == {"customer_id", "name", "plan", "open_tickets"}


def test_load_seed_copies_a_known_seed_row_correctly(tmp_path):
    db_path = tmp_path / "app.db"
    load_seed(db_path=db_path, seed_dir=SEED_DIR)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        ticket = dict(conn.execute("SELECT * FROM tickets WHERE ticket_id = ?", ("T-1042",)).fetchone())
        customer = dict(conn.execute("SELECT * FROM customers WHERE customer_id = ?", ("C-77",)).fetchone())

    assert ticket["customer_id"] == "C-77"
    assert ticket["text"] == "I was charged twice this month and nobody answers."
    assert customer["name"] == "Northwind"
    assert customer["plan"] == "Enterprise"
    assert customer["open_tickets"] == 2  # loaded as int, not the CSV's string "2"


def test_load_seed_handles_a_quoted_field_containing_a_comma(tmp_path):
    # seed/tickets.csv has T-1047 with a comma inside a quoted CSV field --
    # naive comma-splitting would corrupt this row; csv.DictReader must not.
    db_path = tmp_path / "app.db"
    load_seed(db_path=db_path, seed_dir=SEED_DIR)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM tickets WHERE ticket_id = ?", ("T-1047",)).fetchone()

    assert dict(row)["text"] == "Refund the duplicate charge, please."


def test_load_seed_running_twice_leaves_the_same_database(tmp_path):
    db_path = tmp_path / "app.db"
    load_seed(db_path=db_path, seed_dir=SEED_DIR)
    first_tickets = _rows(db_path, "tickets", "ticket_id")
    first_customers = _rows(db_path, "customers", "customer_id")

    load_seed(db_path=db_path, seed_dir=SEED_DIR)
    second_tickets = _rows(db_path, "tickets", "ticket_id")
    second_customers = _rows(db_path, "customers", "customer_id")

    assert first_tickets == second_tickets
    assert first_customers == second_customers


def test_load_seed_overwrites_pre_existing_unrelated_data_in_the_tables(tmp_path):
    # A second run must leave the same database even if something else had
    # written extra rows into these tables in between -- the load rebuilds
    # the tables from scratch rather than upserting on top of prior state.
    db_path = tmp_path / "app.db"
    load_seed(db_path=db_path, seed_dir=SEED_DIR)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO tickets (ticket_id, customer_id, created_at, text) VALUES (?, ?, ?, ?)",
            ("T-9999", "C-00", "2000-01-01T00:00:00", "stray row that should not survive a reload"),
        )
        conn.commit()

    load_seed(db_path=db_path, seed_dir=SEED_DIR)

    with sqlite3.connect(db_path) as conn:
        remaining = conn.execute(
            "SELECT COUNT(*) FROM tickets WHERE ticket_id = ?", ("T-9999",)
        ).fetchone()[0]
    assert remaining == 0


def test_load_seed_output_is_readable_by_the_mcp_triage_server(tmp_path, monkeypatch):
    # This is the story's actual success signal (SPEC.md CAP-2): after
    # load_seed runs, mcp/triage_server.py's tools -- unmodified -- must be
    # able to look up a seed ticket. Every other test here only checks the
    # raw table/column shape; this one exercises the real integration
    # contract those tools depend on.
    triage_server = _import_triage_server()
    db_path = tmp_path / "app.db"
    monkeypatch.setattr(triage_server, "DB_PATH", db_path)

    load_seed(db_path=db_path, seed_dir=SEED_DIR)

    ticket = triage_server.get_ticket("T-1042")
    assert ticket["customer_id"] == "C-77"

    customer = triage_server.get_customer_history(ticket["customer_id"])
    assert customer == {
        "customer_id": "C-77",
        "name": "Northwind",
        "plan": "Enterprise",
        "open_tickets": 2,
        "ticket_ids": ["T-1042", "T-1047"],
    }
