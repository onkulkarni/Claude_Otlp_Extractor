import json
import os
import shutil

from extractor import correlate, state_store
from extractor.otlp_flatten import iter_log_records

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")

JIRA_SESSION = "7a577f2e-f56d-4cb0-8d18-46bcddd72287"
JIRA_PROMPT_ID = "1095e257-4c52-4df6-9d73-e22b247060ac"
SKILL_PROMPT_ID = "c009fe2c-b93c-43a7-9a60-68541f49a3f6"
POST_CLEAR_SESSION = "39e26407-550f-4bde-92d0-7d99591c5655"

JIRA_FIXTURES = [
    "2026-07-10T13-22-44.088Z_logs_000007.json",  # user_prompt: "can you implement APA-43308"
    "2026-07-10T13-22-46.801Z_logs_000009.json",  # api_request, query_source=generate_session_title (auxiliary)
    "2026-07-10T13-22-49.050Z_logs_000011.json",  # api_request, query_source=repl_main_thread
]
SKILL_FIXTURES = [
    "2026-07-10T13-26-00.510Z_logs_000146.json",  # skill_activated: code-explainer:code-explainer
    "2026-07-10T13-26-04.522Z_logs_000148.json",  # api_request under same prompt_id
]
POST_CLEAR_FIXTURE = "2026-07-10T13-27-04.014Z_logs_000173.json"


def _load_events(filenames):
    events = []
    for name in filenames:
        with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
            doc = json.load(f)
        events.extend(iter_log_records(doc, f"logs/{name}"))
    return events


def test_jira_key_carries_forward_to_all_api_requests_under_same_prompt(tmp_path):
    events = _load_events(JIRA_FIXTURES)
    records = correlate.process_events(events, str(tmp_path))

    assert len(records) == 2  # the two api_request events (auxiliary + main)
    for record in records:
        assert record["JIRA Key"] == "APA-43308"
    # the cheap auxiliary title-gen call inherits the key too
    query_sources = {r["_meta"]["query_source"] for r in records}
    assert query_sources == {"generate_session_title", "repl_main_thread"}


def test_skill_scoped_strictly_to_matching_prompt_id(tmp_path):
    events = _load_events(JIRA_FIXTURES + SKILL_FIXTURES)
    records = correlate.process_events(events, str(tmp_path))

    by_prompt = {r["_meta"]["prompt_id"]: r for r in records}
    assert by_prompt[SKILL_PROMPT_ID]["Skills"] == "code-explainer:code-explainer"
    # records under the unrelated JIRA prompt_id must NOT pick up the skill
    for record in records:
        if record["_meta"]["prompt_id"] == JIRA_PROMPT_ID:
            assert record["Skills"] is None


def test_session_state_rekeyed_after_clear(tmp_path):
    events = _load_events(JIRA_FIXTURES + [POST_CLEAR_FIXTURE])
    correlate.process_events(events, str(tmp_path))

    old_state = state_store.load(str(tmp_path), JIRA_SESSION)
    new_state = state_store.load(str(tmp_path), POST_CLEAR_SESSION)

    assert old_state.last_jira_key == "APA-43308"
    # fresh session.id after /clear must not inherit the old session's state
    assert new_state.last_jira_key is None
    assert new_state.skill_by_prompt_id == {}


def test_state_persists_and_reloads_across_runs(tmp_path):
    events = _load_events(JIRA_FIXTURES)
    correlate.process_events(events, str(tmp_path))

    reloaded = state_store.load(str(tmp_path), JIRA_SESSION)
    assert reloaded.last_jira_key == "APA-43308"


def test_jira_fallback_seeds_session_with_lost_state(tmp_path):
    # SKILL_FIXTURES alone has no JIRA-key-bearing user_prompt for this session
    # (its user_prompt is the unrelated "/code-explainer..." slash command) --
    # simulates a session resumed after .state/ was lost/reset.
    events = _load_events(SKILL_FIXTURES)
    records = correlate.process_events(events, str(tmp_path), jira_fallback={JIRA_SESSION: "APA-1"})

    assert len(records) == 1
    assert records[0]["JIRA Key"] == "APA-1"


def test_jira_fallback_does_not_override_state_that_still_has_a_key(tmp_path):
    events = _load_events(JIRA_FIXTURES)
    records = correlate.process_events(events, str(tmp_path), jira_fallback={JIRA_SESSION: "APA-99999"})

    for record in records:
        assert record["JIRA Key"] == "APA-43308"  # in-run user_prompt wins over fallback


def test_run_end_to_end_over_fixture_folder(tmp_path):
    input_dir = tmp_path / "received"
    logs_dir = input_dir / "logs"
    logs_dir.mkdir(parents=True)
    for name in JIRA_FIXTURES + SKILL_FIXTURES:
        shutil.copy(os.path.join(FIXTURES, name), logs_dir / name)

    state_dir = tmp_path / ".state"
    records = correlate.run(str(input_dir), str(state_dir))

    assert len(records) == 3
    assert all(r["JIRA Key"] == "APA-43308" for r in records)
    skills = [r["Skills"] for r in records]
    assert skills.count("code-explainer:code-explainer") == 1
    assert skills.count(None) == 2
