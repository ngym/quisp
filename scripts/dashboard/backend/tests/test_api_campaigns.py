from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from scripts.dashboard.backend.app import main
from scripts.dashboard.backend.app.models import SimTemplate
from scripts.dashboard.backend.app.sim_models import SimRunStatus
from scripts.dashboard.backend.app.sim_store import SimRunRecord


class FakeCampaignRunner:
    last_instance = None

    def __init__(self, *, run_store, sim_store, **_kwargs):
        self._run_store = run_store
        self._sim_store = sim_store
        self._records: dict[str, SimRunRecord] = {}
        self.started_requests = []
        FakeCampaignRunner.last_instance = self

    async def start_run(self, request):
        self.started_requests.append(request)
        run_id = f"campaign_run_{len(self.started_requests):03d}"
        run_dir = Path(self._run_store.log_dir) / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        log_path = run_dir / "run.jsonl"
        log_path.write_text("", encoding="utf-8")
        record = SimRunRecord(
            run_id=run_id,
            template_id=request.template_id or "",
            config_name=request.config_name or "",
            log_path=log_path,
            ini_path=run_dir / "run.ini",
            command=["quisp"],
            workdir=Path(request.workdir) if request.workdir else Path("."),
            run_name=request.run_name,
            num_runs=request.num_runs,
            seed_set=request.seed_set,
            sim_time_limit=request.sim_time_limit,
            status=SimRunStatus.RUNNING,
            experiment_profile_id=request.experiment_profile_id,
            parameter_values=request.parameter_values,
            requested_metrics=request.requested_metrics,
            tags=request.tags,
        )
        await self._sim_store.register(record)
        self._run_store.register_run_file(log_path, run_id=run_id)
        self._records[run_id] = record
        return record

    async def list_runs(self):
        return list(self._records.values())

    async def get_run(self, run_id: str):
        return self._records[run_id]

    async def stop_run(self, run_id: str, timeout_seconds: float | None = None):
        record = self._records[run_id]
        record.status = SimRunStatus.TERMINATED
        return record

    async def get_logs(self, run_id: str, limit: int = 200, mode: str = "all"):
        return []

    async def get_metrics(self, run_id: str):
        return {
            "run_id": run_id,
            "status": SimRunStatus.RUNNING,
            "elapsed_seconds": 0.0,
            "output_lines": 0,
            "event_count": 0,
            "log_touched": None,
            "stdout_tail_lines": 0,
            "stderr_tail_lines": 0,
            "last_log_path": str(Path(self._run_store.log_dir) / run_id / "run.jsonl"),
        }


def _install_fake_runner(monkeypatch):
    monkeypatch.setattr(main, "SimulationRunner", FakeCampaignRunner)


def _install_profile_template(monkeypatch, root: Path):
    template_path = root / "quisp" / "simulations" / "two_nodes.ini"
    template_path.parent.mkdir(parents=True, exist_ok=True)
    template_path.write_text("[Config two_node_MIM]\n", encoding="utf-8")

    def _templates(project_root=None):
        return [
            SimTemplate(
                template_id="quisp/simulations/two_nodes.ini",
                path=str(template_path),
                available_configs=["two_node_MIM"],
                description="mock",
                default_workdir=str(root),
                last_modified="1970-01-01T00:00:00Z",
            )
        ]

    def _template_with_configs(template_id_arg, project_root=None):
        assert template_id_arg == "quisp/simulations/two_nodes.ini"
        return {
            "path": template_path,
            "config_names": ["two_node_MIM"],
            "default_workdir": str(root),
        }

    monkeypatch.setattr(main, "list_templates", _templates)
    monkeypatch.setattr(main, "template_with_configs", _template_with_configs)


def _campaign_request():
    return {
        "display_name": "Two-node request-rate campaign",
        "experiment_profile_id": "verify_two_node_setup",
        "base_parameter_values": {
            "execution.backend_type": "graph_state",
            "execution.sim_time_limit_s": 4.0,
            "traffic.pairs_per_request": 1,
        },
        "sweeps": [
            {
                "target": "profile_parameter",
                "id": "execution.seed_set",
                "values": [1, 2],
            },
            {
                "target": "profile_parameter",
                "id": "traffic.request_rate_hz",
                "values": [1.0, 2.0],
            },
            {
                "target": "override",
                "key": "*.source.app.number_of_bellpair",
                "values": [1, 2],
            },
        ],
        "fixed_overrides": {
            "**.logger.emit_router_events": "true",
        },
        "requested_metrics": [
            "request_submitted_count",
            "setup_success_ratio",
        ],
        "tags": {
            "purpose": "campaign-red-test",
        },
    }


