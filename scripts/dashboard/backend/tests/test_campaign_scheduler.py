from __future__ import annotations

import importlib

import pytest


class FakeSimulationRunner:
    def __init__(self):
        self.started_requests = []
        self.finished_run_ids = set()
        self.stopped_run_ids = []
        self.records = {}

    async def start_run(self, request):
        self.started_requests.append(request)
        index = len(self.started_requests)
        record = type(
            "FakeRun",
            (),
            {
                "run_id": f"run_{index:03d}",
                "status": "running",
                "dashboard_run_id": f"run_{index:03d}",
                "status_message": "running",
            },
        )()
        self.records[record.run_id] = record
        return record

    async def stop_run(self, run_id, timeout_seconds=None):
        self.stopped_run_ids.append(run_id)
        record = self.records[run_id]
        record.status = "terminated"
        record.status_message = "terminated"
        return record

    async def get_run(self, run_id):
        return self.records[run_id]


def _modules():
    models = importlib.import_module("scripts.dashboard.backend.app.campaign_models")
    store_mod = importlib.import_module("scripts.dashboard.backend.app.campaign_store")
    scheduler_mod = importlib.import_module("scripts.dashboard.backend.app.campaign_scheduler")
    return models, store_mod, scheduler_mod


def _campaign_request(models):
    return models.CampaignCreateRequest(
        display_name="scheduler campaign",
        experiment_profile_id="verify_two_node_setup",
        base_parameter_values={
            "execution.backend_type": "graph_state",
            "execution.sim_time_limit_s": 4.0,
        },
        sweeps=[
            models.CampaignSweep(
                target="profile_parameter",
                id="execution.seed_set",
                values=[1, 2, 3],
            ),
        ],
    )


@pytest.mark.anyio
async def test_campaign_scheduler_respects_max_concurrent_runs(tmp_path):
    _models, store_mod, scheduler_mod = _modules()
    store = store_mod.CampaignStore(root_dir=tmp_path)
    campaign = store.create_campaign_from_request(_campaign_request(_models))
    runner = FakeSimulationRunner()
    scheduler = scheduler_mod.CampaignScheduler(
        campaign_store=store,
        simulation_runner=runner,
        max_concurrent_runs=2,
    )

    await scheduler.tick()

    assert len(runner.started_requests) == 2
    refreshed = store.get_campaign(campaign.campaign_id)
    assert refreshed.running_count == 2
    assert refreshed.queued_count == 1


@pytest.mark.anyio
async def test_campaign_scheduler_starts_next_run_after_terminal_update(tmp_path):
    _models, store_mod, scheduler_mod = _modules()
    store = store_mod.CampaignStore(root_dir=tmp_path)
    campaign = store.create_campaign_from_request(_campaign_request(_models))
    runner = FakeSimulationRunner()
    scheduler = scheduler_mod.CampaignScheduler(
        campaign_store=store,
        simulation_runner=runner,
        max_concurrent_runs=2,
    )
    await scheduler.tick()
    first_run_id = store.get_campaign(campaign.campaign_id).run_specs[0].run_id

    await scheduler.mark_run_terminal(first_run_id, status="finished")
    await scheduler.tick()

    refreshed = store.get_campaign(campaign.campaign_id)
    assert len(runner.started_requests) == 3
    assert refreshed.finished_count == 1
    assert refreshed.running_count == 2
    assert refreshed.queued_count == 0


@pytest.mark.anyio
async def test_campaign_scheduler_syncs_finished_run_before_starting_next(tmp_path):
    _models, store_mod, scheduler_mod = _modules()
    store = store_mod.CampaignStore(root_dir=tmp_path)
    campaign = store.create_campaign_from_request(_campaign_request(_models))
    runner = FakeSimulationRunner()
    scheduler = scheduler_mod.CampaignScheduler(
        campaign_store=store,
        simulation_runner=runner,
        max_concurrent_runs=1,
    )
    await scheduler.tick()
    first_run_id = store.get_campaign(campaign.campaign_id).run_specs[0].run_id
    runner.records[first_run_id].status = "finished"
    runner.records[first_run_id].status_message = "finished"

    await scheduler.tick()

    refreshed = store.get_campaign(campaign.campaign_id)
    assert len(runner.started_requests) == 2
    assert refreshed.finished_count == 1
    assert refreshed.running_count == 1
    assert refreshed.queued_count == 1


@pytest.mark.anyio
async def test_campaign_scheduler_stop_cancels_unstarted_specs(tmp_path):
    _models, store_mod, scheduler_mod = _modules()
    store = store_mod.CampaignStore(root_dir=tmp_path)
    campaign = store.create_campaign_from_request(_campaign_request(_models))
    runner = FakeSimulationRunner()
    scheduler = scheduler_mod.CampaignScheduler(
        campaign_store=store,
        simulation_runner=runner,
        max_concurrent_runs=1,
    )
    await scheduler.tick()

    stopped = await scheduler.stop_campaign(campaign.campaign_id)

    assert stopped.status == _models.CampaignStatus.CANCELLED
    assert stopped.cancelled_count == 3
    assert runner.stopped_run_ids == [stopped.run_specs[0].run_id]
