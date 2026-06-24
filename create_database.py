"""
Creates the CloudDesk SQLite database and all tables from scratch.

Run this with:
    python create_database.py

This will create a file called `clouddesk.db` in the same folder.
Safe to re-run: it drops existing tables first, so you always get a clean schema.
"""

import sqlite3

DB_NAME = "clouddesk.db"


def create_connection():
    """Creates (or opens) the SQLite database file and returns a connection."""
    conn = sqlite3.connect(DB_NAME)
    return conn


def create_tables(conn):
    cursor = conn.cursor()

    # Drop tables first if they exist, so this script is safely re-runnable
    # during development. Order matters: drop child tables before parents
    # to avoid foreign key issues.
    cursor.executescript("""
        DROP TABLE IF EXISTS agent_logs;
        DROP TABLE IF EXISTS verification_attempts;
        DROP TABLE IF EXISTS tickets;
        DROP TABLE IF EXISTS invoices;
        DROP TABLE IF EXISTS subscriptions;
        DROP TABLE IF EXISTS customers;
        DROP TABLE IF EXISTS accounts;
        DROP TABLE IF EXISTS knowledge_base_articles;
    """)

    # --- accounts -----------------------------------------------------
    # One account = one company (the paying CloudDesk customer org).
    cursor.execute("""
        CREATE TABLE accounts (
            account_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name    TEXT NOT NULL,
            plan_tier       TEXT NOT NULL CHECK (plan_tier IN ('starter', 'growth', 'enterprise')),
            status          TEXT NOT NULL CHECK (status IN ('active', 'locked', 'suspended', 'cancelled')),
            renewal_date    TEXT NOT NULL,
            mrr             REAL NOT NULL,
            last_modified   TEXT NOT NULL
        );
    """)

    # --- customers ------------------------------------------------------
    # Multiple customers (people) belong to one account.
    # Exactly one per account should have role = 'owner' (enforced in app code,
    # not in the schema itself — SQLite doesn't make partial unique constraints easy).
    cursor.execute("""
        CREATE TABLE customers (
            customer_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id      INTEGER NOT NULL,
            name            TEXT NOT NULL,
            email           TEXT NOT NULL UNIQUE,
            role            TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'member')),
            date_joined     TEXT NOT NULL,
            last_modified   TEXT NOT NULL,
            FOREIGN KEY (account_id) REFERENCES accounts (account_id)
        );
    """)

    # --- subscriptions ----------------------------------------------------
    cursor.execute("""
        CREATE TABLE subscriptions (
            subscription_id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id       INTEGER NOT NULL,
            billing_cycle    TEXT NOT NULL CHECK (billing_cycle IN ('monthly', 'annual')),
            seats_purchased  INTEGER NOT NULL,
            auto_pay         INTEGER NOT NULL CHECK (auto_pay IN (0, 1)),  -- boolean: 0=False, 1=True
            billing_address  TEXT NOT NULL,
            last_modified    TEXT NOT NULL,
            FOREIGN KEY (account_id) REFERENCES accounts (account_id)
        );
    """)

    # --- invoices -----------------------------------------------------
    cursor.execute("""
        CREATE TABLE invoices (
            invoice_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id   INTEGER NOT NULL,
            amount       REAL NOT NULL,
            date         TEXT NOT NULL,
            status       TEXT NOT NULL CHECK (status IN ('paid', 'failed', 'pending')),
            FOREIGN KEY (account_id) REFERENCES accounts (account_id)
        );
    """)

    # --- tickets --------------------------------------------------------
    cursor.execute("""
        CREATE TABLE tickets (
            ticket_id              INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id              INTEGER NOT NULL,
            created_by_customer_id  INTEGER NOT NULL,
            status                  TEXT NOT NULL CHECK (status IN ('open', 'in_progress', 'resolved', 'escalated')),
            priority                TEXT NOT NULL CHECK (priority IN ('low', 'medium', 'high', 'urgent')),
            category                TEXT NOT NULL CHECK (category IN ('billing', 'ivr', 'routing', 'integration', 'account', 'agent_desktop')),
            created_at              TEXT NOT NULL,
            last_modified           TEXT NOT NULL,
            summary                 TEXT NOT NULL,
            assigned_to              TEXT,
            FOREIGN KEY (account_id) REFERENCES accounts (account_id),
            FOREIGN KEY (created_by_customer_id) REFERENCES customers (customer_id)
        );
    """)

    # --- knowledge_base_articles ----------------------------------------
    # Not linked to other tables via foreign key — it's a standalone reference
    # set the agent searches against (a simple stand-in for a RAG knowledge base).
    cursor.execute("""
        CREATE TABLE knowledge_base_articles (
            article_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            title        TEXT NOT NULL,
            content      TEXT NOT NULL,
            category     TEXT NOT NULL CHECK (category IN ('billing', 'ivr', 'routing', 'integration', 'account', 'agent_desktop'))
        );
    """)

    # --- verification_attempts -------------------------------------------
    # Tracks failed identity verification attempts, keyed by the email being
    # attempted (not the account) -- this is what enables throttling a
    # specific verification session without ever touching the real account
    # record. See guardrails.py for the throttling logic that uses this.
    cursor.execute("""
        CREATE TABLE verification_attempts (
            attempt_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            email_attempted TEXT NOT NULL,
            attempted_at    TEXT NOT NULL,
            succeeded       INTEGER NOT NULL CHECK (succeeded IN (0, 1))
        );
    """)

    # --- agent_logs -------------------------------------------------------
    # Every interaction the agent has gets logged here. This is the backbone
    # of the evaluation harness we'll build in week 2.
    cursor.execute("""
        CREATE TABLE agent_logs (
            log_id                          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp                       TEXT NOT NULL,
            customer_id                     INTEGER,
            customer_query                  TEXT NOT NULL,
            tools_called                    TEXT,   -- stored as JSON text, e.g. '["lookup_customer", "search_kb"]'
            final_response                  TEXT,
            escalated                       INTEGER NOT NULL CHECK (escalated IN (0, 1)),
            human_confirmation_required     INTEGER NOT NULL CHECK (human_confirmation_required IN (0, 1)),
            outcome                         TEXT NOT NULL CHECK (outcome IN ('resolved', 'escalated', 'ticket_created', 'refused')),
            FOREIGN KEY (customer_id) REFERENCES customers (customer_id)
        );
    """)

    conn.commit()
    print(f"Database '{DB_NAME}' created successfully with all 7 tables.")


def verify_tables(conn):
    """Prints out the list of tables that now exist, as a sanity check."""
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    print("\nTables in database:")
    for table in tables:
        print(f"  - {table[0]}")


if __name__ == "__main__":
    connection = create_connection()
    create_tables(connection)
    verify_tables(connection)
    connection.close()