def test_campaign_preview_expands_sweeps_without_creating_runs(tmp_path, monkeypatch):
    _install_profile_template(monkeypatch, tmp_path)
    _install_fake_runner(monkeypatch)
    app = main.create_app(log_dir=tmp_path / "runs", workspace_root=tmp_path)
    client = TestClient(app)

    response = client.post("/api/experiments/campaigns/preview", json=_campaign_request())

    assert response.status_code == 200
    payload = response.json()
    assert payload["display_name"] == "Two-node request-rate campaign"
    assert payload["experiment_profile_id"] == "verify_two_node_setup"
    assert payload["resolved_template_id"] == "quisp/simulations/two_nodes.ini"
    assert payload["resolved_config_name"] == "two_node_MIM"
    assert payload["total_runs"] == 8
    assert 1 <= len(payload["sample_runs"]) <= 8
    assert payload["sample_runs"][0]["seed_set"] in {1, 2}
    assert payload["sample_runs"][0]["sim_time_limit"] == 4.0
    assert payload["sample_runs"][0]["num_runs"] == 1
    assert "*.source.app.number_of_bellpair" in payload["sample_runs"][0]["overrides"]
    assert "**.logger.emit_router_events" in payload["sample_runs"][0]["overrides"]
    assert "command_samples" in payload

    runs_response = client.get("/api/sim/runs")
    assert runs_response.status_code == 200
    assert runs_response.json() == []
    assert FakeCampaignRunner.last_instance.started_requests == []


def test_campaign_create_persists_queue_and_starts_only_available_slots(tmp_path, monkeypatch):
    _install_profile_template(monkeypatch, tmp_path)
    _install_fake_runner(monkeypatch)
    app = main.create_app(log_dir=tmp_path / "runs", workspace_root=tmp_path, max_concurrent_runs=2)
    client = TestClient(app)

    response = client.post("/api/experiments/campaigns", json=_campaign_request())

    assert response.status_code == 201
    payload = response.json()
    assert payload["campaign_id"].startswith("campaign_")
    assert payload["display_name"] == "Two-node request-rate campaign"
    assert payload["total_runs"] == 8
    assert payload["running_count"] == 2
    assert payload["queued_count"] == 6
    assert len(FakeCampaignRunner.last_instance.started_requests) == 2

    detail = client.get(f"/api/experiments/campaigns/{payload['campaign_id']}")
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert detail_payload["campaign_id"] == payload["campaign_id"]
    assert detail_payload["total_runs"] == 8
    assert len(detail_payload["run_specs"]) == 8
    assert {spec["status"] for spec in detail_payload["run_specs"]} >= {"queued", "running"}


def test_campaign_control_pause_resume_stop_and_retry(tmp_path, monkeypatch):
    _install_profile_template(monkeypatch, tmp_path)
    _install_fake_runner(monkeypatch)
    app = main.create_app(log_dir=tmp_path / "runs", workspace_root=tmp_path, max_concurrent_runs=1)
    client = TestClient(app)
    create = client.post("/api/experiments/campaigns", json=_campaign_request())
    assert create.status_code == 201
    campaign_id = create.json()["campaign_id"]

    pause = client.post(f"/api/experiments/campaigns/{campaign_id}/pause")
    assert pause.status_code == 200
    assert pause.json()["status"] == "paused"

    resume = client.post(f"/api/experiments/campaigns/{campaign_id}/resume")
    assert resume.status_code == 200
    assert resume.json()["status"] in {"queued", "running"}

    stop = client.post(f"/api/experiments/campaigns/{campaign_id}/stop")
    assert stop.status_code == 200
    stopped = stop.json()
    assert stopped["status"] == "cancelled"
    assert stopped["cancelled_count"] >= 1

    failed_or_cancelled_spec = next(
        spec for spec in stopped["run_specs"] if spec["status"] in {"failed", "cancelled"}
    )
    retry = client.post(
        f"/api/experiments/campaigns/{campaign_id}/runs/{failed_or_cancelled_spec['spec_id']}/retry"
    )
    assert retry.status_code == 200
    retry_payload = retry.json()
    assert retry_payload["campaign_id"] == campaign_id
    assert retry_payload["total_runs"] == stopped["total_runs"] + 1
