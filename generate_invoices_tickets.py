"""
Generates realistic synthetic data for: invoices, tickets.
Run this AFTER create_database.py and generate_data.py:

    python create_database.py
    python generate_data.py
    python generate_invoices_tickets.py

Re-running this script wipes and regenerates only these 2 tables.
"""

import sqlite3
import random
import json
from datetime import datetime, timedelta

DB_NAME = "clouddesk.db"
random.seed(42)

TODAY = datetime(2026, 6, 18)
DATE_FORMAT = "%Y-%m-%d"

TICKET_CATEGORIES = ["billing", "ivr", "routing", "integration", "account", "agent_desktop"]
TICKET_STATUSES = ["open", "in_progress", "resolved", "escalated"]
TICKET_PRIORITIES = ["low", "medium", "high", "urgent"]

SUPPORT_AGENTS = [
    "Alex Rivera", "Sam Okafor", "Jordan Kim", "Taylor Brooks", "Morgan Singh", None,
]  # None = unassigned (common for 'open' tickets)

# Ticket summary templates per category -- gives realistic, varied but on-topic text
TICKET_TEMPLATES = {
    "billing": [
        "Customer reports being charged twice for the {month} invoice.",
        "Auto-pay failed and account is at risk of being locked.",
        "Customer wants to switch from monthly to annual billing.",
        "Invoice amount doesn't match the agreed seat count.",
        "Customer requesting an invoice copy for their finance team.",
        "Card on file expired, payment failed for latest invoice.",
    ],
    "ivr": [
        "IVR greeting still references the old business hours.",
        "Customer can't figure out how to add a new menu option to their IVR.",
        "Calls to the 'billing' IVR option are routing to the wrong queue.",
        "Customer wants to record a new IVR greeting but the upload is failing.",
        "IVR menu loops back to the main menu instead of connecting to an agent.",
    ],
    "routing": [
        "Calls are not being distributed evenly across available agents.",
        "Skill-based routing isn't matching calls to the correct team.",
        "Customer reports calls dropping before being routed to an agent.",
        "Queue wait time is much higher than expected during peak hours.",
        "VIP customer calls aren't being prioritized in the queue as configured.",
    ],
    "integration": [
        "Salesforce sync stopped updating customer records two days ago.",
        "HubSpot integration is duplicating contact entries.",
        "Customer can't generate an API key for their CRM integration.",
        "Webhook events from CloudDesk aren't reaching their ticketing system.",
        "Integration setup wizard fails at the authentication step.",
    ],
    "account": [
        "Customer requesting to downgrade their plan at renewal.",
        "Account owner wants to transfer ownership to a new employee.",
        "Customer asking why their account was locked.",
        "Request to add 10 additional seats to the account.",
        "Customer wants to cancel their subscription before next renewal.",
        "Admin requesting role change for a team member.",
    ],
    "agent_desktop": [
        "Support agent can't see customer call history in the desktop view.",
        "Agent desktop is logging users out randomly during calls.",
        "Customer reports the desktop app is slow to load contact details.",
        "Agent unable to reset their own password to access the desktop.",
        "Screen pop isn't showing the correct customer record on inbound calls.",
    ],
}

MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]


def random_date_between(start: datetime, end: datetime) -> datetime:
    delta_days = (end - start).days
    if delta_days <= 0:
        return start
    return start + timedelta(days=random.randint(0, delta_days))


def get_accounts_with_context(conn):
    """Pulls accounts joined with their subscription info and customer lists,
    so invoice/ticket generation can stay consistent with existing data."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT a.account_id, a.status, a.mrr, a.last_modified,
               s.billing_cycle, s.last_modified
        FROM accounts a
        JOIN subscriptions s ON a.account_id = s.account_id
    """)
    accounts = cursor.fetchall()

    cursor.execute("SELECT customer_id, account_id, date_joined FROM customers")
    customers_by_account = {}
    for customer_id, account_id, date_joined in cursor.fetchall():
        customers_by_account.setdefault(account_id, []).append((customer_id, date_joined))

    return accounts, customers_by_account


