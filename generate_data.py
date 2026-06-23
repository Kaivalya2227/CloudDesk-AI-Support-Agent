"""
Generates realistic synthetic data for accounts, customers, subscriptions.
(invoices, tickets, knowledge_base_articles, agent_logs are not included in this script)

Run this AFTER create_database.py (After creating database schema):
    python create_database.py
    python generate_data.py

Re-running this script wipes and regenerates these 3 tables only (not the
full schema) Update random seed to a different value to generate different data.
"""

import sqlite3
import random
from datetime import datetime, timedelta

DB_NAME = "clouddesk.db"

random.seed(42)

TOTAL_ACCOUNTS = 200
SINGLE_USER_ACCOUNTS = 100   # 50%
MULTI_USER_ACCOUNTS = 100    # 50%

# Multi-user company size buckets: (label, min_seats, max_seats, weight)
SIZE_BUCKETS = [
    ("small", 2, 10, 0.50),
    ("medium", 11, 50, 0.35),
    ("large", 51, 150, 0.15),
]

FIRST_NAMES = [
    "James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael", "Linda",
    "David", "Elizabeth", "William", "Barbara", "Richard", "Susan", "Joseph", "Jessica",
    "Thomas", "Sarah", "Charles", "Karen", "Priya", "Wei", "Carlos", "Fatima", "Ahmed",
    "Yuki", "Olga", "Diego", "Aisha", "Liam", "Noah", "Emma", "Olivia", "Ava", "Sophia",
    "Mateo", "Lucas", "Mia", "Amara", "Kenji",
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
    "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson",
    "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson",
    "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker",
    "Patel", "Kim", "Chen", "Nguyen", "Khan",
]

COMPANY_PREFIXES = [
    "Summit", "Riverstone", "Brightpath", "Northbridge", "Clearview", "Ironwood",
    "Bluepeak", "Harborview", "Stonegate", "Meridian", "Lakeshore", "Crestline",
    "Silverline", "Oakfield", "Westgate", "Pinecrest", "Coastal", "Highland",
    "Vantage", "Cornerstone", "Brookline", "Fairmont", "Redwood", "Skyline",
]

COMPANY_SUFFIXES = [
    "Insurance Group", "Logistics", "Financial Services", "Healthcare Partners",
    "Retail Co", "Realty", "Consulting", "Telecom", "Manufacturing", "Solutions",
    "Brokerage", "Travel", "Software", "Staffing", "Energy", "Media Group",
]

PLAN_TIERS = ["starter", "growth", "enterprise"]
ACCOUNT_STATUSES = ["active", "locked", "suspended", "cancelled"]
BILLING_CYCLES = ["monthly", "annual"]

DATE_FORMAT = "%Y-%m-%d"
TODAY = datetime(2026, 6, 18)  # matches "current date" context for this project


def random_date_between(start: datetime, end: datetime) -> datetime:
    """Returns a random datetime between start and end (inclusive-ish)."""
    delta_days = (end - start).days
    if delta_days <= 0:
        return start
    return start + timedelta(days=random.randint(0, delta_days))


def make_company_name(used_names: set) -> str:
    """Generates a unique-ish fake company name from prefix + suffix combos."""
    while True:
        name = f"{random.choice(COMPANY_PREFIXES)} {random.choice(COMPANY_SUFFIXES)}"
        if name not in used_names:
            used_names.add(name)
            return name


def make_person_name() -> str:
    return f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"


def make_email(name: str, company_name: str, used_emails: set) -> str:
    """Generates a plausible work email: firstname.lastname@company.com"""
    domain = company_name.lower().replace(" ", "").replace(",", "") + ".com"
    base = name.lower().replace(" ", ".")
    email = f"{base}@{domain}"
    # Handle accidental duplicates (e.g. two "James Smith" at different companies is fine,
    # but guard against the rare same-name-same-company collision)
    counter = 1
    while email in used_emails:
        email = f"{base}{counter}@{domain}"
        counter += 1
    used_emails.add(email)
    return email


