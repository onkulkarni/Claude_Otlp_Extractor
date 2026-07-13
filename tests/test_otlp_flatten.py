import json
import os

from extractor.otlp_flatten import attrs_to_dict, coerce, iter_log_records

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return json.load(f)


def test_coerce_string_value():
    assert coerce({"stringValue": "hello"}) == "hello"


def test_coerce_int_value_is_cast_from_numeric_string():
    assert coerce({"intValue": "13"}) == 13
    assert isinstance(coerce({"intValue": "13"}), int)


def test_coerce_double_value():
    assert coerce({"doubleValue": 0.0811173}) == 0.0811173


def test_coerce_bool_value():
    assert coerce({"boolValue": True}) is True


def test_coerce_unknown_variant_returns_none():
    assert coerce({}) is None


def test_numeric_looking_string_values_stay_as_strings():
    # num_success / safe_mode are emitted as stringValue despite being conceptually
    # numeric/boolean -- coerce must not guess, just return the native value.
    assert coerce({"stringValue": "1"}) == "1"
    assert coerce({"stringValue": "false"}) == "false"


def test_attrs_to_dict():
    attrs = [
        {"key": "a", "value": {"stringValue": "x"}},
        {"key": "b", "value": {"intValue": "5"}},
    ]
    assert attrs_to_dict(attrs) == {"a": "x", "b": 5}


def test_iter_log_records_merges_resource_and_record_attrs():
    doc = _load("2026-07-10T13-22-44.088Z_logs_000007.json")
    events = list(iter_log_records(doc, "logs/fixture.json"))
    assert len(events) == 2
    # resource attrs (provenance) merged into every record
    assert events[0]["service.name"] == "claude-code"
    assert events[0]["host.arch"] == "amd64"
    assert events[0]["_source_file"] == "logs/fixture.json"
    assert events[0]["event.name"] == "user_prompt"
    assert events[0]["prompt"] == "can you implement APA-43308"
