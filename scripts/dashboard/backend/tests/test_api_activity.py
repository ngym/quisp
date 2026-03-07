from __future__ import annotations

import json

from fastapi.testclient import TestClient

from scripts.dashboard.backend.app.main import create_app


def _write_run(log_dir, run_id: str, lines: list[dict]) -> None:
    run_dir = log_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / 'run.jsonl'
    payload = '\n'.join(json.dumps(line) for line in lines) + '\n'
    path.write_text(payload, encoding='utf-8')


def test_activity_endpoints(tmp_path):
    _write_run(
        tmp_path,
        'run_b',
        [
            {"event_type": "topology_snapshot", "sim_time": 0.0, "source": "1", "event_payload": {"nodes": [{"id": "1", "x": 0, "y": 0}, {"id": "2", "x": 100, "y": 0}], "edges": [{"src": "1", "dst": "2"}]}},
            {"event_type": "flying_qubit_sent", "sim_time": 1.0, "source": "1", "event_payload": {"node_id": 1, "dst_node_id": 2}},
            {"event_type": "flying_qubit_loss", "sim_time": 1.4, "source": "1", "event_payload": {"node_id": 1, "dst_node_id": 2}},
        ],
    )
    app = create_app(log_dir=tmp_path, workspace_root=tmp_path)
    with TestClient(app) as client:
        activity = client.get('/api/runs/run_b/activity')
        assert activity.status_code == 200
        payload = activity.json()
        assert payload['run_id'] == 'run_b'
        assert 'global_totals' in payload
        assert 'view_node_activity' in payload

        summary = client.get('/api/runs/run_b/activity/summary')
        assert summary.status_code == 200
        summary_payload = summary.json()
        assert summary_payload['run_id'] == 'run_b'
        assert 'visible_event_density' in summary_payload
