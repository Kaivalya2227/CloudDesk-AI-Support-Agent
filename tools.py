"""
tools.py

Defines the tools (Python functions) the AI agent can call, plus the
"tool schemas" that describe them to the Claude API so the model knows
they exist and what arguments each one takes.

Each tool function queries the CloudDesk SQLite database directly.
None of these tools perform destructive actions (no cancel, no refund,
no role changes) -- those are deliberately NOT exposed as callable tools
at all, which is itself a guardrail: the agent literally cannot execute
them, regardless of what it decides to do. Destructive actions are instead
drafted as a proposed ticket/action requiring human confirmation.
"""

import sqlite3
import json

DB_NAME = "clouddesk.db"


def get_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row  # lets us access columns by name
    return conn


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def lookup_customer(email: str) -> dict:
    """Looks up a customer by email and returns their profile + account summary."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.customer_id, c.name, c.email, c.role, c.date_joined,
               a.account_id, a.company_name, a.plan_tier, a.status AS account_status
        FROM customers c
        JOIN accounts a ON c.account_id = a.account_id
        WHERE c.email = ?
    """, (email,))
    row = cursor.fetchone()
    conn.close()

    if row is None:
        return {"found": False, "message": f"No customer found with email '{email}'."}

    return {"found": True, "customer": dict(row)}


def get_account_status(account_id: int) -> dict:
    """Returns ONLY the account's status (active/locked/suspended/cancelled) and
    basic identity (company name) -- deliberately excludes billing/plan info.
    Use this when the customer asks specifically about their account status."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT account_id, company_name, status
        FROM accounts WHERE account_id = ?
    """, (account_id,))
    row = cursor.fetchone()
    conn.close()

    if row is None:
        return {"found": False, "message": f"No account found with id {account_id}."}

    return {"found": True, "account": dict(row)}


def get_billing_details(account_id: int) -> dict:
    """Returns billing-specific info: plan tier, MRR, renewal date. Separate from
    get_account_status so the agent only fetches billing data when the customer
    actually asks a billing-related question, not on every account query."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT account_id, plan_tier, mrr, renewal_date
        FROM accounts WHERE account_id = ?
    """, (account_id,))
    row = cursor.fetchone()
    conn.close()

    if row is None:
        return {"found": False, "message": f"No account found with id {account_id}."}

    return {"found": True, "billing": dict(row)}


def search_knowledge_base(query: str, category: str = None) -> dict:
    """
    Searches knowledge base articles by keyword (simple LIKE match on title/content),
    optionally filtered by category. This is intentionally simple keyword search
    rather than embeddings-based retrieval -- sufficient for a ~25-article KB,
    with semantic/embedding search as a noted future upgrade.
    """
    conn = get_connection()
    cursor = conn.cursor()

    like_pattern = f"%{query}%"
    if category:
        cursor.execute("""
            SELECT article_id, title, content, category FROM knowledge_base_articles
            WHERE (title LIKE ? OR content LIKE ?) AND category = ?
            LIMIT 3
        """, (like_pattern, like_pattern, category))
    else:
        cursor.execute("""
            SELECT article_id, title, content, category FROM knowledge_base_articles
            WHERE title LIKE ? OR content LIKE ?
            LIMIT 3
        """, (like_pattern, like_pattern))

    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return {"found": False, "message": "No matching knowledge base articles found."}

    return {"found": True, "articles": [dict(row) for row in rows]}


def check_ticket_status(ticket_id: int) -> dict:
    """Returns the status, priority, and summary of an existing ticket."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT ticket_id, account_id, status, priority, category,
               created_at, last_modified, summary, assigned_to
        FROM tickets WHERE ticket_id = ?
    """, (ticket_id,))
    row = cursor.fetchone()
    conn.close()

    if row is None:
        return {"found": False, "message": f"No ticket found with id {ticket_id}."}

    return {"found": True, "ticket": dict(row)}


