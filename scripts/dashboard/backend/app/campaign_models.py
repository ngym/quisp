from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator


class CampaignStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    FINISHED = "finished"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CampaignRunStatus(str, Enum):
    QUEUED = "queued"
    STARTING = "starting"
    RUNNING = "running"
    FINISHED = "finished"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CampaignSweep(BaseModel):
    target: str
    id: Optional[str] = None
    key: Optional[str] = None
    values: list[Any] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_target(self) -> "CampaignSweep":
        if self.target == "profile_parameter":
            if not self.id:
                raise ValueError("profile_parameter sweep requires id")
        elif self.target == "override":
            if not self.key:
                raise ValueError("override sweep requires key")
        else:
            raise ValueError("sweep target must be profile_parameter or override")
        return self


class CampaignCreateRequest(BaseModel):
    display_name: Optional[str] = None
    experiment_profile_id: Optional[str] = None
    template_id: Optional[str] = None
    config_name: Optional[str] = None
    base_parameter_values: dict[str, Any] = Field(default_factory=dict)
    sweeps: list[CampaignSweep] = Field(default_factory=list)
    fixed_overrides: dict[str, Any] = Field(default_factory=dict)
    requested_metrics: list[str] = Field(default_factory=list)
    tags: dict[str, str] = Field(default_factory=dict)


class CampaignRunSpec(BaseModel):
    spec_id: str
    parameter_values: dict[str, Any] = Field(default_factory=dict)
    overrides: dict[str, Any] = Field(default_factory=dict)
    seed_set: Optional[int] = None
    sim_time_limit: Optional[float] = None
    run_name: Optional[str] = None
    tags: dict[str, str] = Field(default_factory=dict)
    status: CampaignRunStatus = CampaignRunStatus.QUEUED
    run_id: Optional[str] = None
    error_message: Optional[str] = None
    template_id: str = ""
    config_name: str = ""
    experiment_profile_id: Optional[str] = None
    requested_metrics: list[str] = Field(default_factory=list)
    num_runs: int = 1


class Campaign(BaseModel):
    campaign_id: str
    display_name: str
    experiment_profile_id: Optional[str] = None
    template_id: str
    config_name: str
    base_parameter_values: dict[str, Any] = Field(default_factory=dict)
    sweeps: list[CampaignSweep] = Field(default_factory=list)
    fixed_overrides: dict[str, Any] = Field(default_factory=dict)
    requested_metrics: list[str] = Field(default_factory=list)
    tags: dict[str, str] = Field(default_factory=dict)
    run_specs: list[CampaignRunSpec] = Field(default_factory=list)
    run_ids: list[str] = Field(default_factory=list)
    status: CampaignStatus = CampaignStatus.QUEUED
    created_at: float
    updated_at: float
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    total_runs: int = 0
    queued_count: int = 0
    starting_count: int = 0
    running_count: int = 0
    finished_count: int = 0
    failed_count: int = 0
    cancelled_count: int = 0

    def refresh_counters(self) -> "Campaign":
        self.total_runs = len(self.run_specs)
        self.queued_count = sum(1 for spec in self.run_specs if spec.status == CampaignRunStatus.QUEUED)
        self.starting_count = sum(1 for spec in self.run_specs if spec.status == CampaignRunStatus.STARTING)
        self.running_count = sum(1 for spec in self.run_specs if spec.status == CampaignRunStatus.RUNNING)
        self.finished_count = sum(1 for spec in self.run_specs if spec.status == CampaignRunStatus.FINISHED)
        self.failed_count = sum(1 for spec in self.run_specs if spec.status == CampaignRunStatus.FAILED)
        self.cancelled_count = sum(1 for spec in self.run_specs if spec.status == CampaignRunStatus.CANCELLED)
        self.run_ids = [spec.run_id for spec in self.run_specs if spec.run_id]
        return self

    def refresh_status(self) -> "Campaign":
        if self.status in {CampaignStatus.PAUSED, CampaignStatus.CANCELLED}:
            self.refresh_counters()
            return self
        self.refresh_counters()
        if self.running_count or self.starting_count:
            self.status = CampaignStatus.RUNNING
        elif self.queued_count:
            self.status = CampaignStatus.QUEUED
        elif self.failed_count:
            self.status = CampaignStatus.FAILED
        elif self.cancelled_count and not self.finished_count:
            self.status = CampaignStatus.CANCELLED
        else:
            self.status = CampaignStatus.FINISHED
        return self


class CampaignPreviewResponse(BaseModel):
    display_name: str
    experiment_profile_id: Optional[str] = None
    resolved_template_id: str
    resolved_config_name: str
    total_runs: int
    sample_runs: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    command_samples: list[list[str]] = Field(default_factory=list)
