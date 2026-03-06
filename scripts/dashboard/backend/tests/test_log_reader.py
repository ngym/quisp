from __future__ import annotations

import json
from scripts.dashboard.backend.app import log_reader


def test_parse_with_structured_payload() -> None:
    line = '{"simtime": 1.25, "event_type": "link", "address": "3", "event_payload": {"msg": "ok"}}\n'
    event = log_reader.parse_log_event(line, run_id="run.log", cursor=10)

    assert event.event_type == "link"
    assert event.run_id == "run.log"
    assert event.cursor == 10
    assert event.sim_time == 1.25
    assert event.source == "3"
    assert event.payload["msg"] == "ok"


def test_parse_with_string_payload() -> None:
    inner = json.dumps({"event_type": "nested", "value": 42})
    line = '{"simtime": 0.5, "event_payload": "' + inner.replace('"', '\\"') + '"}'
    event = log_reader.parse_log_event(line, run_id="run.log", cursor=8)

    assert event.event_type == "unknown"
    assert event.sim_time == 0.5
    assert event.payload["event_type"] == "nested"
    assert event.payload["value"] == 42


def test_parse_invalid_json_keeps_parse_error() -> None:
    event = log_reader.parse_log_event("{this is not json}\n", run_id="run.log", cursor=0)

    assert event.event_type == "unknown"
    assert "parse_error" in event.payload
    assert isinstance(event.cursor, int)
