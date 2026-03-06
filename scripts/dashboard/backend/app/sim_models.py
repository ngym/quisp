from __future__ import annotations

"""Compatibility model exports for simulation API endpoints."""

from .models import (  # noqa: F401
    SimRunStatus,
    SimRunStartRequest,
    SimRunStartResponse,
    SimRunInfo,
    SimRunMetrics,
    SimTemplate,
)
from pydantic import BaseModel, Field


class SimRunStopRequest(BaseModel):
    timeout_seconds: float = Field(default=10.0, ge=0.1, le=600.0)
