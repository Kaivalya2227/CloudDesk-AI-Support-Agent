"""
seed_eval_fixtures.py

Inserts a small number of DELIBERATE data anomalies needed to test specific
guardrail/reasoning behaviors that don't occur naturally in the randomly
generated dataset -- e.g., the synthetic data generator produces invoices on
a clean schedule with no near-duplicate charges, so there's no real case to
test "does the agent correctly detect a duplicate charge" against.

Run this AFTER the normal data generation scripts, as the last step:
    python create_database.py
    python generate_data.py
    python generate_invoices_tickets.py
    python load_kb_articles.py
    python seed_eval_fixtures.py   <-- adds eval-only fixtures

Safe to re-run: removes any previously-seeded fixture rows (tagged via a
fixed amount/date pair below) before re-inserting.
"""

import sqlite3

DB_NAME = "clouddesk.db"

# A deliberate near-duplicate charge for account 1 (Noah Thomas / Highland Staffing),
# one day after their real most recent invoice, same amount -- this is the exact
# pattern the agent should learn to flag as a likely duplicate.
DUPLICATE_INVOICE_FIXTURE = {
    "account_id": 1,
    "amount": 157.76,        # matches the real invoice on 2026-05-13
    "date": "2026-05-14",    # one day later -- the actual duplicate signature
    "status": "paid",
}


def seed_duplicate_invoice(conn):
    cursor = conn.cursor()

    # Remove any previously-seeded fixture with this exact amount/date first,
    # so re-running this script doesn't pile up duplicates of the duplicate.
    cursor.execute("""
        DELETE FROM invoices
        WHERE account_id = ? AND amount = ? AND date = ?
    """, (
        DUPLICATE_INVOICE_FIXTURE["account_id"],
        DUPLICATE_INVOICE_FIXTURE["amount"],
        DUPLICATE_INVOICE_FIXTURE["date"],
    ))

    cursor.execute("""
        INSERT INTO invoices (account_id, amount, date, status)
        VALUES (?, ?, ?, ?)
    """, (
        DUPLICATE_INVOICE_FIXTURE["account_id"],
        DUPLICATE_INVOICE_FIXTURE["amount"],
        DUPLICATE_INVOICE_FIXTURE["date"],
        DUPLICATE_INVOICE_FIXTURE["status"],
    ))
    conn.commit()
    print(f"Seeded 1 deliberate duplicate invoice fixture for account {DUPLICATE_INVOICE_FIXTURE['account_id']}.")


if __name__ == "__main__":
    connection = sqlite3.connect(DB_NAME)
    seed_duplicate_invoice(connection)
    connection.close()
