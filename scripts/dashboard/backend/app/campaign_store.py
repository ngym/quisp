from __future__ import annotations

import itertools
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any

from .campaign_models import (
    Campaign,
    CampaignCreateRequest,
    CampaignPreviewResponse,
    CampaignRunSpec,
    CampaignRunStatus,
    CampaignStatus,
)
from .experiment_catalog import resolve_experiment_request
from .runner_config_builder import validate_run_spec_overrides
from .sim_models import SimRunStartRequest


class CampaignStore:
    def __init__(self, *, root_dir: Path, max_campaign_runs: int | None = None) -> None:
        self.root_dir = Path(root_dir)
        self.max_campaign_runs = int(max_campaign_runs or os.getenv("Q_DASH_MAX_CAMPAIGN_RUNS", "10000"))
        self._campaigns: dict[str, Campaign] = {}

    def _next_campaign_id(self) -> str:
        return f"campaign_{int(time.time() * 1000)}_{secrets.token_hex(3)}"

    def _campaign_path(self, campaign_id: str) -> Path:
        return self.root_dir / campaign_id / "campaign.json"

    def list_campaigns(self) -> list[Campaign]:
        return sorted(self._campaigns.values(), key=lambda item: item.created_at, reverse=True)

    def get_campaign(self, campaign_id: str) -> Campaign:
        if campaign_id not in self._campaigns:
            raise KeyError(f"unknown campaign_id {campaign_id}")
        return self._campaigns[campaign_id]

    def save_campaign(self, campaign: Campaign) -> Campaign:
        campaign.updated_at = time.time()
        campaign.refresh_status()
        path = self._campaign_path(campaign.campaign_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(campaign.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(path)
        self._campaigns[campaign.campaign_id] = campaign
        return campaign

    def restore_from_disk(self, *, mark_orphaned_active_runs_failed: bool = False) -> list[Campaign]:
        self.root_dir.mkdir(parents=True, exist_ok=True)
        restored: list[Campaign] = []
        for path in sorted(self.root_dir.glob("*/campaign.json")):
            try:
                campaign = Campaign(**json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                continue
            if mark_orphaned_active_runs_failed:
                for spec in campaign.run_specs:
                    if spec.status in {CampaignRunStatus.STARTING, CampaignRunStatus.RUNNING}:
                        spec.status = CampaignRunStatus.FAILED
                        spec.error_message = "dashboard restarted before completion"
            campaign.refresh_status()
            self._campaigns[campaign.campaign_id] = campaign
            self.save_campaign(campaign)
            restored.append(campaign)
        return restored

    def preview_request(self, request: CampaignCreateRequest) -> CampaignPreviewResponse:
        specs, resolved = self._expand_request(request, campaign_id="preview")
        return CampaignPreviewResponse(
            display_name=self._display_name(request, resolved),
            experiment_profile_id=resolved["experiment_profile_id"],
            resolved_template_id=resolved["template_id"],
            resolved_config_name=resolved["config_name"],
            total_runs=len(specs),
            sample_runs=[spec.model_dump(mode="json") for spec in specs[:50]],
            warnings=self._warnings(specs),
            command_samples=[self._command_sample(spec) for spec in specs[:3]],
        )

    def create_campaign_from_request(self, request: CampaignCreateRequest) -> Campaign:
        campaign_id = self._next_campaign_id()
        specs, resolved = self._expand_request(request, campaign_id=campaign_id)
        now = time.time()
        campaign = Campaign(
            campaign_id=campaign_id,
            display_name=self._display_name(request, resolved),
            experiment_profile_id=resolved["experiment_profile_id"],
            template_id=resolved["template_id"],
            config_name=resolved["config_name"],
            base_parameter_values=dict(request.base_parameter_values or {}),
            sweeps=list(request.sweeps or []),
            fixed_overrides=dict(request.fixed_overrides or {}),
            requested_metrics=list(resolved["requested_metrics"] or []),
            tags={str(key): str(value) for key, value in dict(request.tags or {}).items()},
            run_specs=specs,
            status=CampaignStatus.QUEUED,
            created_at=now,
            updated_at=now,
        )
        campaign.refresh_status()
        self.save_campaign(campaign)
        return campaign

    def update_campaign(self, campaign: Campaign) -> Campaign:
        return self.save_campaign(campaign)

    def _display_name(self, request: CampaignCreateRequest, resolved: dict[str, Any]) -> str:
        return request.display_name or resolved.get("experiment_display_name") or resolved["config_name"]

    def _expand_request(self, request: CampaignCreateRequest, *, campaign_id: str) -> tuple[list[CampaignRunSpec], dict[str, Any]]:
        combinations = self._sweep_product(request)
        if len(combinations) > self.max_campaign_runs:
            raise ValueError(f"campaign expands to {len(combinations)} runs, limit is {self.max_campaign_runs}")
        specs: list[CampaignRunSpec] = []
        first_resolved: dict[str, Any] | None = None
        for index, combination in enumerate(combinations):
            resolved = self._resolve_one(request, combination, spec_index=index, campaign_id=campaign_id)
            if first_resolved is None:
                first_resolved = resolved
            specs.append(self._spec_from_resolution(resolved, spec_index=index, campaign_id=campaign_id))
        if first_resolved is None:
            first_resolved = self._resolve_one(request, {}, spec_index=0, campaign_id=campaign_id)
        return specs, first_resolved

    def _sweep_product(self, request: CampaignCreateRequest) -> list[dict[str, Any]]:
        sweeps = list(request.sweeps or [])
        if not sweeps:
            return [{}]
        value_lists = [sweep.values if sweep.values else [None] for sweep in sweeps]
        result: list[dict[str, Any]] = []
        for values in itertools.product(*value_lists):
            item: dict[str, Any] = {}
            for sweep, value in zip(sweeps, values):
                if value is None:
                    continue
                if sweep.target == "profile_parameter":
                    item[f"param:{sweep.id}"] = value
                else:
                    item[f"override:{sweep.key}"] = value
            result.append(item)
        return result

    def _resolve_one(
        self,
        request: CampaignCreateRequest,
        combination: dict[str, Any],
        *,
        spec_index: int,
        campaign_id: str,
    ) -> dict[str, Any]:
        parameter_values = dict(request.base_parameter_values or {})
        overrides = dict(request.fixed_overrides or {})
        for key, value in combination.items():
            if key.startswith("param:"):
                parameter_values[key.removeprefix("param:")] = value
            elif key.startswith("override:"):
                overrides[key.removeprefix("override:")] = value
        validate_run_spec_overrides(overrides)
        run_name_base = request.display_name or request.experiment_profile_id or request.config_name or "campaign"
        start_request = SimRunStartRequest(
            template_id=request.template_id,
            config_name=request.config_name,
            experiment_profile_id=request.experiment_profile_id,
            parameter_values=parameter_values,
            requested_metrics=list(request.requested_metrics or []),
            overrides=overrides,
            run_name=f"{run_name_base} #{spec_index + 1}",
            num_runs=1,
            tags={
                **{str(key): str(value) for key, value in dict(request.tags or {}).items()},
                "campaign_id": campaign_id,
            },
        )
        resolved = resolve_experiment_request(start_request)
        resolved_request = SimRunStartRequest(**{**resolved["request_dict"], "num_runs": 1})
        return {
            "request": resolved_request,
            "template_id": resolved_request.template_id or "",
            "config_name": resolved_request.config_name or "",
            "experiment_profile_id": resolved_request.experiment_profile_id,
            "experiment_display_name": resolved["experiment_display_name"],
            "requested_metrics": list(resolved_request.requested_metrics or []),
        }

    def _spec_from_resolution(self, resolved: dict[str, Any], *, spec_index: int, campaign_id: str) -> CampaignRunSpec:
        request: SimRunStartRequest = resolved["request"]
        spec_id = f"spec_{spec_index + 1:04d}"
        return CampaignRunSpec(
            spec_id=spec_id,
            parameter_values=dict(request.parameter_values or {}),
            overrides=dict(request.overrides or {}),
            seed_set=request.seed_set,
            sim_time_limit=request.sim_time_limit,
            run_name=request.run_name,
            tags={**dict(request.tags or {}), "campaign_id": campaign_id, "campaign_spec_id": spec_id},
            template_id=request.template_id or "",
            config_name=request.config_name or "",
            experiment_profile_id=request.experiment_profile_id,
            requested_metrics=list(request.requested_metrics or []),
            num_runs=1,
        )

    def _warnings(self, specs: list[CampaignRunSpec]) -> list[str]:
        warnings: list[str] = []
        if len(specs) > 1000:
            warnings.append(f"large campaign: {len(specs)} runs")
        if any(str(spec.parameter_values.get("execution.backend_type", "")).startswith("qutip") for spec in specs):
            warnings.append("qutip backend can be slow for large campaigns")
        return warnings

    def _command_sample(self, spec: CampaignRunSpec) -> list[str]:
        return ["quisp", "-u", "Cmdenv", "-c", spec.config_name, "-f", f"<campaign:{spec.spec_id}>/run.ini"]
