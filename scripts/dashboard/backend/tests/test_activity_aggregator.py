from __future__ import annotations

import asyncio
import json

from scripts.dashboard.backend.app.activity_aggregator import ActivityAggregator
from scripts.dashboard.backend.app.store import RunStore


def _write_run(log_dir, run_id: str, lines: list[dict]) -> None:
    run_dir = log_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / 'run.jsonl'
    payload = '\n'.join(json.dumps(line) for line in lines) + '\n'
    path.write_text(payload, encoding='utf-8')


def test_activity_snapshot_and_summary(tmp_path):
    _write_run(
        tmp_path,
        'run_a',
        [
            {"event_type": "topology_snapshot", "sim_time": 0.0, "source": "1", "event_payload": {"nodes": [{"id": "1", "x": 0, "y": 0}, {"id": "2", "x": 100, "y": 0}], "edges": [{"src": "1", "dst": "2"}]}},
            {"event_type": "experiment_request_submitted", "sim_time": 1.0, "source": "1", "event_payload": {"src_addr": 1, "dst_addr": 2, "connection_session_id": 10, "connection_attempt": 1}},
            {"event_type": "experiment_request_setup_accepted", "sim_time": 1.5, "source": "1", "event_payload": {"src_addr": 1, "dst_addr": 2, "connection_session_id": 10, "connection_attempt": 1}},
            {"event_type": "BellPairGenerated", "sim_time": 2.0, "source": "1", "event_payload": {"partner_addr": 2}},
            {"event_type": "flying_qubit_loss", "sim_time": 2.4, "source": "1", "event_payload": {"node_id": 1, "dst_node_id": 2}},
        ],
    )
    store = RunStore(tmp_path)
    asyncio.run(store.discover_runs())
    aggregator = ActivityAggregator(store=store)

    snapshot = asyncio.run(aggregator.build_snapshot('run_a', window_s=1.0, lookback_s=5.0))
    assert snapshot.run_id == 'run_a'
    assert snapshot.global_totals.visible_event_density is not None
    assert any(node.id == '1' for node in snapshot.view_node_activity)
    assert any(edge.src == '1' and edge.dst == '2' for edge in snapshot.view_edge_activity)

    summary = asyncio.run(aggregator.build_summary('run_a', bin_s=1.0))
    assert summary.run_id == 'run_a'
    assert summary.visible_event_density.count >= 1
    assert summary.global_counts_by_class['requests'] >= 2
