"""
Unit tests for guardrails.py, identity verification, throttling, and
access-control logic. This is the most important file to have solid test
coverage on, since it's the security-relevant code: bugs here were found
manually during development (the throttle bypass), and regression tests
exist specifically so those bugs can never silently come back.
"""

import pytest
import guardrails


# ---------------------------------------------------------------------------
# verify_identity -- core verification logic
# ---------------------------------------------------------------------------

def test_verify_identity_success(test_db):
    result = guardrails.verify_identity("owner@testco.com", 1)
    assert result["name"] == "Test Owner"
    assert result["role"] == "owner"


def test_verify_identity_wrong_account_id_fails(test_db):
    """The actual vulnerability this project found: a real email paired with
    the WRONG account_id must be rejected, not just a fake email."""
    with pytest.raises(guardrails.VerificationError):
        guardrails.verify_identity("owner@testco.com", 99999)


def test_verify_identity_fake_email_fails(test_db):
    with pytest.raises(guardrails.VerificationError):
        guardrails.verify_identity("fake@nowhere.com", 1)


def test_verify_identity_error_message_is_identical_for_both_failure_modes(test_db):
    """Security detail worth a dedicated test: wrong-account-id and fake-email
    must produce the EXACT same error message, so neither leaks information
    about which part of the credentials was wrong."""
    try:
        guardrails.verify_identity("owner@testco.com", 99999)
    except guardrails.VerificationError as e:
        wrong_account_message = str(e)

    try:
        guardrails.verify_identity("fake@nowhere.com", 1)
    except guardrails.VerificationError as e:
        fake_email_message = str(e)

    assert wrong_account_message == fake_email_message


# ---------------------------------------------------------------------------
# Per-email throttling
# ---------------------------------------------------------------------------

def test_throttle_kicks_in_after_max_attempts(test_db):
    """Regression test for the core throttling behavior: after MAX_ATTEMPTS
    failures on the SAME email, the next attempt must be throttled, not
    given a normal VerificationError."""
    email = "repeated.fail@nowhere.com"
    for _ in range(guardrails.MAX_ATTEMPTS):
        with pytest.raises(guardrails.VerificationError):
            guardrails.verify_identity(email, 99999)

    # The next attempt should now be throttled, not just another VerificationError
    with pytest.raises(guardrails.ThrottledError):
        guardrails.verify_identity(email, 99999)


def test_throttle_does_not_affect_different_email(test_db):
    """Regression test confirming throttling is scoped per-email, not global --
    a different, legitimate email must still verify successfully while
    another email is actively throttled."""
    throttled_email = "attacker@nowhere.com"
    for _ in range(guardrails.MAX_ATTEMPTS):
        with pytest.raises(guardrails.VerificationError):
            guardrails.verify_identity(throttled_email, 99999)
    with pytest.raises(guardrails.ThrottledError):
        guardrails.verify_identity(throttled_email, 99999)

    # A different, legitimate user should be completely unaffected
    result = guardrails.verify_identity("owner@testco.com", 1)
    assert result["role"] == "owner"


def test_throttle_never_locks_the_real_account(test_db):
    """Direct regression test for the documented design decision: failed
    verification attempts must NEVER change the underlying account's status,
    even after the email is fully throttled. Locking the real account would
    let an attacker deny service to a legitimate customer."""
    email = "owner@testco.com"  # a REAL email, paired with a wrong account_id
    for _ in range(guardrails.MAX_ATTEMPTS):
        with pytest.raises(guardrails.VerificationError):
            guardrails.verify_identity(email, 99999)

    # Confirm account 1 (which this email actually belongs to) is still active
    import tools
    status = tools.get_account_status(1)
    assert status["account"]["status"] == "active"


def test_successful_verification_resets_throttle_count(test_db):
    """A success should reset the failure count, same as real lockout systems --
    confirmed by failing twice (under the threshold), succeeding, then
    failing twice more should NOT trigger throttling."""
    email = "owner@testco.com"

    # Fail twice with wrong account_id (under MAX_ATTEMPTS of 3)
    for _ in range(2):
        with pytest.raises(guardrails.VerificationError):
            guardrails.verify_identity(email, 99999)

    # Now succeed
    guardrails.verify_identity(email, 1)

    # Fail twice more -- should NOT be throttled yet, since the prior success reset the count
    for _ in range(2):
        with pytest.raises(guardrails.VerificationError):
            guardrails.verify_identity(email, 99999)

    # This should still be a normal VerificationError, not ThrottledError
    with pytest.raises(guardrails.VerificationError):
        guardrails.verify_identity(email, 99999)


# ---------------------------------------------------------------------------
# Role-based billing field filtering
# ---------------------------------------------------------------------------

def test_filter_billing_fields_owner_sees_everything(test_db):
    billing = {"account_id": 1, "plan_tier": "growth", "mrr": 159.0, "renewal_date": "2027-01-01"}
    filtered = guardrails.filter_billing_fields(billing, "owner")
    assert filtered["mrr"] == 159.0


def test_filter_billing_fields_member_loses_mrr(test_db):
    billing = {"account_id": 1, "plan_tier": "growth", "mrr": 159.0, "renewal_date": "2027-01-01"}
    filtered = guardrails.filter_billing_fields(billing, "member")
    assert "mrr" not in filtered
    assert filtered["plan_tier"] == "growth"  # other fields still present


def test_filter_billing_fields_unknown_role_defaults_to_most_restrictive(test_db):
    """If an unexpected role string ever shows up, the filter should fail
    safe (restrict), not fail open (expose everything)."""
    billing = {"account_id": 1, "plan_tier": "growth", "mrr": 159.0}
    filtered = guardrails.filter_billing_fields(billing, "some_unexpected_role")
    assert "mrr" not in filtered


# ---------------------------------------------------------------------------
# Role-based invoice access (all-or-nothing, unlike the field filter above)
# ---------------------------------------------------------------------------

def test_invoice_access_allowed_for_owner_and_admin(test_db):
    assert guardrails.invoice_access_allowed("owner") is True
    assert guardrails.invoice_access_allowed("admin") is True


def test_invoice_access_blocked_for_member(test_db):
    assert guardrails.invoice_access_allowed("member") is False


# ---------------------------------------------------------------------------
# Account-status-based billing block
# ---------------------------------------------------------------------------

def test_billing_blocked_for_locked_status(test_db):
    assert guardrails.billing_access_blocked("locked") is True


def test_billing_blocked_for_suspended_status(test_db):
    assert guardrails.billing_access_blocked("suspended") is True


def test_billing_allowed_for_active_status(test_db):
    assert guardrails.billing_access_blocked("active") is False


# ---------------------------------------------------------------------------
# Destructive-action keyword detection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("message", [
    "I want to cancel my account",
    "Can you give me a refund",
    "How do I downgrade my plan",
    "Please transfer ownership to my colleague",
    "I'd like to remove a seat",
])
def test_requires_human_confirmation_detects_destructive_requests(message):
    assert guardrails.requires_human_confirmation(message) is True


@pytest.mark.parametrize("message", [
    "What is my account status",
    "Can you check my recent invoices",
    "What plan tiers do you offer",
])
def test_requires_human_confirmation_ignores_normal_requests(message):
    assert guardrails.requires_human_confirmation(message) is False