def create_ticket(account_id: int, created_by_customer_id: int, category: str,
                   priority: str, summary: str) -> dict:
    """
    Creates a new support ticket. This is a NON-destructive action (adding a
    record, not modifying/deleting existing account data), so the agent is
    allowed to call this directly without requiring human confirmation first.
    """
    valid_categories = ["billing", "ivr", "routing", "integration", "account", "agent_desktop"]
    valid_priorities = ["low", "medium", "high", "urgent"]

    if category not in valid_categories:
        return {"success": False, "message": f"Invalid category '{category}'. Must be one of {valid_categories}."}
    if priority not in valid_priorities:
        return {"success": False, "message": f"Invalid priority '{priority}'. Must be one of {valid_priorities}."}

    conn = get_connection()
    cursor = conn.cursor()

    # Confirm the account and customer actually exist before creating the ticket
    cursor.execute("SELECT 1 FROM accounts WHERE account_id = ?", (account_id,))
    if cursor.fetchone() is None:
        conn.close()
        return {"success": False, "message": f"No account found with id {account_id}."}

    cursor.execute("SELECT 1 FROM customers WHERE customer_id = ?", (created_by_customer_id,))
    if cursor.fetchone() is None:
        conn.close()
        return {"success": False, "message": f"No customer found with id {created_by_customer_id}."}

    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d")

    cursor.execute("""
        INSERT INTO tickets (account_id, created_by_customer_id, status, priority,
                              category, created_at, last_modified, summary, assigned_to)
        VALUES (?, ?, 'open', ?, ?, ?, ?, ?, NULL)
    """, (account_id, created_by_customer_id, priority, category, now, now, summary))
    conn.commit()
    new_ticket_id = cursor.lastrowid
    conn.close()

    return {"success": True, "ticket_id": new_ticket_id, "message": f"Ticket #{new_ticket_id} created."}


# ---------------------------------------------------------------------------
# Tool schemas -- this is what gets sent to the Claude API so the model
# knows what tools exist, what they do, and what arguments to provide.
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = [
    {
        "name": "lookup_customer",
        "description": "Look up a customer's profile and account info by their email address.",
        "input_schema": {
            "type": "object",
            "properties": {
                "email": {"type": "string", "description": "The customer's email address."}
            },
            "required": ["email"],
        },
    },
    {
        "name": "get_account_status",
        "description": (
            "Get ONLY the account's status (active/locked/suspended/cancelled) and company "
            "name for an account by account_id. Use this when the customer asks about their "
            "account status specifically. Does NOT include billing or plan info -- use "
            "get_billing_details separately if the customer asks about billing, plan tier, "
            "MRR, or renewal date."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "account_id": {"type": "integer", "description": "The account ID to look up."}
            },
            "required": ["account_id"],
        },
    },
    {
        "name": "get_billing_details",
        "description": (
            "Get billing-specific info for an account: plan tier, monthly recurring revenue "
            "(MRR), and renewal date. Only call this when the customer specifically asks "
            "about billing, their plan, pricing, or renewal -- not for general account "
            "status questions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "account_id": {"type": "integer", "description": "The account ID to look up."}
            },
            "required": ["account_id"],
        },
    },
    {
        "name": "search_knowledge_base",
        "description": (
            "Search the knowledge base for help articles relevant to a customer's question. "
            "Use this before escalating or creating a ticket, to see if a documented answer exists."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keywords describing the issue or question."},
                "category": {
                    "type": "string",
                    "description": "Optional category filter.",
                    "enum": ["billing", "ivr", "routing", "integration", "account", "agent_desktop"],
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "check_ticket_status",
        "description": "Check the status, priority, and details of an existing support ticket by ticket_id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticket_id": {"type": "integer", "description": "The ticket ID to check."}
            },
            "required": ["ticket_id"],
        },
    },
    {
        "name": "create_ticket",
        "description": (
            "Create a new support ticket when the issue cannot be resolved via the knowledge "
            "base. Always search the knowledge base first before creating a ticket."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "account_id": {"type": "integer"},
                "created_by_customer_id": {"type": "integer"},
                "category": {
                    "type": "string",
                    "enum": ["billing", "ivr", "routing", "integration", "account", "agent_desktop"],
                },
                "priority": {"type": "string", "enum": ["low", "medium", "high", "urgent"]},
                "summary": {"type": "string", "description": "A clear summary of the customer's issue."},
            },
            "required": ["account_id", "created_by_customer_id", "category", "priority", "summary"],
        },
    },
]

# Maps tool name (string) -> actual Python function, so the agent loop can
# dynamically call the right function based on what the model requests.
TOOL_FUNCTIONS = {
    "lookup_customer": lookup_customer,
    "get_account_status": get_account_status,
    "get_billing_details": get_billing_details,
    "search_knowledge_base": search_knowledge_base,
    "check_ticket_status": check_ticket_status,
    "create_ticket": create_ticket,
}


if __name__ == "__main__":
    # Quick manual sanity check when running this file directly
    print(json.dumps(search_knowledge_base("IVR greeting"), indent=2))