def pick_plan_tier(seat_count: int) -> str:
    """Plan tier correlates with company size, not fully independent randomness."""
    if seat_count == 1:
        # single-user accounts skew heavily toward starter
        return random.choices(PLAN_TIERS, weights=[0.70, 0.25, 0.05])[0]
    elif seat_count <= 10:
        return random.choices(PLAN_TIERS, weights=[0.45, 0.40, 0.15])[0]
    elif seat_count <= 50:
        return random.choices(PLAN_TIERS, weights=[0.10, 0.55, 0.35])[0]
    else:
        # large companies: starter would be unrealistic
        return random.choices(PLAN_TIERS, weights=[0.0, 0.30, 0.70])[0]


def pick_account_status() -> str:
    return random.choices(
        ACCOUNT_STATUSES,
        weights=[0.80, 0.10, 0.03, 0.07],  # active, locked, suspended, cancelled
    )[0]


def generate_accounts_and_customers(conn):
    cursor = conn.cursor()
    used_company_names = set()
    used_emails = set()

    accounts_data = []      # rows to insert into accounts
    customers_data = []     # rows to insert into customers
    account_seat_info = []  # (account_id placeholder index, seat_count) for later use in subscriptions

    # Build size assignment list for the 100 multi-user accounts up front,
    # respecting bucket weights (50/35/15 small/medium/large)
    multi_user_sizes = []
    for label, lo, hi, weight in SIZE_BUCKETS:
        count = round(MULTI_USER_ACCOUNTS * weight)
        for _ in range(count):
            multi_user_sizes.append(random.randint(lo, hi))
    # Adjust for rounding so we have exactly MULTI_USER_ACCOUNTS entries
    while len(multi_user_sizes) < MULTI_USER_ACCOUNTS:
        multi_user_sizes.append(random.randint(2, 10))
    while len(multi_user_sizes) > MULTI_USER_ACCOUNTS:
        multi_user_sizes.pop()
    random.shuffle(multi_user_sizes)

    # All seat counts: 100 single-user (seat_count=1) + 100 multi-user (varied)
    all_seat_counts = [1] * SINGLE_USER_ACCOUNTS + multi_user_sizes
    random.shuffle(all_seat_counts)

    for seat_count in all_seat_counts:
        company_name = make_company_name(used_company_names)
        plan_tier = pick_plan_tier(seat_count)
        status = pick_account_status()

        # account creation date: somewhere in the last 4 years
        account_created = random_date_between(TODAY - timedelta(days=4 * 365), TODAY - timedelta(days=30))
        # last_modified must be >= account_created (date_joined-equivalent rule for accounts)
        account_last_modified = random_date_between(account_created, TODAY)
        renewal_date = TODAY + timedelta(days=random.randint(10, 365))

        # mrr roughly correlates with plan tier and seat count
        base_price = {"starter": 29, "growth": 99, "enterprise": 249}[plan_tier]
        per_seat = {"starter": 5, "growth": 12, "enterprise": 25}[plan_tier]
        mrr = round(base_price + per_seat * max(seat_count - 1, 0), 2)

        accounts_data.append((
            company_name, plan_tier, status,
            renewal_date.strftime(DATE_FORMAT),
            mrr,
            account_last_modified.strftime(DATE_FORMAT),
        ))

        account_seat_info.append({
            "seat_count": seat_count,
            "account_created": account_created,
            "account_last_modified": account_last_modified,
        })

    # Insert accounts and capture their auto-generated IDs
    cursor.executemany("""
        INSERT INTO accounts (company_name, plan_tier, status, renewal_date, mrr, last_modified)
        VALUES (?, ?, ?, ?, ?, ?)
    """, accounts_data)
    conn.commit()

    cursor.execute("SELECT account_id FROM accounts ORDER BY account_id;")
    account_ids = [row[0] for row in cursor.fetchall()]

    # Now generate customers per account, respecting role distribution rules
    for account_id, info in zip(account_ids, account_seat_info):
        seat_count = info["seat_count"]
        account_created = info["account_created"]
        account_last_modified = info["account_last_modified"]

        # Determine role counts based on company size
        if seat_count == 1:
            roles = ["owner"]
        else:
            if seat_count <= 10:
                num_admins = random.randint(1, 2)
            elif seat_count <= 50:
                num_admins = random.randint(2, 5)
            else:
                num_admins = random.randint(5, 10)
            num_admins = min(num_admins, seat_count - 1)  # leave room for at least 1 owner + members
            num_members = seat_count - 1 - num_admins
            roles = ["owner"] + ["admin"] * num_admins + ["member"] * num_members

        company_name_row = cursor.execute(
            "SELECT company_name FROM accounts WHERE account_id = ?", (account_id,)
        ).fetchone()
        company_name = company_name_row[0]

        for role in roles:
            person_name = make_person_name()
            email = make_email(person_name, company_name, used_emails)

            # date_joined must be >= account_created and <= last_modified (the rule you specified)
            date_joined = random_date_between(account_created, account_last_modified)
            # most users share the same last_modified as their account (per your spec:
            # "last_modified will be same for most of the users"), with occasional individual updates
            if random.random() < 0.85:
                customer_last_modified = account_last_modified
            else:
                customer_last_modified = random_date_between(date_joined, TODAY)

            customers_data.append((
                account_id, person_name, email, role,
                date_joined.strftime(DATE_FORMAT),
                customer_last_modified.strftime(DATE_FORMAT),
            ))

    cursor.executemany("""
        INSERT INTO customers (account_id, name, email, role, date_joined, last_modified)
        VALUES (?, ?, ?, ?, ?, ?)
    """, customers_data)
    conn.commit()

    print(f"✅ Inserted {len(accounts_data)} accounts and {len(customers_data)} customers.")
    return account_ids, account_seat_info


