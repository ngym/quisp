from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict
import json

from .models import RawLogLine, parse_time_to_iso, normalize_event


@dataclass(frozen=True)
class ParsedLine:
    raw: str
    raw_log_line: RawLogLine


def parse_raw_line(raw_line: str) -> RawLogLine:
    text = raw_line.strip()
    if not text:
        return RawLogLine(raw=raw_line, parse_error="empty_line")

    try:
        payload: Dict[str, Any] = json.loads(text)
    except Exception as exc:  # pragma: no cover - defensive for malformed logs
        return RawLogLine(raw=raw_line, parse_error=f"invalid_json: {exc}")

    if not isinstance(payload, dict):
        return RawLogLine(raw=raw_line, parse_error="non_object_payload")

    return RawLogLine(raw=raw_line, parsed=payload)


def parse_log_event(raw_line: str, run_id: str, cursor: int):
    raw_log_line = parse_raw_line(raw_line)
    return normalize_event(raw_log_line, run_id=run_id, cursor=cursor)


def is_event_with_payload(raw_line: RawLogLine) -> bool:
    return raw_line.parsed is not None and "event_payload" in raw_line.parsed


def _safe_event_type(raw: Dict[str, Any], default: str = "unknown") -> str:
    candidate = raw.get("event_type") if isinstance(raw, dict) else None
    if isinstance(candidate, str) and candidate.strip():
        return candidate.strip()
    return default


def _safe_ts(raw: Dict[str, Any]) -> str:
    if not isinstance(raw, dict):
        return parse_time_to_iso(None)
    ts = raw.get("ts") or raw.get("timestamp") or raw.get("time")
    return parse_time_to_iso(ts)
