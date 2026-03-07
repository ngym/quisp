from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from scripts.dashboard.backend.app import main
from scripts.dashboard.backend.app.models import SimTemplate
from scripts.dashboard.backend.app.sim_models import SimRunStatus
from scripts.dashboard.backend.app.sim_store import SimRunRecord


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
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "resolved_overrides.json").write_text(json.dumps(request.overrides), encoding="utf-8")
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
            status=SimRunStatus.FINISHED,
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
            "status": SimRunStatus.FINISHED,
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


def _write_log(log_path: Path, fidelity: float) -> None:
    log_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "event_type": "experiment_request_submitted",
                        "simtime": 0.0,
                        "event_payload": {
                            "src_addr": 1,
                            "dst_addr": 2,
                            "connection_session_id": 1,
                            "connection_attempt": 0,
                        },
                    }
                ),
                json.dumps(
                    {
                        "event_type": "experiment_request_setup_accepted",
                        "simtime": 1.5,
                        "event_payload": {
                            "src_addr": 1,
                            "dst_addr": 2,
                            "connection_session_id": 1,
                            "connection_attempt": 0,
                            "ruleset_id": 11,
                        },
                    }
                ),
                json.dumps({"event_type": "BellPairGenerated", "simtime": 2.0, "event_payload": {}}),
                json.dumps({"event_type": "flying_qubit_loss", "simtime": 3.0, "event_payload": {"node_id": 1}}),
                json.dumps(
                    {
                        "event_type": "experiment_link_quality_sample",
                        "simtime": 4.0,
                        "event_payload": {
                            "partner_addr": 2,
                            "qnic_index": 0,
                            "distance_km": 10,
                            "link_cost": 1.25,
                            "fidelity": fidelity,
                            "bellpair_per_sec": 2.0,
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_api_experiment_summary_timeseries_and_compare(tmp_path, monkeypatch):
    _install_profile_templates(monkeypatch, tmp_path)
    _install_fake_runner(monkeypatch)

    app = main.create_app(log_dir=tmp_path, workspace_root=tmp_path)
    client = TestClient(app)

    run_ids = []
    for fidelity in (0.91, 0.82):
        start_resp = client.post(
            "/api/sim/runs",
            json={
                "experiment_profile_id": "two_node_mim_smoke",
                "parameter_values": {"traffic.request_rate_hz": 5},
            },
        )
        assert start_resp.status_code == 200
        run_id = start_resp.json()["run_id"]
        run_ids.append(run_id)
        record = FakeExperimentRunner.last_instance._records[run_id]
        _write_log(record.log_path, fidelity)

    summary_resp = client.get(f"/api/sim/runs/{run_ids[0]}/summary")
    assert summary_resp.status_code == 200
    summary = summary_resp.json()
    assert summary["metric_summaries"]["setup_success_ratio"]["value"] == 1.0
    assert summary["metric_summaries"]["setup_latency_s"]["p95"] == 1.5
    assert summary["metric_summaries"]["link_fidelity"]["mean"] == 0.91

    timeseries_resp = client.get(
        f"/api/sim/runs/{run_ids[0]}/timeseries",
        params={"metric": "request_submit_rate", "bin_s": 1.0},
    )
    assert timeseries_resp.status_code == 200
    series = timeseries_resp.json()
    assert series["unavailable"] is False
    assert series["points"][0]["value"] == 1.0

    compare_resp = client.post(
        "/api/experiments/compare",
        json={"run_ids": run_ids, "metric_ids": ["setup_success_ratio", "link_fidelity"]},
    )
    assert compare_resp.status_code == 200
    payload = compare_resp.json()
    assert [item["run_id"] for item in payload["runs"]] == run_ids
    rows = {row["metric_id"]: row for row in payload["metric_rows"]}
    assert rows["setup_success_ratio"][run_ids[0]] == 1.0
    assert rows["link_fidelity"][run_ids[1]]["mean"] == 0.82