def generate_subscriptions(conn, account_ids, account_seat_info):
    cursor = conn.cursor()
    subscriptions_data = []

    for account_id, info in zip(account_ids, account_seat_info):
        seat_count = info["seat_count"]
        account_last_modified = info["account_last_modified"]

        billing_cycle = random.choices(BILLING_CYCLES, weights=[0.60, 0.40])[0]
        seats_purchased = seat_count + random.randint(0, 3)  # small buffer above actual headcount
        auto_pay = 1 if random.random() < 0.70 else 0

        # billing address: simple fake street address
        street_num = random.randint(100, 9999)
        street_names = ["Market St", "Main St", "Industrial Ave", "Corporate Dr", "1st Ave", "Tech Park Rd"]
        cities = ["Austin, TX", "Denver, CO", "Columbus, OH", "Raleigh, NC", "Phoenix, AZ", "Atlanta, GA"]
        billing_address = f"{street_num} {random.choice(street_names)}, {random.choice(cities)} USA"

        subscriptions_data.append((
            account_id, billing_cycle, seats_purchased, auto_pay,
            billing_address,
            account_last_modified.strftime(DATE_FORMAT),
        ))

    cursor.executemany("""
        INSERT INTO subscriptions (account_id, billing_cycle, seats_purchased, auto_pay, billing_address, last_modified)
        VALUES (?, ?, ?, ?, ?, ?)
    """, subscriptions_data)
    conn.commit()

    print(f"✅ Inserted {len(subscriptions_data)} subscriptions.")


def clear_existing_data(conn):
    """Wipes these 3 tables (and dependents) so this script is safely re-runnable."""
    cursor = conn.cursor()
    cursor.executescript("""
        DELETE FROM agent_logs;
        DELETE FROM tickets;
        DELETE FROM invoices;
        DELETE FROM subscriptions;
        DELETE FROM customers;
        DELETE FROM accounts;
        DELETE FROM sqlite_sequence WHERE name IN
            ('accounts', 'customers', 'subscriptions', 'invoices', 'tickets', 'agent_logs');
    """)
    conn.commit()


if __name__ == "__main__":
    connection = sqlite3.connect(DB_NAME)
    clear_existing_data(connection)
    ids, seat_info = generate_accounts_and_customers(connection)
    generate_subscriptions(connection, ids, seat_info)
    connection.close()
    print("\nDone. Run create_database.py again first if you ever need a full schema reset.")