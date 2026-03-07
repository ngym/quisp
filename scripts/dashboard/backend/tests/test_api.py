from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from scripts.dashboard.backend.app.main import create_app


def _write_run(tmp_path: Path) -> str:
    run_id = "integration_run.log"
    payload = [
        {
            "simtime": 0.1,
            "event_type": "topology",
            "event_payload": {
                "nodes": [
                    {"id": "n1", "x": 10, "y": 20},
                    {"id": "n2", "x": 14, "y": 24},
                    {"id": "n3", "x": 20, "y": 8},
                ],
                "edges": [
                    ["n1", "n2"],
                    ["n2", "n3"],
                ],
            },
        },
        {
            "simtime": 0.2,
            "event_type": "BellPairGenerated",
            "address": "n1",
            "partner_addr": "n2",
        },
        {
            "simtime": 0.3,
            "event_type": "BellPairGenerated",
            "address": "n2",
            "partner_addr": "n3",
        },
    ]

    log_path = tmp_path / run_id
    with log_path.open("w", encoding="utf-8") as f:
        for row in payload:
            f.write(json.dumps(row))
            f.write("\n")
    return run_id


def _write_connection_run(tmp_path: Path) -> str:
    run_id = "connection_run.log"
    payload = [
        {
            "simtime": 0.1,
            "event_type": "handleMessage",
            "address": "1",
            "msg_type": "ConnectionSetupRequest",
            "actual_dest_addr": 3,
            "actual_src_addr": 1,
            "num_measure": 1000,
            "num_required_bell_pairs": 0,
        },
        {
            "simtime": 0.2,
            "event_type": "handleMessage",
            "address": "1",
            "msg_type": "ConnectionSetupRequest",
            "actual_dest_addr": 3,
            "actual_src_addr": 1,
            "num_measure": 1000,
            "num_required_bell_pairs": 0,
        },
    ]

    log_path = tmp_path / run_id
    with log_path.open("w", encoding="utf-8") as f:
        for row in payload:
            f.write(json.dumps(row))
            f.write("\n")
    return run_id


def test_api_returns_runs_and_topology(tmp_path: Path) -> None:
    run_id = _write_run(tmp_path)
    app = create_app(log_dir=tmp_path)
    client = TestClient(app)

    runs_response = client.get("/api/runs")
    assert runs_response.status_code == 200
    runs = runs_response.json()
    assert any(run["run_id"] == run_id for run in runs)

    topo = client.get(f"/api/runs/{run_id}/topology", params={"max_nodes": 10})
    assert topo.status_code == 200
    topo_json = topo.json()
    assert len(topo_json["nodes"]) >= 3
    assert len(topo_json["edges"]) >= 2

    subgraph = client.get(
        f"/api/runs/{run_id}/subgraph",
        params={"focus": "n1", "hops": 1, "max_nodes": 10},
    )
    assert subgraph.status_code == 200
    subgraph_json = subgraph.json()
    assert {"n1", "n2"}.issubset({node["id"] for node in subgraph_json["nodes"]})

    events = client.get(f"/api/runs/{run_id}/events", params={"limit": 2})
    assert events.status_code == 200
    events_json = events.json()
    assert events_json["events"][0]["event_type"] in {"topology", "BellPairGenerated"}

    metrics = client.get("/api/metrics")
    assert metrics.status_code == 200
    assert metrics.json()["runs_discovered"] >= 1

    root_metrics = client.get("/metrics")
    assert root_metrics.status_code == 200
    assert root_metrics.json()["runs_discovered"] >= 1


def test_api_infers_topology_from_connection_requests(tmp_path: Path) -> None:
    run_id = _write_connection_run(tmp_path)
    app = create_app(log_dir=tmp_path)
    client = TestClient(app)

    topo = client.get(f"/api/runs/{run_id}/topology", params={"max_nodes": 10})
    assert topo.status_code == 200
    topo_json = topo.json()
    assert {"1", "3"} == {node["id"] for node in topo_json["nodes"]}
    assert ("1", "3") in {(edge["src"], edge["dst"]) for edge in topo_json["edges"]}

    events = client.get(f"/api/runs/{run_id}/events", params={"limit": 5})
    assert events.status_code == 200
    assert events.json()["events"][0]["payload"]["actual_dest_addr"] == 3


def test_api_ignores_nested_non_run_logs(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_123"
    run_dir.mkdir()
    (run_dir / "stdout.log").write_text("stdout only\n", encoding="utf-8")
    (run_dir / "stderr.log").write_text("stderr only\n", encoding="utf-8")
    (run_dir / "run.jsonl").write_text('{"simtime":0.1,"event_type":"noop"}\n', encoding="utf-8")

    app = create_app(log_dir=tmp_path)
    client = TestClient(app)

    runs_response = client.get("/api/runs")
    assert runs_response.status_code == 200
    run_ids = {run["run_id"] for run in runs_response.json()}
    assert run_ids == {"run_123"}
