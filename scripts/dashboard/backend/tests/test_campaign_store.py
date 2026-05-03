from __future__ import annotations

import importlib


def _campaign_modules():
    models = importlib.import_module("scripts.dashboard.backend.app.campaign_models")
    store_mod = importlib.import_module("scripts.dashboard.backend.app.campaign_store")
    return models, store_mod


def _sample_campaign_request(models):
    return models.CampaignCreateRequest(
        display_name="persisted campaign",
        experiment_profile_id="verify_two_node_setup",
        base_parameter_values={
            "execution.backend_type": "graph_state",
            "execution.sim_time_limit_s": 4.0,
        },
        sweeps=[
            models.CampaignSweep(
                target="profile_parameter",
                id="execution.seed_set",
                values=[1, 2],
            ),
        ],
        fixed_overrides={"**.logger.emit_router_events": "true"},
        requested_metrics=["setup_success_ratio"],
        tags={"purpose": "store-red-test"},
    )


def test_campaign_store_persists_and_restores_campaign_json(tmp_path):
    models, store_mod = _campaign_modules()
    store = store_mod.CampaignStore(root_dir=tmp_path)
    campaign = store.create_campaign_from_request(_sample_campaign_request(models))
    store.save_campaign(campaign)

    restored_store = store_mod.CampaignStore(root_dir=tmp_path)
    restored_store.restore_from_disk()
    restored = restored_store.get_campaign(campaign.campaign_id)

    assert restored.campaign_id == campaign.campaign_id
    assert restored.display_name == "persisted campaign"
    assert restored.total_runs == 2
    assert [spec.seed_set for spec in restored.run_specs] == [1, 2]
    assert restored.run_specs[0].num_runs == 1
    assert restored.run_specs[0].sim_time_limit == 4.0
    assert restored.run_specs[0].overrides["**.logger.emit_router_events"] == "true"


def test_campaign_store_marks_orphaned_active_specs_failed_on_restore(tmp_path):
    models, store_mod = _campaign_modules()
    store = store_mod.CampaignStore(root_dir=tmp_path)
    campaign = store.create_campaign_from_request(_sample_campaign_request(models))
    campaign.run_specs[0].status = models.CampaignRunStatus.RUNNING
    campaign.run_specs[0].run_id = "run_orphaned"
    campaign.status = models.CampaignStatus.RUNNING
    store.save_campaign(campaign)

    restored_store = store_mod.CampaignStore(root_dir=tmp_path)
    restored_store.restore_from_disk(mark_orphaned_active_runs_failed=True)
    restored = restored_store.get_campaign(campaign.campaign_id)

    assert restored.run_specs[0].status == models.CampaignRunStatus.FAILED
    assert "dashboard restarted" in restored.run_specs[0].error_message
    assert restored.failed_count == 1
    assert restored.queued_count == 1
    assert restored.status in {models.CampaignStatus.QUEUED, models.CampaignStatus.RUNNING}
