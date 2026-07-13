# OTLP Extractor — Phase 1 Handoff

> This document is a self-contained handoff so implementation can start in a fresh session with no prior context. It captures what was investigated, what was decided, and what's still open.

## Related documents

- `plans/2026-07-13-session-consolidation-jira-map-interval.md` — approved, not-yet-implemented plan for a consolidated session report, a session→JIRA resume map, and `--interval` scheduling. Read this before starting related work instead of re-exploring the codebase.
- `extractor/session_costs.py` (+ `tests/test_session_costs.py`) — a post-Phase-1 addition not covered by the design below: sums `Cost USD` per `Session ID` from `records.csv`, deduping on `Request ID`. Run as `python -m extractor.session_costs [--csv-path extracted/records.csv]`. It's the template the above plan's new `consolidate.py`/`jira_map.py` modules follow (read-only report over `records.csv`, no changes to raw output).

## Goal

Greenfield project. Claude Code emits its own OpenTelemetry logs/metrics/traces, which an OTel Collector's file exporter drops as batched JSON files into `received\logs\`, `received\metrics\`, `received\traces\` (sample data already present in this repo). A **later phase** (not this one) will POST one record per LLM call to a server for analytics storage.

**This phase (Phase 1) is extraction only**: read the sample OTLP files, correlate data across files/events, and write one JSON file per record to an output folder — **no DB, no HTTP calls, no server component**. Stack: **Python**.

Target output fields (exact, case-sensitive names requested by the user):

```
Session ID, Session Date, Model, Agent, Skills, Cost USD, Input Tokens,
Output Tokens, Cache Read Tokens, Cache Creation Tokens, JIRA Key, User Email
```

Two of these are not native OTel attributes and must be derived:
- **JIRA Key** — regexed out of the free-text `user_prompt` event, then **carried forward per session** until a new JIRA key appears in a later prompt (explicit user requirement: "until the user uses the new JIRA id, the old JIRA key should be continued to be populated on subsequent records").
- **Agent** — derived from a subagent-launching tool call (see "Unverified" section below — no sample data confirms the exact schema).

Both require session-scoped, stateful correlation, because the OTel exporter batches/flushes on a timer — a single Claude Code session's data is spread across dozens of files, and files can arrive/be read out of order.

## Investigation findings (verified against `received\` sample data)

