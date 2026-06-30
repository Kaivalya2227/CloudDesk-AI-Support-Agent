"""Quick smoke test to validate the test_db fixture itself works correctly."""

def test_fixture_creates_isolated_db(test_db):
    import tools
    result = tools.get_account_status(1)
    assert result["found"] is True
    assert result["account"]["status"] == "active"
    assert result["account"]["company_name"] == "Test Co Active"


def test_fixture_db_is_not_the_real_db(test_db):
    assert test_db != "clouddesk.db"
    assert "clouddesk.db" not in test_db
