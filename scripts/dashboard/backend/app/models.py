from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional, Union
import json
import math
from pydantic import BaseModel, Field, model_validator


def _first_non_empty(*values: Any) -> Optional[str]:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            v = value.strip()
            if v:
                return v
            continue
        if value != "":
            return str(value)
    return None


def parse_time_to_iso(raw: Any) -> str:
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(float(raw), tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            pass
    if isinstance(raw, str):
        if raw:
            return raw
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_event_payload(raw_payload: Any) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Return (payload, parse_meta) from event_payload with compatibility handling.

    event_payload may be:
    - a dict (already structured)
    - a stringified JSON object
    - non-json value / malformed JSON string
    """
    if isinstance(raw_payload, dict):
        return dict(raw_payload), {}
    if isinstance(raw_payload, str):
        text = raw_payload.strip()
        if not text:
            return {}, {"event_payload_empty": True}
        try:
            loaded = json.loads(text)
            if isinstance(loaded, dict):
                return dict(loaded), {}
            if isinstance(loaded, list):
                return {"value": loaded}, {"event_payload_was_json_list": True}
            return {"event_payload_value": loaded}, {"event_payload_scalar": True}
        except json.JSONDecodeError as exc:
            maybe_object = text
            if not text.startswith("{") and not text.startswith("[") and '":' in text:
                maybe_object = "{" + text + "}"
                try:
                    loaded = json.loads(maybe_object)
                    if isinstance(loaded, dict):
                        return dict(loaded), {"event_payload_wrapped_object": True}
                except json.JSONDecodeError:
                    pass
            return {"raw_message": text}, {"event_payload_parse_error": str(exc)}
    if raw_payload is None:
        return {}, {}
    return {"value": raw_payload}, {"event_payload_scalar": True}


@dataclass(frozen=True)
class RawLogLine:
    raw: str
    parsed: Optional[Dict[str, Any]] = None
    parse_error: Optional[str] = None


@dataclass(frozen=True)
class DashboardEvent:
    event_type: str
    ts: str
    sim_time: float
    run_id: str
    source: str
    payload: Dict[str, Any]
    cursor: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type,
            "ts": self.ts,
            "sim_time": self.sim_time,
            "run_id": self.run_id,
            "source": self.source,
            "payload": self.payload,
            **({"cursor": self.cursor} if self.cursor is not None else {}),
        }


@dataclass(frozen=True)
class TopologyNode:
    id: str
    label: str
    x: Optional[float] = None
    y: Optional[float] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TopologyEdge:
    src: str
    dst: str
    weight: Optional[float] = None
    kind: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TopologySnapshot:
    nodes: list[TopologyNode]
    edges: list[TopologyEdge]
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class FrameWindow:
    window_id: str
    frame_index: int
    events: list[DashboardEvent]
    state_delta: Dict[str, Any]
    next_cursor: int
    has_more: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "window_id": self.window_id,
            "frame_index": self.frame_index,
            "events": [event.to_dict() for event in self.events],
            "state_delta": self.state_delta,
            "next_cursor": self.next_cursor,
            "has_more": self.has_more,
        }


@dataclass(frozen=True)
class RunInfo:
    run_id: str
    path: str
    event_count: int
    last_sim_time: float
    last_event_type: Optional[str]
    updated_at: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def normalize_event(raw: RawLogLine, run_id: str, cursor: int) -> DashboardEvent:
    parsed = raw.parsed if raw.parsed is not None else {}

    event_type = str(
        _first_non_empty(
            parsed.get("event_type"),
            parsed.get("type"),
            parsed.get("event"),
            "unknown"
        )
    )
    sim_time = _coerce_float(
        _first_non_empty(parsed.get("simtime"), parsed.get("sim_time"), parsed.get("time")),
        default=0.0,
    )
    ts = parse_time_to_iso(_first_non_empty(parsed.get("ts"), parsed.get("timestamp")))
    source = _first_non_empty(parsed.get("address"), parsed.get("source"), parsed.get("node"), parsed.get("node_id"), parsed.get("module"), "") or ""

    payload_from_key, payload_meta = parse_event_payload(parsed.get("event_payload"))
    payload: Dict[str, Any] = {}

    for k, v in parsed.items():
        if k in {"event_payload", "simtime", "sim_time", "time", "ts", "timestamp", "event_type", "type", "event", "address", "source", "node", "node_id", "module"}:
            continue
        payload[k] = v

    if source:
        payload.setdefault("source", source)
    payload.update(payload_meta)
    payload.update(payload_from_key)
    if "event_type" not in payload:
        payload["event_type"] = event_type

    # Attach raw for debugging and compatibility if parser metadata exists.
    if raw.parse_error:
        payload["parse_error"] = raw.parse_error

    return DashboardEvent(
        event_type=event_type,
        ts=ts,
        sim_time=sim_time,
        run_id=run_id,
        source=source,
        payload=payload,
        cursor=cursor,
    )


def flatten_event_types(types: Optional[str]) -> Optional[list[str]]:
    if not types:
        return None
    normalized = [t.strip() for t in types.split(",") if t.strip()]
    if not normalized:
        return None
    return normalized


def parse_focused_node(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text.startswith("N"):
        text = text[1:]
    if not text.replace("_", "").replace("-", "").isalnum():
        return None
    return text


def parse_coordinate(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if math.isfinite(value):
        return value
    return None


class SimRunStatus(str, Enum):
    QUEUED = "queued"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FINISHED = "finished"
    FAILED = "failed"
    TERMINATED = "terminated"


class OverridePair(BaseModel):
    key: str
    value: str


class SimTemplate(BaseModel):
    template_id: str
    path: str
    available_configs: list[str]
    description: Optional[str] = None
    default_workdir: str
    last_modified: str


class SimRunStartRequest(BaseModel):
    template_id: Optional[str] = None
    config_name: Optional[str] = None
    run_name: Optional[str] = None
    workdir: Optional[str] = None
    num_runs: int = Field(default=1, ge=1, le=10000)
    seed_set: Optional[int] = Field(default=None, ge=0, le=999999999)
    sim_time_limit: Optional[float] = Field(default=None, ge=0)
    experiment_profile_id: Optional[str] = None
    parameter_values: Dict[str, Any] = Field(default_factory=dict)
    requested_metrics: list[str] = Field(default_factory=list)
    tags: Dict[str, str] = Field(default_factory=dict)
    overrides: Union[dict[str, Any], list[OverridePair], list[dict[str, Any]], None] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _normalize_overrides(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        raw = values.get("overrides", {})
        if raw is None:
            values["overrides"] = {}
            return values

        if isinstance(raw, dict):
            normalized = {str(key): str(value) for key, value in raw.items()}
            values["overrides"] = normalized
            return values

        if isinstance(raw, (list, tuple)):
            normalized: Dict[str, str] = {}
            for item in raw:
                if isinstance(item, dict):
                    key = item.get("key")
                    value = item.get("value")
                    if key is not None:
                        normalized[str(key)] = str(value if value is not None else "")
            values["overrides"] = normalized
            return values

        raise TypeError("overrides must be a mapping or list of {key,value}")

    @model_validator(mode="after")
    def _validate_launcher_target(self) -> "SimRunStartRequest":
        template_id = self.template_id
        config_name = self.config_name
        profile_id = self.experiment_profile_id
        if profile_id:
            return self
        if template_id and config_name:
            return self
        raise ValueError("template_id/config_name or experiment_profile_id is required")


class SimRunStartResponse(BaseModel):
    run_id: str
    status: SimRunStatus
    log_path: str
    dashboard_run_id: str
    display_name: Optional[str] = None
    experiment_profile_id: Optional[str] = None


class SimRunArchiveRequest(BaseModel):
    run_ids: list[str] = Field(default_factory=list)
    completed_only: bool = False
    archived: bool = True


class SimRunDeleteRequest(BaseModel):
    run_ids: list[str] = Field(default_factory=list)
    delete_all_archived: bool = False


class SimRunInfo(BaseModel):
    run_id: str
    display_name: Optional[str] = None
    experiment_display_name: Optional[str] = None
    status: SimRunStatus
    status_message: Optional[str]
    template_id: str
    config_name: str
    run_name: Optional[str]
    pid: Optional[int]
    workdir: str
    log_path: str
    created_at: str
    started_at: Optional[str]
    finished_at: Optional[str]
    exit_code: Optional[int]
    num_runs: int
    seed_set: Optional[int]
    sim_time_limit: Optional[float]
    command: list[str]
    stdout_tail: list[str]
    stderr_tail: list[str]
    dashboard_run_id: str
    output_lines: int
    timeout: Optional[float] = None
    event_count: Optional[int] = None
    experiment_profile_id: Optional[str] = None
    parameter_values: Dict[str, Any] = Field(default_factory=dict)
    requested_metrics: list[str] = Field(default_factory=list)
    tags: Dict[str, str] = Field(default_factory=dict)
    experiment_summary_available: bool = False
    archived: bool = False


class SimRunMetrics(BaseModel):
    run_id: str
    status: SimRunStatus
    elapsed_seconds: float
    output_lines: int
    event_count: int
    log_touched: Optional[str] = None
    stdout_tail_lines: int
    stderr_tail_lines: int
    last_log_path: Optional[str] = None