All of the following was confirmed by directly reading sample files in `received\logs\`, `received\metrics\`, `received\traces\` — not assumed.

1. **Structure**: `resourceLogs → scopeLogs → logRecords`. Each `logRecord` has a flat `attributes` array of `{key, value: {stringValue|intValue|doubleValue|boolValue}}` pairs, plus top-level fields `timeUnixNano`, `traceId`, `spanId`, `body.stringValue` (e.g. `"claude_code.api_request"`). The record's `event.name` attribute (e.g. `"api_request"`) is the actual event type — `body` is just a namespaced echo of it.
   - `intValue` is encoded as a **numeric string** (e.g. `"13"`) — must be `int()`-cast.
   - Some conceptually numeric/boolean fields are actually emitted as `stringValue` (e.g. `num_success: {"stringValue": "1"}`, `safe_mode: {"stringValue": "false"}`). A flatten helper must not assume type consistency per key name — just return whichever native value falls out of the single populated key in the `value` dict, and let callers coerce explicitly if they need a specific type.
   - `resourceLogs[i].resource.attributes` (sibling of `scopeLogs`, not nested inside it) carries host/service info (`host.arch`, `os.type`, `os.version`, `service.name`, `service.version`) — cheap to merge into every record for provenance.

2. **`api_request`** event = the billable unit, one per actual LLM API call. Carries directly: `model` (e.g. `"claude-sonnet-5"`, `"claude-haiku-4-5-20251001"`), `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_creation_tokens` (all `intValue`), `cost_usd` (`doubleValue`), `cost_usd_micros`, `duration_ms`, `request_id` (globally unique per sample data — the natural idempotency key), `speed`, `query_source` (seen: `"main"`, `"auxiliary"`, `"repl_main_thread"`), `effort` (sometimes present, e.g. `"high"`), `prompt.id`, `event.timestamp` (ISO8601), `event.sequence` (monotonic per session), `session.id`, `user.email`. **This one event alone supplies 8 of the 12 target fields directly.**

3. **`user_prompt`** event carries the raw `prompt` text attribute — the only place a JIRA key can come from (e.g. `"can you implement APA-43308"`). Also seen: slash commands (`"/cost"`, `"/clear"`, `"/exit"`, `"/code-explainer:code-explainer can you help me understand the code?"`), `prompt.id`, `prompt_length`. Regex to extract: `[A-Z][A-Z0-9]+-\d+` (standard JIRA issue key pattern).

4. **`skill_activated`** event carries the *real* skill identifier (e.g. `"code-explainer:code-explainer"`) plus `invocation_trigger`, `skill.source`, `plugin.name`, `marketplace.name`, tied to a `prompt.id`.
   - **Gotcha (verified):** `api_request` events *also* sometimes carry their own `skill.name`/`plugin.name` attributes — but the value observed in every single sample was literally the string `"third-party"`. This is a coarse category/classification flag, **not** the real skill name. Confirmed the same on the periodic `metrics` aggregations too. **Do not use `api_request`'s own `skill.name` attribute as the Skills field source — only `skill_activated` is valid.**
   - **Skill scope is per-turn, not carried forward** (verified): after a skill-invoking prompt's turn completes, the next `user_prompt` (e.g. `/cost`) does not re-fire `skill_activated`, and no further `api_request` shares that old `prompt.id`. So: look up Skills by matching `api_request.prompt.id` to a `skill_activated.prompt.id` within the same session — **do not** carry it forward indefinitely the way the JIRA key is carried forward.

5. **`session.id` is not a fixed constant across a batch of files** (verified): running `/clear` mid-session produces a **new** `session.id` in the very next file, even while `prompt.id` still belongs to the pre-clear turn. **All correlation state must be keyed by the `session.id` read fresh off each individual event — never assume one session per processing run or per folder.**

6. **Chronological ordering**: files can arrive/be read out of order across the three subfolders, and a single file (batch flush) can span several seconds of activity — so the **filename timestamp only decides file read order** (cheap pre-sort), never authoritative event order. Use `(session_id, event.sequence)` as the primary sort key (verified `event.sequence` is a monotonic per-session integer, and resets when `session.id` changes), falling back to `event.timestamp` if `event.sequence` is ever missing.

7. **Metrics** (`resourceMetrics`, e.g. `claude_code.cost.usage`, `claude_code.token.usage`, `claude_code.active_time.total`, `claude_code.session.count`) are periodic **delta aggregations**, not per-call — coarser than `api_request` log events and confirmed to carry the same `"third-party"` skill-name quirk. **Traces** (`resourceSpans`, `llm_request` spans) largely mirror `api_request`'s model/token/duration fields via `gen_ai.*` attributes but were not confirmed to carry `cost_usd`, JIRA, or Skill context. **Decision: Phase 1 parses `received\logs\` only.** Metrics/traces parsers can be added later as a cross-check/reconciliation tool if needed, but are not required for the target fields.

8. **`tool_decision`/`tool_result`** events carry a `tool_name` attribute (seen values in samples: `ToolSearch`, `Bash`, `Read`, `Grep`, `AskUserQuestion`, `mcp_tool`) and, at least for `ToolSearch`, a `tool_input` attribute containing a **JSON-encoded string** of the actual call arguments (e.g. `{"query":"select:mcp__claude_ai_Atlassian__getJiraIssue","max_results":3}`), plus `tool_input_size_bytes`.

## UNVERIFIED — flag before trusting in production

**No sample file in `received\` contains a subagent (`Task` tool) invocation.** The plan to extract the **Agent** field is based on Claude Code's known tool schema, not confirmed sample data: subagent launches would appear as a `tool_decision`/`tool_result` event with `tool_name == "Task"`, whose `tool_input` JSON string contains a `subagent_type` field (e.g. `"general-purpose"`, `"Explore"`, `"Plan"`) — the same `tool_input` JSON-string pattern confirmed for `ToolSearch`.

**Action before/during implementation**: capture a real Claude Code session that invokes a subagent (via the Task tool), inspect its `tool_result`/`tool_decision` event to confirm the actual `tool_name` value and the `tool_input` JSON shape, and adjust `extractor/agent.py` accordingly. Until then, the extractor must degrade gracefully — `Agent` field is `None`/empty, never a crash.

## Design

### Module layout (small flat package — pure functions over dicts, no unnecessary class hierarchy)

```
C:\proj\Oltp-Extracter\
  extractor\
    __init__.py
    otlp_flatten.py   # OTLP JSON -> list of flat event dicts (coerce, attrs_to_dict, iter_log_records)
    jira.py           # JIRA_KEY_RE + extract_jira_key(text) -> str | None
    agent.py          # ISOLATED, explicitly-unverified Task/subagent_type extraction
    correlate.py      # stateful single pass: dispatch by event.name, build output records
    state_store.py    # per-session state persisted as .state\<session_id>.json
    writer.py         # output record -> extracted\<session_id>\<ts>_<request_id>.json
    cli.py            # entrypoint: python -m extractor --input received --output extracted [--dry-run]
  tests\
    fixtures\         # trimmed copies of real sample files (see "Fixtures to use" below)
    test_otlp_flatten.py
    test_correlate.py
    test_jira.py
  extracted\          # output (gitignore)
  .state\             # persisted correlation state (gitignore)
