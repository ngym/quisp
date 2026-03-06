from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scripts.dashboard.backend.app import main
from scripts.dashboard.backend.app.models import SimTemplate
from scripts.dashboard.backend.app.sim_models import SimRunStatus
from scripts.dashboard.backend.app.sim_store import SimRunRecord


class FakeRunner:
    def __init__(self, *, run_store, sim_store, **_kwargs):
        self._run_store = run_store
        self._sim_store = sim_store
        self._count = 0
        self._records: dict[str, SimRunRecord] = {}

    async def start_run(self, request):
        self._count += 1
        run_id = f"fake_{self._count:03d}"
        log_path = Path(self._run_store.log_dir) / run_id / "run.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("{}", encoding="utf-8")

        record = SimRunRecord(
            run_id=run_id,
            template_id=request.template_id,
            config_name=request.config_name,
            log_path=log_path,
            ini_path=log_path.with_suffix(".ini"),
            command=["quisp"],
            workdir=Path(request.workdir) if request.workdir else Path("."),
            run_name=request.run_name,
            num_runs=request.num_runs,
            seed_set=request.seed_set,
            sim_time_limit=request.sim_time_limit,
            status=SimRunStatus.RUNNING,
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
        return [f"fake log for {run_id}"]

    async def get_metrics(self, run_id: str):
        return {
            "run_id": run_id,
            "status": SimRunStatus.TERMINATED,
            "elapsed_seconds": 0.1,
            "output_lines": 0,
            "event_count": 0,
            "log_touched": None,
            "stdout_tail_lines": 0,
            "stderr_tail_lines": 0,
            "last_log_path": f"/tmp/{run_id}.jsonl",
        }


def _install_fake_runner(monkeypatch):
    monkeypatch.setattr(main, "SimulationRunner", FakeRunner)


def _install_fake_template(monkeypatch, template_file: Path, template_id: str = "network.ini", configs=None):
    if configs is None:
        configs = ["General"]

    def _templates(project_root=None):
        return [
            SimTemplate(
                template_id=template_id,
                path=str(template_file),
                available_configs=configs,
                description="mock",
                default_workdir=str(template_file.parent),
                last_modified="1970-01-01T00:00:00Z",
            )
        ]

    def _template_with_configs(_template_id_arg, project_root=None):
        return {
            "path": template_file,
            "config_names": configs,
            "default_workdir": str(template_file.parent),
        }

    monkeypatch.setattr(main, "list_templates", _templates)
    monkeypatch.setattr(main, "template_with_configs", _template_with_configs)


def test_api_sim_templates_and_start_and_stop(tmp_path, monkeypatch):
    template_id = "network.ini"
    template_file = tmp_path / template_id
    template_file.write_text("[Config General]\\n", encoding="utf-8")

    _install_fake_template(monkeypatch, template_file, template_id=template_id, configs=["General"])
    _install_fake_runner(monkeypatch)

    app = main.create_app(log_dir=tmp_path)
    client = TestClient(app)

    list_resp = client.get("/api/sim/templates")
    assert list_resp.status_code == 200
    assert list_resp.json()[0]["template_id"] == template_id

    start_resp = client.post(
        "/api/sim/runs",
        json={
            "template_id": template_id,
            "config_name": "General",
            "num_runs": 1,
            "sim_time_limit": 10,
            "overrides": {},
        },
    )
    assert start_resp.status_code == 200
    run_id = start_resp.json()["run_id"]

    runs_resp = client.get("/api/sim/runs")
    assert runs_resp.status_code == 200
    items = runs_resp.json()
    assert any(item["run_id"] == run_id for item in items)

    run_resp = client.get(f"/api/sim/runs/{run_id}")
    assert run_resp.status_code == 200
    assert run_resp.json()["run_id"] == run_id

    stop_resp = client.post(f"/api/sim/runs/{run_id}/stop")
    assert stop_resp.status_code == 200
    assert stop_resp.json()["status"] in {"terminated", "stopping", "running", "finished"}

    log_resp = client.get(f"/api/sim/runs/{run_id}/log", params={"limit": 1})
    assert log_resp.status_code == 200
    assert log_resp.json()["run_id"] == run_id


def test_api_sim_templates_and_start_rejects_invalid_config(tmp_path, monkeypatch):
    template_id = "network.ini"
    template_file = tmp_path / template_id
    template_file.write_text("[Config General]\\n", encoding="utf-8")

    _install_fake_template(monkeypatch, template_file, template_id=template_id, configs=["General"])
    _install_fake_runner(monkeypatch)

    app = main.create_app(log_dir=tmp_path)
    client = TestClient(app)
    start_resp = client.post(
        "/api/sim/runs",
        json={
            "template_id": template_id,
            "config_name": "InvalidConfig",
        },
    )
    assert start_resp.status_code == 400


def test_api_sim_stop_unknown_run(tmp_path, monkeypatch):
    template_id = "network.ini"
    template_file = tmp_path / template_id
    template_file.write_text("[Config General]\\n", encoding="utf-8")

    _install_fake_template(monkeypatch, template_file, template_id=template_id, configs=["General"])
    _install_fake_runner(monkeypatch)

    app = main.create_app(log_dir=tmp_path)
    client = TestClient(app)
    stop_resp = client.post("/api/sim/runs/not_exists/stop")
    assert stop_resp.status_code == 404
