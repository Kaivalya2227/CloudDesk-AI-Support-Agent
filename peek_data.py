"""
peek_data.py

A small helper for browsing sample data while testing the agent, so you don't
have to retype SQL one-liners every time you need a customer email, account_id,
or ticket_id to test with.

Run this directly:
    python peek_data.py
"""

import sqlite3

DB_NAME = "clouddesk.db"

def peek():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    print("=== 5 sample customers (with their account info) ===")
    cursor.execute("""
        SELECT c.customer_id, c.name, c.email, c.role, a.account_id, a.company_name, a.status
        FROM customers c
        JOIN accounts a ON c.account_id = a.account_id
        LIMIT 5
    """)
    for row in cursor.fetchall():
        print(dict(row))

    print("\n=== 5 sample tickets ===")
    cursor.execute("""
        SELECT ticket_id, account_id, status, priority, category, summary
        FROM tickets
        LIMIT 5
    """)
    for row in cursor.fetchall():
        print(dict(row))

    print("\n=== A locked account (good for testing edge cases) ===")
    cursor.execute("""
        SELECT c.name, c.email, a.account_id, a.company_name, a.status
        FROM customers c JOIN accounts a ON c.account_id = a.account_id
        WHERE a.status = 'locked' LIMIT 3
    """)
    for row in cursor.fetchall():
        print(dict(row))

    print("\n=== An account owner (good for testing role-based actions) ===")
    cursor.execute("""
        SELECT c.name, c.email, c.role, a.account_id, a.company_name
        FROM customers c JOIN accounts a ON c.account_id = a.account_id
        WHERE c.role = 'owner' LIMIT 3
    """)
    for row in cursor.fetchall():
        print(dict(row))

    conn.close()


if __name__ == "__main__":
    peek()
