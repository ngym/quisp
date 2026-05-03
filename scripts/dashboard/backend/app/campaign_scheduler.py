from __future__ import annotations

import time
from typing import Any, Optional

from .campaign_models import Campaign, CampaignRunSpec, CampaignRunStatus, CampaignStatus
from .campaign_store import CampaignStore
from .sim_models import SimRunStartRequest, SimRunStatus
from .sim_store import SimulationRunStore


class CampaignScheduler:
    def __init__(
        self,
        *,
        campaign_store: CampaignStore,
        simulation_runner: Any,
        max_concurrent_runs: int,
        sim_store: Optional[SimulationRunStore] = None,
    ) -> None:
        self.campaign_store = campaign_store
        self.simulation_runner = simulation_runner
        self.max_concurrent_runs = max(1, int(max_concurrent_runs))
        self.sim_store = sim_store

    async def tick(self) -> None:
        for campaign in self.campaign_store.list_campaigns():
            await self._sync_known_specs(campaign)
            if campaign.status in {CampaignStatus.PAUSED, CampaignStatus.CANCELLED, CampaignStatus.FINISHED, CampaignStatus.FAILED}:
                continue
            await self._start_available_specs(campaign)

    async def sync(self) -> None:
        for campaign in self.campaign_store.list_campaigns():
            await self._sync_known_specs(campaign)

    async def mark_run_terminal(self, run_id: str, *, status: str, error_message: str | None = None) -> Campaign:
        campaign, spec = self._find_spec_by_run_id(run_id)
        if status == "finished":
            spec.status = CampaignRunStatus.FINISHED
        elif status in {"cancelled", "terminated"}:
            spec.status = CampaignRunStatus.CANCELLED
        else:
            spec.status = CampaignRunStatus.FAILED
        spec.error_message = error_message
        campaign.refresh_status()
        if campaign.status in {CampaignStatus.FINISHED, CampaignStatus.FAILED, CampaignStatus.CANCELLED}:
            campaign.finished_at = time.time()
        return self.campaign_store.update_campaign(campaign)

    async def pause_campaign(self, campaign_id: str) -> Campaign:
        campaign = self.campaign_store.get_campaign(campaign_id)
        if campaign.status not in {CampaignStatus.CANCELLED, CampaignStatus.FINISHED, CampaignStatus.FAILED}:
            campaign.status = CampaignStatus.PAUSED
        return self.campaign_store.update_campaign(campaign)

    async def resume_campaign(self, campaign_id: str) -> Campaign:
        campaign = self.campaign_store.get_campaign(campaign_id)
        if campaign.status == CampaignStatus.PAUSED:
            campaign.status = CampaignStatus.QUEUED
        self.campaign_store.update_campaign(campaign)
        await self._start_available_specs(campaign)
        return self.campaign_store.get_campaign(campaign_id)

    async def stop_campaign(self, campaign_id: str) -> Campaign:
        campaign = self.campaign_store.get_campaign(campaign_id)
        for spec in campaign.run_specs:
            if spec.status == CampaignRunStatus.QUEUED:
                spec.status = CampaignRunStatus.CANCELLED
            elif spec.status in {CampaignRunStatus.STARTING, CampaignRunStatus.RUNNING} and spec.run_id:
                try:
                    await self.simulation_runner.stop_run(spec.run_id)
                except Exception:
                    pass
                spec.status = CampaignRunStatus.CANCELLED
        campaign.status = CampaignStatus.CANCELLED
        campaign.finished_at = time.time()
        return self.campaign_store.update_campaign(campaign)

    async def retry_run_spec(self, campaign_id: str, spec_or_run_id: str) -> Campaign:
        campaign = self.campaign_store.get_campaign(campaign_id)
        source = self._find_spec(campaign, spec_or_run_id)
        if source.status not in {CampaignRunStatus.FAILED, CampaignRunStatus.CANCELLED}:
            raise ValueError("only failed or cancelled campaign run specs can be retried")
        next_index = len(campaign.run_specs) + 1
        clone = source.model_copy(deep=True)
        clone.spec_id = f"spec_{next_index:04d}"
        clone.status = CampaignRunStatus.QUEUED
        clone.run_id = None
        clone.error_message = None
        clone.tags = {**dict(clone.tags or {}), "campaign_spec_id": clone.spec_id, "retry_of": source.spec_id}
        campaign.run_specs.append(clone)
        if campaign.status == CampaignStatus.CANCELLED:
            campaign.status = CampaignStatus.QUEUED
        self.campaign_store.update_campaign(campaign)
        await self._start_available_specs(campaign)
        return self.campaign_store.get_campaign(campaign_id)

    async def _available_slots(self, campaign: Campaign) -> int:
        if self.sim_store is not None:
            active = await self.sim_store.count_active()
            return max(0, self.max_concurrent_runs - active)
        campaign.refresh_counters()
        return max(0, self.max_concurrent_runs - campaign.running_count - campaign.starting_count)

    async def _sync_known_specs(self, campaign: Campaign) -> Campaign:
        changed = False
        for spec in campaign.run_specs:
            if spec.status not in {CampaignRunStatus.STARTING, CampaignRunStatus.RUNNING} or not spec.run_id:
                continue
            try:
                record = await self._get_run_record(spec.run_id)
            except Exception:
                continue
            previous_status = spec.status
            sim_status = getattr(record, "status", None)
            status_value = getattr(sim_status, "value", str(sim_status))
            if status_value == SimRunStatus.FINISHED.value:
                spec.status = CampaignRunStatus.FINISHED
            elif status_value == SimRunStatus.FAILED.value:
                spec.status = CampaignRunStatus.FAILED
            elif status_value == SimRunStatus.TERMINATED.value:
                spec.status = CampaignRunStatus.CANCELLED
            elif status_value in {SimRunStatus.QUEUED.value, SimRunStatus.STARTING.value}:
                spec.status = CampaignRunStatus.STARTING
            else:
                spec.status = CampaignRunStatus.RUNNING
            if spec.status in {CampaignRunStatus.FAILED, CampaignRunStatus.CANCELLED}:
                spec.error_message = getattr(record, "status_message", None)
            changed = changed or previous_status != spec.status
        if changed:
            campaign.refresh_status()
            if campaign.status in {CampaignStatus.FINISHED, CampaignStatus.FAILED, CampaignStatus.CANCELLED}:
                campaign.finished_at = time.time()
            return self.campaign_store.update_campaign(campaign)
        return campaign

    async def _get_run_record(self, run_id: str) -> Any:
        if self.sim_store is not None:
            return await self.sim_store.get(run_id)
        return await self.simulation_runner.get_run(run_id)

    async def _start_available_specs(self, campaign: Campaign) -> Campaign:
        slots = await self._available_slots(campaign)
        if slots <= 0:
            campaign.refresh_status()
            return self.campaign_store.update_campaign(campaign)
        started = False
        for spec in campaign.run_specs:
            if slots <= 0:
                break
            if spec.status != CampaignRunStatus.QUEUED:
                continue
            await self._start_spec(campaign, spec)
            started = True
            slots -= 1
        if started and campaign.started_at is None:
            campaign.started_at = time.time()
        campaign.refresh_status()
        return self.campaign_store.update_campaign(campaign)

    async def _start_spec(self, campaign: Campaign, spec: CampaignRunSpec) -> None:
        spec.status = CampaignRunStatus.STARTING
        request = SimRunStartRequest(
            template_id=spec.template_id,
            config_name=spec.config_name,
            experiment_profile_id=spec.experiment_profile_id,
            parameter_values=dict(spec.parameter_values or {}),
            requested_metrics=list(spec.requested_metrics or []),
            overrides=dict(spec.overrides or {}),
            run_name=spec.run_name,
            num_runs=1,
            seed_set=spec.seed_set,
            sim_time_limit=spec.sim_time_limit,
            tags=dict(spec.tags or {}),
        )
        try:
            record = await self.simulation_runner.start_run(request=request)
        except Exception as exc:
            spec.status = CampaignRunStatus.FAILED
            spec.error_message = str(exc)
            return
        spec.run_id = record.run_id
        status = getattr(record, "status", None)
        if status == SimRunStatus.FINISHED or str(status) == "finished":
            spec.status = CampaignRunStatus.FINISHED
        elif status == SimRunStatus.FAILED or str(status) == "failed":
            spec.status = CampaignRunStatus.FAILED
        else:
            spec.status = CampaignRunStatus.RUNNING

    def _find_spec(self, campaign: Campaign, spec_or_run_id: str) -> CampaignRunSpec:
        for spec in campaign.run_specs:
            if spec.spec_id == spec_or_run_id or spec.run_id == spec_or_run_id:
                return spec
        raise KeyError(f"unknown campaign run spec {spec_or_run_id}")

    def _find_spec_by_run_id(self, run_id: str) -> tuple[Campaign, CampaignRunSpec]:
        for campaign in self.campaign_store.list_campaigns():
            for spec in campaign.run_specs:
                if spec.run_id == run_id:
                    return campaign, spec
        raise KeyError(f"unknown campaign run_id {run_id}")
