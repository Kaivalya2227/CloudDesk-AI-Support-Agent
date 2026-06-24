"""
guardrails.py

Safety and access-control logic that sits BETWEEN the user and the agent's
tools. This is deliberately implemented in plain Python, not as instructions
to the LLM -- verification and role-based filtering must hold even if the
model is confused, manipulated, or simply makes a mistake. An instruction
("please verify the user first") can be argued around by a clever prompt;
a code path that refuses to run without a verified session cannot.

Two things live here:
1. Identity verification (simulates "logging in" with email + account_id)
2. Role-based field filtering (owner/admin see full billing info, members don't)
"""

import sqlite3
from datetime import datetime, timedelta

DB_NAME = "clouddesk.db"


def get_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


class VerificationError(Exception):
    """Raised when identity verification fails."""
    pass


class ThrottledError(Exception):
    """Raised when an email has too many recent failed attempts and is
    temporarily blocked from further verification tries."""
    pass


MAX_ATTEMPTS = 3
THROTTLE_WINDOW_MINUTES = 15


def record_attempt(email: str, succeeded: bool) -> None:
    """Logs a verification attempt (success or failure) keyed by the email
    that was tried. This is what enables throttling without ever touching
    the actual account record."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO verification_attempts (email_attempted, attempted_at, succeeded)
        VALUES (?, datetime('now'), ?)
    """, (email, 1 if succeeded else 0))
    conn.commit()
    conn.close()


def is_throttled(email: str) -> tuple:
    """
    Checks whether this email has had MAX_ATTEMPTS or more consecutive failed
    attempts within the last THROTTLE_WINDOW_MINUTES. Returns (is_throttled, minutes_remaining).

    Only counts failures SINCE the last success (or since the beginning, if
    there's never been a success) -- a successful verification resets the count,
    same as how most real lockout systems behave.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT attempted_at, succeeded FROM verification_attempts
        WHERE email_attempted = ?
        ORDER BY attempted_at DESC
    """, (email,))
    rows = cursor.fetchall()
    conn.close()

    recent_failures = []
    for row in rows:
        if row["succeeded"]:
            break  # stop counting once we hit a prior success
        recent_failures.append(row["attempted_at"])

    if len(recent_failures) < MAX_ATTEMPTS:
        return False, 0

    # Check if the most recent failure run is still within the throttle window
    most_recent_failure = datetime.strptime(recent_failures[0], "%Y-%m-%d %H:%M:%S")
    elapsed = datetime.now() - most_recent_failure
    window = timedelta(minutes=THROTTLE_WINDOW_MINUTES)

    if elapsed < window:
        minutes_remaining = int((window - elapsed).total_seconds() // 60) + 1
        return True, minutes_remaining

    return False, 0


def verify_identity(email: str, account_id: int) -> dict:
    """
    Confirms that the given email belongs to a customer on the given account_id.
    This simulates a logged-in session: in a real deployment, this check would
    happen via SSO/login before the chat even starts, and the agent would simply
    receive an already-verified customer_id. Here, we simulate it with a
    two-factor check (email + account_id) since the customer must know both to
    pass -- an attacker guessing a single leaked email cannot authenticate.

    Throttling is applied per email-attempted, NOT per account -- after
    MAX_ATTEMPTS consecutive failures, further attempts for that email are
    blocked for THROTTLE_WINDOW_MINUTES. The underlying account record is never
    modified, since at this point we don't know whether the failures came from
    the legitimate owner or an attacker; locking the real account would let an
    attacker deny service to the legitimate customer just by failing on purpose.

    Returns the verified customer record on success.
    Raises ThrottledError if this email is currently throttled.
    Raises VerificationError on failure (deliberately without revealing WHICH
    field was wrong, to avoid letting someone fish for valid emails or account IDs).
    """
    throttled, minutes_remaining = is_throttled(email)
    if throttled:
        raise ThrottledError(
            f"Too many failed verification attempts for this email. "
            f"Please try again in about {minutes_remaining} minute(s)."
        )

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT customer_id, name, email, role, account_id
        FROM customers
        WHERE email = ? AND account_id = ?
    """, (email, account_id))
    row = cursor.fetchone()
    conn.close()

    if row is None:
        record_attempt(email, succeeded=False)
        raise VerificationError(
            "We couldn't verify your identity with that email and account ID. "
            "Please double check both and try again."
        )

    record_attempt(email, succeeded=True)
    return dict(row)


# ---------------------------------------------------------------------------
# Role-based field filtering
# ---------------------------------------------------------------------------

# Fields hidden from each role when viewing billing details.
# 'member' cannot see MRR (a sensitive revenue/cost figure); 'owner' and 'admin' see everything.
RESTRICTED_FIELDS_BY_ROLE = {
    "owner": [],
    "admin": [],
    "member": ["mrr"],
}


def filter_billing_fields(billing_data: dict, role: str) -> dict:
    """
    Removes fields the given role isn't allowed to see from a get_billing_details
    result. Applied AFTER the tool runs, so the underlying tool function stays
    simple -- filtering is a separate, explicit step, which also makes it easy
    to point to in an interview as a deliberate access-control layer.
    """
    restricted = RESTRICTED_FIELDS_BY_ROLE.get(role, ["mrr"])  # default to most restrictive
    filtered = {k: v for k, v in billing_data.items() if k not in restricted}
    if restricted:
        filtered["_note"] = (
            f"Some billing details are restricted for your role ({role}). "
            "Ask an account owner or admin for full billing details."
        )
    return filtered


# Roles allowed to view itemized invoice history (actual dollar amounts charged).
# Unlike the MRR field-level filter above, invoice access is all-or-nothing:
# there's no meaningful way to show "an invoice" with the amount redacted, so a
# 'member' is blocked from the tool entirely rather than given a partial result.
ROLES_ALLOWED_INVOICE_ACCESS = {"owner", "admin"}


def invoice_access_allowed(role: str) -> bool:
    """Returns True if this role is allowed to view itemized invoice history."""
    return role in ROLES_ALLOWED_INVOICE_ACCESS


# Account statuses that block self-service billing access entirely, regardless
# of role. Realistic rationale: a locked/suspended account is often locked
# BECAUSE of a billing issue (failed payment, fraud review), so billing details
# are restricted to push the customer toward a human-verified support channel
# rather than letting an automated agent freely discuss billing on a flagged
# account.
BILLING_RESTRICTED_STATUSES = ["locked", "suspended"]


def billing_access_blocked(account_status: str) -> bool:
    """Returns True if this account's status should block self-service billing access."""
    return account_status in BILLING_RESTRICTED_STATUSES


# ---------------------------------------------------------------------------
# Destructive-action guardrail (used by the agent loop, not tools.py, since
# these aren't real tools at all -- see PROJECT_NOTES.md for the reasoning)
# ---------------------------------------------------------------------------

DESTRUCTIVE_ACTION_KEYWORDS = [
    "cancel", "cancellation", "refund", "delete account", "downgrade",
    "transfer ownership", "change role", "remove seat",
]


def requires_human_confirmation(user_message: str) -> bool:
    """
    Simple keyword check used as a first line of defense to flag messages that
    likely involve a destructive/account-changing request, so the agent can
    proactively say it will draft the request for human review rather than
    attempt to resolve it as a normal query. This is a coarse heuristic, not
    a substitute for the deeper guardrail (these actions aren't even
    implemented as callable tools) -- it just helps the agent respond
    appropriately in conversation.
    """
    lowered = user_message.lower()
    return any(keyword in lowered for keyword in DESTRUCTIVE_ACTION_KEYWORDS)
