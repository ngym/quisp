from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ExperimentParameterOption(BaseModel):
    value: str
    label: str


class ExperimentParameterDefinition(BaseModel):
    id: str
    label: str
    group: str
    type: str
    unit: Optional[str] = None
    required: bool = False
    advanced: bool = False
    default: Any = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    step: Optional[float] = None
    enum_options: list[ExperimentParameterOption] = Field(default_factory=list)
    help_text: Optional[str] = None


class ExperimentProfile(BaseModel):
    profile_id: str
    label: str
    description: str
    template_id: str
    config_name: str
    supported_parameter_ids: list[str]
    default_parameter_values: Dict[str, Any] = Field(default_factory=dict)
    recommended_metric_ids: list[str] = Field(default_factory=list)
    override_mappings: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    fixed_overrides: Dict[str, str] = Field(default_factory=dict)
    notes: Optional[str] = None


class ExperimentFormSchema(BaseModel):
    template_id: str
    config_name: str
    profile_id: Optional[str] = None
    parameter_definitions: list[ExperimentParameterDefinition]
    default_parameter_values: Dict[str, Any] = Field(default_factory=dict)
    recommended_metric_ids: list[str] = Field(default_factory=list)
    legacy_override_supported: bool = True


class DistributionSummary(BaseModel):
    count: int
    mean: Optional[float] = None
    min: Optional[float] = None
    max: Optional[float] = None
    p50: Optional[float] = None
    p95: Optional[float] = None
    p99: Optional[float] = None
    sample_mode: str = "exact"


class ArtifactPaths(BaseModel):
    spec_path: str
    summary_path: str
    timeseries_path: Optional[str] = None


class ExperimentRunSummary(BaseModel):
    run_id: str
    display_name: str
    status: str
    experiment_profile_id: Optional[str] = None
    parameter_values: Dict[str, Any] = Field(default_factory=dict)
    resolved_overrides: Dict[str, Any] = Field(default_factory=dict)
    requested_metrics: list[str] = Field(default_factory=list)
    metric_summaries: Dict[str, Any] = Field(default_factory=dict)
    failure_reason_breakdown: Dict[str, int] = Field(default_factory=dict)
    link_quality_latest: list[Dict[str, Any]] = Field(default_factory=list)
    timeseries_metric_ids: list[str] = Field(default_factory=list)
    artifacts: ArtifactPaths


class ExperimentTimeseriesPoint(BaseModel):
    bin_index: int
    sim_time_start: float
    sim_time_end: float
    value: Optional[float] = None


class ExperimentTimeseries(BaseModel):
    run_id: str
    metric_id: str
    bin_s: float
    unavailable: bool = False
    points: list[ExperimentTimeseriesPoint] = Field(default_factory=list)


class ExperimentComparisonRequest(BaseModel):
    run_ids: List[str]
    metric_ids: list[str] = Field(default_factory=list)


class ExperimentComparisonResponse(BaseModel):
    runs: list[Dict[str, Any]] = Field(default_factory=list)
    metric_rows: list[Dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
