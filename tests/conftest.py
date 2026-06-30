"""
Pytest fixtures shared across all test files. The key fixture here is
`test_db`, which builds a small, ISOLATED, throwaway SQLite database for
each test, not the real clouddesk.db. This matters for two reasons:

1. Tests stay deterministic. If tests ran against the real database, results
   would depend on whatever state it happens to be in (which accounts are
   locked today, how many tickets exist, etc.) -- not reproducible.
2. Tests don't pollute real data. Earlier in this project, manual testing of
   create_ticket() left a stray test ticket in the real database that had
   to be cleaned up by hand. A fixture database sidesteps that entirely --
   it's discarded after each test.

The fixture works by pointing the CLOUDDESK_DB_PATH environment variable
(read by tools.py and guardrails.py) at a temporary file, then building the
real schema (reusing create_database.py's create_tables function, so the
test schema can never drift out of sync with the real one) and seeding a
small, known set of test data.
"""

import os
import sys
import sqlite3
import tempfile
import pytest

# Allow importing tools.py, guardrails.py, create_database.py from the project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def test_db(monkeypatch):
    """
    Creates a temporary SQLite database with the real schema and a small set
    of known test rows, points CLOUDDESK_DB_PATH at it for the duration of
    the test, and cleans up the file afterward.

    Returns the path to the temp database, in case a test needs it directly.
    """
    # Create a temp file path (don't keep it open -- sqlite3.connect will create it)
    fd, temp_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(temp_path)  # sqlite3.connect creates a fresh file

    # Point tools.py / guardrails.py at this temp database BEFORE importing them,
    # since they read the env var once at import time into their DB_NAME constant.
    monkeypatch.setenv("CLOUDDESK_DB_PATH", temp_path)

    # Import here (not at module level) so the env var is already set when
    # tools.py/guardrails.py read it into their DB_NAME constant. Reload in
    # case a previous test already imported them with a different DB_NAME.
    import importlib
    import create_database
    import tools
    import guardrails
    importlib.reload(create_database)
    importlib.reload(tools)
    importlib.reload(guardrails)

    conn = sqlite3.connect(temp_path)
    create_database.create_tables(conn)
    _seed_test_data(conn)
    conn.close()

    yield temp_path

    # Cleanup
    if os.path.exists(temp_path):
        os.remove(temp_path)


def _seed_test_data(conn):
    """Seeds a small, known set of test rows -- deliberately simple and
    hand-picked, not randomly generated, so test expectations can reference
    exact values (e.g., 'account 1 has status active')."""
    cursor = conn.cursor()

    # accounts: one active, one locked, one suspended
    cursor.executescript("""
        INSERT INTO accounts (account_id, company_name, plan_tier, status, renewal_date, mrr, last_modified)
        VALUES
            (1, 'Test Co Active', 'growth', 'active', '2027-01-01', 159.0, '2026-01-01'),
            (2, 'Test Co Locked', 'enterprise', 'locked', '2027-01-01', 249.0, '2026-01-01'),
            (3, 'Test Co Suspended', 'starter', 'suspended', '2027-01-01', 29.0, '2026-01-01');
    """)

    # customers: owner, admin, member all on account 1; one owner on account 2
    cursor.executescript("""
        INSERT INTO customers (customer_id, account_id, name, email, role, date_joined, last_modified)
        VALUES
            (1, 1, 'Test Owner', 'owner@testco.com', 'owner', '2026-01-01', '2026-01-01'),
            (2, 1, 'Test Admin', 'admin@testco.com', 'admin', '2026-01-01', '2026-01-01'),
            (3, 1, 'Test Member', 'member@testco.com', 'member', '2026-01-01', '2026-01-01'),
            (4, 2, 'Locked Owner', 'owner@lockedco.com', 'owner', '2026-01-01', '2026-01-01');
    """)

    # invoices: a couple for account 1
    cursor.executescript("""
        INSERT INTO invoices (invoice_id, account_id, amount, date, status)
        VALUES
            (1, 1, 159.0, '2026-05-01', 'paid'),
            (2, 1, 159.0, '2026-04-01', 'paid');
    """)

    # tickets: one resolved ticket on account 1
    cursor.executescript("""
        INSERT INTO tickets (ticket_id, account_id, created_by_customer_id, status, priority,
                              category, created_at, last_modified, summary, assigned_to)
        VALUES
            (1, 1, 1, 'resolved', 'high', 'routing', '2026-05-01', '2026-05-02',
             'Test ticket summary', 'Test Agent');
    """)

    # knowledge_base_articles: one article, searchable by "test"
    cursor.executescript("""
        INSERT INTO knowledge_base_articles (article_id, title, content, category)
        VALUES
            (1, 'Test Article Title', 'This is test content about billing.', 'billing');
    """)

    conn.commit()