```

### Parsing (`otlp_flatten.py`)

```python
def coerce(value_dict: dict):
    # value_dict looks like {"stringValue": "..."} / {"intValue": "13"} / etc.
    if "stringValue" in value_dict: return value_dict["stringValue"]
    if "intValue" in value_dict:    return int(value_dict["intValue"])
    if "doubleValue" in value_dict: return value_dict["doubleValue"]
    if "boolValue" in value_dict:   return bool(value_dict["boolValue"])
    return None  # unknown variant -> None, never raise (forward-compat)

def attrs_to_dict(attributes: list) -> dict:
    return {a["key"]: coerce(a["value"]) for a in attributes}

def iter_log_records(doc: dict, source_file: str):
    for rl in doc.get("resourceLogs", []):
        resource_attrs = attrs_to_dict(rl.get("resource", {}).get("attributes", []))
        for sl in rl.get("scopeLogs", []):
            for lr in sl.get("logRecords", []):
                attrs = {**resource_attrs, **attrs_to_dict(lr.get("attributes", []))}
                yield {"_source_file": source_file, **attrs}
```

### Correlation engine (`correlate.py`)

Single chronological pass over all flattened log events from every file in the input folder, sorted per the ordering rule below. Maintains `dict[session_id -> SessionState]`:

```python
@dataclass
class SessionState:
    last_jira_key: str | None = None
    skill_by_prompt_id: dict = field(default_factory=dict)
    agent_by_prompt_id: dict = field(default_factory=dict)
