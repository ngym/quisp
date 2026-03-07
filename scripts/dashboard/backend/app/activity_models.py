from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class ActivityGlobalTotals(BaseModel):
    events_per_s: float = 0.0
    visible_event_density: Optional[float] = None
    request_submit_rate: float = 0.0
    request_accept_rate: float = 0.0
    request_reject_rate: float = 0.0
    bellpair_generation_rate: float = 0.0
    photon_loss_rate: float = 0.0
    active_node_count: int = 0
    active_edge_count: int = 0


class ActivityBin(BaseModel):
    start_sim_time: float
    end_sim_time: float
    events_per_s: float = 0.0
    visible_event_density: Optional[float] = None
    request_submit_rate: float = 0.0
    request_accept_rate: float = 0.0
    request_reject_rate: float = 0.0
    bellpair_generation_rate: float = 0.0
    photon_loss_rate: float = 0.0
    active_node_count: int = 0
    active_edge_count: int = 0


class ActivityNodeHeat(BaseModel):
    id: str
    total_count: int = 0
    rate_per_s: float = 0.0
    intensity: float = 0.0
    dominant_class: str = "mixed"
    counts_by_class: Dict[str, int] = Field(default_factory=dict)


class ActivityEdgeHeat(BaseModel):
    src: str
    dst: str
    total_count: int = 0
    rate_per_s: float = 0.0
    intensity: float = 0.0
    dominant_class: str = "mixed"
    counts_by_class: Dict[str, int] = Field(default_factory=dict)


class KeyMoment(BaseModel):
    cursor: int
    sim_time: Optional[float] = None
    event_type: str
    label: str
    severity: Literal["info", "warn", "bad"] = "info"
    node_id: Optional[str] = None
    src: Optional[str] = None
    dst: Optional[str] = None


class ActivitySnapshot(BaseModel):
    run_id: str
    anchor_cursor: int
    live_edge_cursor: int
    anchor_sim_time: Optional[float] = None
    window_s: float = 1.0
    lookback_s: float = 15.0
    global_totals: ActivityGlobalTotals
    bins: List[ActivityBin] = Field(default_factory=list)
    view_node_activity: List[ActivityNodeHeat] = Field(default_factory=list)
    view_edge_activity: List[ActivityEdgeHeat] = Field(default_factory=list)
    key_moments: List[KeyMoment] = Field(default_factory=list)


class ActivityDensitySummary(BaseModel):
    count: int = 0
    mean: Optional[float] = None
    min: Optional[float] = None
    max: Optional[float] = None
    p50: Optional[float] = None
    p95: Optional[float] = None
    p99: Optional[float] = None


class PeakWindow(BaseModel):
    start_sim_time: float
    end_sim_time: float
    visible_event_density: float
    dominant_class: str = "mixed"


class RunActivitySummary(BaseModel):
    run_id: str
    bin_s: float = 1.0
    classes: List[str] = Field(default_factory=list)
    visible_event_density: ActivityDensitySummary
    peak_windows: List[PeakWindow] = Field(default_factory=list)
    global_counts_by_class: Dict[str, int] = Field(default_factory=dict)