def generate_invoices(conn, accounts):
    cursor = conn.cursor()
    invoices_data = []

    for account_id, status, mrr, account_last_modified, billing_cycle, sub_last_modified in accounts:
        account_last_mod_date = datetime.strptime(account_last_modified, DATE_FORMAT)

        # number of past invoices roughly based on billing cycle and account age
        # (kept simple: monthly accounts get more invoice history than annual)
        if billing_cycle == "monthly":
            num_invoices = random.randint(3, 12)
            interval_days = 30
        else:
            num_invoices = random.randint(1, 3)
            interval_days = 365

        invoice_date = account_last_mod_date - timedelta(days=interval_days * (num_invoices - 1))

        for i in range(num_invoices):
            this_date = invoice_date + timedelta(days=interval_days * i)
            if this_date > TODAY:
                break

            # most invoices paid; failed/pending more likely for locked/suspended accounts
            if status in ("locked", "suspended"):
                inv_status = random.choices(["paid", "failed", "pending"], weights=[0.4, 0.4, 0.2])[0]
            else:
                inv_status = random.choices(["paid", "failed", "pending"], weights=[0.90, 0.05, 0.05])[0]

            # small natural variance around the account's mrr
            amount = round(mrr * random.uniform(0.95, 1.05), 2)

            invoices_data.append((
                account_id, amount, this_date.strftime(DATE_FORMAT), inv_status
            ))

    cursor.executemany("""
        INSERT INTO invoices (account_id, amount, date, status)
        VALUES (?, ?, ?, ?)
    """, invoices_data)
    conn.commit()
    print(f"Inserted {len(invoices_data)} invoices.")


def generate_tickets(conn, accounts, customers_by_account):
    cursor = conn.cursor()
    tickets_data = []

    for account_id, status, mrr, account_last_modified, billing_cycle, sub_last_modified in accounts:
        customers = customers_by_account.get(account_id, [])
        if not customers:
            continue

        account_last_mod_date = datetime.strptime(account_last_modified, DATE_FORMAT)

        # number of tickets loosely scales with number of users at the account
        seat_count = len(customers)
        if seat_count == 1:
            num_tickets = random.randint(0, 3)
        elif seat_count <= 10:
            num_tickets = random.randint(1, 6)
        elif seat_count <= 50:
            num_tickets = random.randint(3, 12)
        else:
            num_tickets = random.randint(8, 20)

        for _ in range(num_tickets):
            creator_id, creator_joined = random.choice(customers)
            creator_joined_date = datetime.strptime(creator_joined, DATE_FORMAT)

            created_at = random_date_between(
                max(creator_joined_date, account_last_mod_date - timedelta(days=365)),
                account_last_mod_date,
            )

            category = random.choice(TICKET_CATEGORIES)
            summary_template = random.choice(TICKET_TEMPLATES[category])
            summary = summary_template.format(month=random.choice(MONTHS))

            ticket_status = random.choices(
                TICKET_STATUSES, weights=[0.15, 0.10, 0.65, 0.10]
            )[0]
            priority = random.choices(
                TICKET_PRIORITIES, weights=[0.30, 0.40, 0.20, 0.10]
            )[0]

            # last_modified must be >= created_at
            if ticket_status == "resolved":
                last_modified = random_date_between(created_at, account_last_mod_date)
                assigned_to = random.choice(SUPPORT_AGENTS[:-1])  # resolved tickets are always assigned
            elif ticket_status == "open":
                last_modified = created_at  # untouched since creation
                assigned_to = random.choice(SUPPORT_AGENTS)  # may or may not be assigned
            else:
                last_modified = random_date_between(created_at, account_last_mod_date)
                assigned_to = random.choice(SUPPORT_AGENTS[:-1])

            tickets_data.append((
                account_id, creator_id, ticket_status, priority, category,
                created_at.strftime(DATE_FORMAT), last_modified.strftime(DATE_FORMAT),
                summary, assigned_to,
            ))

    cursor.executemany("""
        INSERT INTO tickets (account_id, created_by_customer_id, status, priority, category,
                              created_at, last_modified, summary, assigned_to)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, tickets_data)
    conn.commit()
    print(f"Inserted {len(tickets_data)} tickets.")


def clear_existing_data(conn):
    cursor = conn.cursor()
    cursor.executescript("""
        DELETE FROM agent_logs;
        DELETE FROM tickets;
        DELETE FROM invoices;
        DELETE FROM sqlite_sequence WHERE name IN ('invoices', 'tickets', 'agent_logs');
    """)
    conn.commit()


if __name__ == "__main__":
    connection = sqlite3.connect(DB_NAME)
    clear_existing_data(connection)
    accounts, customers_by_account = get_accounts_with_context(connection)
    generate_invoices(connection, accounts)
    generate_tickets(connection, accounts, customers_by_account)
    connection.close()
    print("\nDone.")
