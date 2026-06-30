"""
Unit tests for tools.py, the tool functions the agent can call. These
test the underlying logic directly (not through the LLM/agent loop), which
is the right level for unit tests: fast, deterministic, no API calls needed.
End-to-end behavior (does the AGENT choose the right tool) is covered
separately by the evaluation harness in evaluation/, which does need the
real model.
"""

import tools


# ---------------------------------------------------------------------------
# lookup_customer
# ---------------------------------------------------------------------------

def test_lookup_customer_found(test_db):
    result = tools.lookup_customer("owner@testco.com")
    assert result["found"] is True
    assert result["customer"]["name"] == "Test Owner"
    assert result["customer"]["role"] == "owner"


def test_lookup_customer_not_found(test_db):
    result = tools.lookup_customer("nobody@nowhere.com")
    assert result["found"] is False
    assert "message" in result


# ---------------------------------------------------------------------------
# get_account_status -- must NOT include billing fields (least-privilege scope)
# ---------------------------------------------------------------------------

def test_get_account_status_found(test_db):
    result = tools.get_account_status(1)
    assert result["found"] is True
    assert result["account"]["status"] == "active"


def test_get_account_status_excludes_billing_fields(test_db):
    """This is the actual guardrail behavior, not just a data shape detail --
    get_account_status must never leak mrr/plan_tier, even though that data
    exists on the same accounts table row."""
    result = tools.get_account_status(1)
    assert "mrr" not in result["account"]
    assert "plan_tier" not in result["account"]
    assert "renewal_date" not in result["account"]


def test_get_account_status_not_found(test_db):
    result = tools.get_account_status(99999)
    assert result["found"] is False


# ---------------------------------------------------------------------------
# get_billing_details
# ---------------------------------------------------------------------------

def test_get_billing_details_found(test_db):
    result = tools.get_billing_details(1)
    assert result["found"] is True
    assert result["billing"]["mrr"] == 159.0
    assert result["billing"]["plan_tier"] == "growth"


def test_get_billing_details_excludes_status(test_db):
    """Mirror check of the above -- billing details shouldn't carry account
    status, keeping the two tools' scopes cleanly separated."""
    result = tools.get_billing_details(1)
    assert "status" not in result["billing"]
    assert "company_name" not in result["billing"]


def test_get_billing_details_not_found(test_db):
    result = tools.get_billing_details(99999)
    assert result["found"] is False


# ---------------------------------------------------------------------------
# list_recent_invoices
# ---------------------------------------------------------------------------

def test_list_recent_invoices_found(test_db):
    result = tools.list_recent_invoices(1)
    assert result["found"] is True
    assert len(result["invoices"]) == 2


def test_list_recent_invoices_sorted_newest_first(test_db):
    result = tools.list_recent_invoices(1)
    dates = [inv["date"] for inv in result["invoices"]]
    assert dates == sorted(dates, reverse=True)


def test_list_recent_invoices_respects_limit(test_db):
    result = tools.list_recent_invoices(1, limit=1)
    assert len(result["invoices"]) == 1


def test_list_recent_invoices_no_invoices(test_db):
    # Account 2 (locked) has no seeded invoices
    result = tools.list_recent_invoices(2)
    assert result["found"] is False


# ---------------------------------------------------------------------------
# search_knowledge_base
# ---------------------------------------------------------------------------

def test_search_knowledge_base_finds_match(test_db):
    result = tools.search_knowledge_base("test article")
    assert result["found"] is True
    assert len(result["articles"]) >= 1


def test_search_knowledge_base_no_match(test_db):
    result = tools.search_knowledge_base("completely unrelated nonexistent topic xyz")
    assert result["found"] is False


def test_search_knowledge_base_category_filter(test_db):
    result = tools.search_knowledge_base("test", category="billing")
    assert result["found"] is True
    result_wrong_category = tools.search_knowledge_base("test", category="routing")
    assert result_wrong_category["found"] is False


def test_search_knowledge_base_strips_stopwords(test_db):
    """Regression test for the real bug found during manual testing earlier
    in this project: a query like 'what is the test article about' should
    still match, even though most of those words are stopwords."""
    result = tools.search_knowledge_base("what is the test article about")
    assert result["found"] is True


# ---------------------------------------------------------------------------
# check_ticket_status
# ---------------------------------------------------------------------------

def test_check_ticket_status_found(test_db):
    result = tools.check_ticket_status(1)
    assert result["found"] is True
    assert result["ticket"]["status"] == "resolved"


def test_check_ticket_status_not_found_does_not_fabricate(test_db):
    """Regression test mirroring the real evaluation scenario from earlier --
    a nonexistent ticket must come back as not-found, never with an invented status."""
    result = tools.check_ticket_status(99999)
    assert result["found"] is False
    assert "ticket" not in result


# ---------------------------------------------------------------------------
# create_ticket
# ---------------------------------------------------------------------------

def test_create_ticket_success(test_db):
    result = tools.create_ticket(
        account_id=1, created_by_customer_id=1, category="billing",
        priority="medium", summary="Test ticket creation",
    )
    assert result["success"] is True
    assert "ticket_id" in result

    # Confirm it's actually retrievable afterward
    check = tools.check_ticket_status(result["ticket_id"])
    assert check["found"] is True
    assert check["ticket"]["status"] == "open"


def test_create_ticket_invalid_category(test_db):
    result = tools.create_ticket(
        account_id=1, created_by_customer_id=1, category="not_a_real_category",
        priority="medium", summary="Test",
    )
    assert result["success"] is False


def test_create_ticket_invalid_priority(test_db):
    result = tools.create_ticket(
        account_id=1, created_by_customer_id=1, category="billing",
        priority="not_a_real_priority", summary="Test",
    )
    assert result["success"] is False


def test_create_ticket_nonexistent_account(test_db):
    result = tools.create_ticket(
        account_id=99999, created_by_customer_id=1, category="billing",
        priority="medium", summary="Test",
    )
    assert result["success"] is False


def test_create_ticket_nonexistent_customer(test_db):
    result = tools.create_ticket(
        account_id=1, created_by_customer_id=99999, category="billing",
        priority="medium", summary="Test",
    )
    assert result["success"] is False


# ---------------------------------------------------------------------------
# Tool registry consistency -- catches the exact bug found earlier in this
# project, where a schema edit accidentally broke the dict structure and a
# tool went missing from one of the two registries without the other.
# ---------------------------------------------------------------------------

def test_every_schema_has_a_matching_function():
    schema_names = {s["name"] for s in tools.TOOL_SCHEMAS}
    function_names = set(tools.TOOL_FUNCTIONS.keys())
    assert schema_names == function_names


def test_tool_count_is_seven():
    """Documents the expected tool count -- if this fails, a tool was added
    or removed and the test suite (and resume claims) should be reviewed."""
    assert len(tools.TOOL_SCHEMAS) == 7
    assert len(tools.TOOL_FUNCTIONS) == 7
