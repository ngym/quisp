from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from scripts.dashboard.backend.app import main
from scripts.dashboard.backend.app.models import SimTemplate
from scripts.dashboard.backend.app.sim_store import SimRunRecord
from scripts.dashboard.backend.app.sim_models import SimRunStatus


class FakeExperimentRunner:
    last_instance = None

    def __init__(self, *, run_store, sim_store, **_kwargs):
        self._run_store = run_store
        self._sim_store = sim_store
        self._records: dict[str, SimRunRecord] = {}
        self._count = 0
        FakeExperimentRunner.last_instance = self

    async def start_run(self, request):
        self._count += 1
        run_id = f"exp_{self._count:03d}"
        run_dir = Path(self._run_store.log_dir) / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        log_path = run_dir / "run.jsonl"
        log_path.write_text("", encoding="utf-8")
        (run_dir / "experiment_spec.json").write_text(
            json.dumps(
                {
                    "experiment_profile_id": request.experiment_profile_id,
                    "parameter_values": request.parameter_values,
                    "requested_metrics": request.requested_metrics,
                    "run_name": request.run_name,
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "resolved_overrides.json").write_text(
            json.dumps(request.overrides),
            encoding="utf-8",
        )
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
            experiment_display_name=request.run_name or request.config_name,
            experiment_profile_id=request.experiment_profile_id,
            parameter_values=request.parameter_values,
            requested_metrics=request.requested_metrics,
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
            "last_log_path": str((Path(self._run_store.log_dir) / run_id / "run.jsonl")),
        }


def _install_fake_runner(monkeypatch):
    monkeypatch.setattr(main, "SimulationRunner", FakeExperimentRunner)


def _install_profile_templates(monkeypatch, root: Path):
    profile_template = root / "quisp" / "simulations" / "two_nodes.ini"
    profile_template.parent.mkdir(parents=True, exist_ok=True)
    profile_template.write_text("[Config two_node_MIM]\n", encoding="utf-8")

    def _templates(project_root=None):
        return [
            SimTemplate(
                template_id="quisp/simulations/two_nodes.ini",
                path=str(profile_template),
                available_configs=["two_node_MIM"],
                description="mock",
                default_workdir=str(root),
                last_modified="1970-01-01T00:00:00Z",
            )
        ]

    def _template_with_configs(template_id_arg, project_root=None):
        assert template_id_arg == "quisp/simulations/two_nodes.ini"
        return {
            "path": profile_template,
            "config_names": ["two_node_MIM"],
            "default_workdir": str(root),
        }

    monkeypatch.setattr(main, "list_templates", _templates)
    monkeypatch.setattr(main, "template_with_configs", _template_with_configs)


def test_experiment_catalog_and_structured_start(tmp_path, monkeypatch):
    _install_profile_templates(monkeypatch, tmp_path)
    _install_fake_runner(monkeypatch)

    app = main.create_app(log_dir=tmp_path, workspace_root=tmp_path)
    client = TestClient(app)

    catalog_resp = client.get("/api/experiments/catalog")
    assert catalog_resp.status_code == 200
    assert any(item["profile_id"] == "verify_two_node_setup" for item in catalog_resp.json())

    schema_resp = client.get(
        "/api/experiments/catalog/schema",
        params={
            "template_id": "quisp/simulations/two_nodes.ini",
            "config_name": "two_node_MIM",
        },
    )
    assert schema_resp.status_code == 200
    assert schema_resp.json()["profile_id"] == "verify_two_node_setup"

    start_resp = client.post(
        "/api/sim/runs",
        json={
            "experiment_profile_id": "two_node_mim_smoke",
            "parameter_values": {
                "traffic.request_rate_hz": 5,
                "execution.sim_time_limit_s": 4,
            },
        },
    )
    assert start_resp.status_code == 200
    body = start_resp.json()
    assert body["experiment_profile_id"] == "two_node_mim_smoke"

    run_resp = client.get(f"/api/sim/runs/{body['run_id']}")
    assert run_resp.status_code == 200
    assert run_resp.json()["experiment_profile_id"] == "two_node_mim_smoke"
    assert run_resp.json()["parameter_values"]["traffic.request_rate_hz"] == 5
