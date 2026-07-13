from extractor.jira import extract_jira_key


def test_extracts_jira_key_from_prompt():
    assert extract_jira_key("can you implement APA-43308") == "APA-43308"


def test_no_match_on_slash_command():
    assert extract_jira_key("/cost") is None


def test_no_match_on_unrelated_text():
    assert extract_jira_key("please refactor the login module") is None


def test_no_match_on_empty_or_none():
    assert extract_jira_key("") is None
    assert extract_jira_key(None) is None


def test_extracts_first_match_when_multiple_present():
    assert extract_jira_key("see APA-1 and also APA-2") == "APA-1"