```

Dispatch by the event's `event.name` attribute:
- **`user_prompt`** → regex-extract JIRA key from `prompt`; if matched (non-empty), overwrite `state.last_jira_key` for that session. Non-matching prompts (slash commands, unrelated text) leave it untouched — this is the carry-forward behavior the user explicitly asked for.
- **`skill_activated`** → `state.skill_by_prompt_id[prompt_id] = skill.name` (plus source/plugin/marketplace if useful for `_meta`).
- **`tool_decision`/`tool_result`** → call `agent.extract_agent(event)`; if non-null, `state.agent_by_prompt_id[prompt_id] = result`.
- **`api_request`** → **emit one output record**:
  - Numeric/model fields straight off this event (`model`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_creation_tokens`, `cost_usd`, `request_id`, `session.id`, `user.email`).
  - `JIRA Key` = `state.last_jira_key` (carried forward indefinitely within the session — no query_source exception; even cheap "auxiliary" calls like title-generation inherit it, since they share the same `prompt.id` as the user's JIRA-mentioning turn).
  - `Skills` = `state.skill_by_prompt_id.get(prompt_id)` — empty/`None` if no match. **Strictly per-turn** — do not carry forward across different `prompt_id`s.
  - `Agent` = `state.agent_by_prompt_id.get(prompt_id)` — defaults `None`.
  - `Session Date` = date portion of **this event's own** `event.timestamp` (not a fixed session-start date — long sessions can span midnight).
- Everything else (`hook_execution_*`, `assistant_response`, `plugin_loaded`, `hook_registered`, `mcp_server_connection`, non-Task `tool_decision`/`tool_result`) is ignored for Phase 1.

### Agent extraction (`agent.py`) — isolated, unverified by design

```python
import json

# UNVERIFIED: no sample in received/ contains a tool_name == "Task" event.
# Inferred from Claude Code's known tool schema. MUST be validated against a
# real subagent-invoking session before being trusted in production.
TASK_TOOL_NAME = "Task"  # <-- adjust here once verified

def extract_agent(event: dict) -> str | None:
    if event.get("tool_name") != TASK_TOOL_NAME:
        return None
    raw = event.get("tool_input")
    if not raw:
        return None
    try:
        return json.loads(raw).get("subagent_type")
    except (json.JSONDecodeError, TypeError, AttributeError):
        return None
```

Never raises. The rest of the pipeline treats a `None` Agent as normal/expected until this is validated.

### Ordering

Sort key: `(session_id, event.sequence)` primary; `event.timestamp` fallback if `event.sequence` is missing. Filename timestamp only decides file **read** order (cheap pre-sort before parsing contents), never authoritative event order. Never compare `event.sequence` across different `session_id`s — it resets per session (confirmed via the `/clear` session-id change).

### State persistence (`state_store.py`)

One small JSON file per session: `.state\<session_id>.json`, holding `last_jira_key`, `skill_by_prompt_id`, `agent_by_prompt_id`. Write atomically (temp file + `os.replace`) after each run, so a later invocation (as the collector drops new files over time) resumes correctly. Because `session.id` is read fresh per event, a `/clear`-triggered new session simply gets its own empty state file — no special-casing needed.

### Output (`writer.py`)

One JSON file per emitted `api_request` record:
```
extracted\<session_id>\<event_timestamp_iso_compact>_<request_id>.json
```
`request_id` is globally unique and doubles as the idempotency key: before writing, check whether a file for that `request_id` already exists under `extracted\<session_id>\`; skip if so. Idempotency is derived live from the output folder contents — no separate "already processed" tracking needed in state. Re-running the extractor over the same or overlapping input files is always safe and produces no duplicates.

**Record schema** (12 required fields + a `_meta` block for provenance/debugging — cheap to keep, trivial to strip later if the Phase 2 API consumer doesn't want it):

```json
{
  "Session ID": "7a577f2e-f56d-4cb0-8d18-46bcddd72287",
  "Session Date": "2026-07-10",
  "Model": "claude-sonnet-5",
  "Agent": null,
  "Skills": "code-explainer:code-explainer",
  "Cost USD": 0.0811173,
  "Input Tokens": 10870,
  "Output Tokens": 255,
  "Cache Read Tokens": 32761,
  "Cache Creation Tokens": 5809,
  "JIRA Key": "APA-43308",
  "User Email": "onkar.kulkarni@nice.com",
  "_meta": {
    "request_id": "req_011CctSxa2TV6mEeCaDb5cSk",
    "prompt_id": "1095e257-4c52-4df6-9d73-e22b247060ac",
    "query_source": "repl_main_thread",
    "source_file": "logs/2026-07-10T13-22-49.050Z_logs_000011.json"
  }
}
```

### CLI (`cli.py`)

```
python -m extractor --input received --output extracted [--dry-run]
```
`--dry-run` prints one line per would-be-emitted record (session id, request_id, model, cost, JIRA key, skill, agent) instead of writing files, for quick eyeballing before trusting file output.

## Fixtures to use for tests

Copy these real sample files (trimmed if needed) into `tests\fixtures\`:
- `received\logs\2026-07-10T13-22-44.088Z_logs_000007.json` — `user_prompt` with JIRA key `APA-43308` (`prompt.id = 1095e257-4c52-4df6-9d73-e22b247060ac`).
- `received\logs\2026-07-10T13-22-46.801Z_logs_000009.json` and `received\logs\2026-07-10T13-22-49.050Z_logs_000011.json` — subsequent `api_request` events sharing that same `prompt.id` (verified) — both should inherit the JIRA key, including the cheap `auxiliary`-source title-gen call.
- `received\logs\2026-07-10T13-26-00.510Z_logs_000146.json` (`skill_activated`, `skill.name = "code-explainer:code-explainer"`, `prompt.id = c009fe2c-...`) and `received\logs\2026-07-10T13-26-04.522Z_logs_000148.json` (`api_request` under that same `prompt.id`) — the skill-attribution pair.
- `received\logs\2026-07-10T13-22-50.381Z_logs_000014.json` — contains a `tool_result` with a real `tool_input` JSON string (`ToolSearch`), useful for testing the flatten/agent-parsing helper's JSON-string handling even before a real `Task`-tool sample exists.
- `received\logs\2026-07-10T13-27-04.014Z_logs_000173.json` — the file immediately after `/clear`, showing the new `session.id` (`39e26407-550f-4bde-92d0-7d99591c5655`) appearing while `prompt.id` still belongs to the pre-clear turn — use this to test that state is correctly keyed by fresh `session.id`, not assumed constant.

## Verification checklist

1. **Unit tests** against the fixtures above — cover: JIRA regex extraction/non-match, JIRA carry-forward across multiple `api_request`s under one `prompt.id` (including the auxiliary title-gen call), skill attribution strictly scoped to matching `prompt.id` (and absence of it for other prompt ids), session-state correctly re-keyed after a `/clear`-style `session.id` change, `otlp_flatten.coerce` handling all four value variants plus the "numeric-looking stringValue" quirk (`num_success`, `safe_mode`).
2. **Dry-run against the real `received\` folder**: `python -m extractor --input received --output extracted --dry-run` — eyeball that every record has non-null `Model`/`Cost USD`, that **all** records carry `JIRA Key = "APA-43308"` (the only key ever mentioned in this sample set, never overwritten), and that only records under `prompt_id = c009fe2c-...` show `Skills = "code-explainer:code-explainer"` while all others are null/empty.
3. **Full run**: drop `--dry-run`; confirm files land under `extracted\<session_id>\...json` matching the schema above; cross-check the emitted record count against a quick grep count of `api_request` events in `received\logs\`.
4. **Idempotency check**: run the CLI twice over the same `received\` folder; assert the second run writes zero new files and the output file count is unchanged.

## Explicitly out of scope for this phase

- No database, no server, no HTTP client/API calls (that's Phase 2 — this extractor's per-record JSON files are designed to become individual API request bodies later, hence one-file-per-record output).
- No handling of `received\metrics\` or `received\traces\` in the main pipeline (parsers can be added later purely as a cross-check tool if needed).
- No multi-machine/multi-user session merging (all current sample data is single-host).

## Phase 2 note (for whenever that phase starts)

The user (onkar.kulkarni@nice.com) confirmed during planning that **this team does not own the server/API that will ultimately receive these records** — Phase 2 will only *invoke* an endpoint someone else owns/builds. That means before Phase 2 work can start, someone needs to obtain from that server's owner: the endpoint URL, request schema/contract (does it want exactly the 12-field schema above, or something else — e.g. should `_meta` be stripped?), auth mechanism, and batching/rate-limit expectations. This extractor's one-file-per-record output was deliberately designed to make that hand-off easy (each file is already a self-contained candidate request body), but the actual contract is still unknown as of this writing.
