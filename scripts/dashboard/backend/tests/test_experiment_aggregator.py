from __future__ import annotations

import json

from scripts.dashboard.backend.app.experiment_aggregator import ExperimentAggregator


def _write_run_artifacts(base_dir, run_id: str) -> None:
    run_dir = base_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "experiment_spec.json").write_text(
        json.dumps(
            {
                "experiment_profile_id": "two_node_mim_smoke",
                "parameter_values": {"traffic.request_rate_hz": 10},
                "requested_metrics": ["setup_success_ratio", "setup_latency_s"],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "resolved_overrides.json").write_text(
        json.dumps({"*.source.app.request_generation_interval": "0.1s"}),
        encoding="utf-8",
    )


def _write_log(base_dir, run_id: str, events: list[dict]) -> None:
    run_dir = base_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )


def test_experiment_aggregator_builds_summary_and_timeseries(tmp_path):
    run_id = "run_a"
    _write_run_artifacts(tmp_path, run_id)
    _write_log(
        tmp_path,
        run_id,
        [
            {
                "event_type": "experiment_request_submitted",
                "simtime": 0.0,
                "event_payload": {
                    "src_addr": 1,
                    "dst_addr": 2,
                    "connection_session_id": 10,
                    "connection_attempt": 0,
                },
            },
            {
                "event_type": "experiment_request_setup_accepted",
                "simtime": 2.0,
                "event_payload": {
                    "src_addr": 1,
                    "dst_addr": 2,
                    "connection_session_id": 10,
                    "connection_attempt": 0,
                    "ruleset_id": 7,
                },
            },
            {"event_type": "BellPairGenerated", "simtime": 3.0, "event_payload": {}},
            {"event_type": "BellPairErased", "simtime": 4.0, "event_payload": {}},
            {"event_type": "flying_qubit_loss", "simtime": 5.0, "event_payload": {"node_id": 1}},
            {
                "event_type": "experiment_link_quality_sample",
                "simtime": 6.0,
                "event_payload": {
                    "partner_addr": 2,
                    "qnic_index": 0,
                    "distance_km": 10,
                    "link_cost": 2.5,
                    "fidelity": 0.88,
                    "bellpair_per_sec": 1.5,
                },
            },
        ],
    )

    aggregator = ExperimentAggregator(log_dir=tmp_path)
    summary = aggregator.build_summary(
        run_id,
        display_name="run a",
        status="finished",
        experiment_profile_id="two_node_mim_smoke",
    )

    assert summary.metric_summaries["request_submitted_count"]["value"] == 1
    assert summary.metric_summaries["request_setup_success_count"]["value"] == 1
    assert summary.metric_summaries["setup_success_ratio"]["value"] == 1.0
    assert summary.metric_summaries["setup_latency_s"]["mean"] == 2.0
    assert summary.metric_summaries["bellpair_inventory_peak"]["value"] == 1
    assert summary.metric_summaries["photon_loss_count"]["value"] == 1
    assert summary.metric_summaries["link_fidelity"]["mean"] == 0.88
    assert summary.link_quality_latest[0]["partner_addr"] == 2

    series = aggregator.build_timeseries(
        run_id,
        metric_id="request_submit_rate",
        bin_s=1.0,
        display_name="run a",
        status="finished",
        experiment_profile_id="two_node_mim_smoke",
    )
    assert series.unavailable is False
    assert len(series.points) == 1
    assert series.points[0].value == 1.0


def test_experiment_aggregator_compare_marks_missing_metrics_unavailable(tmp_path):
    aggregator = ExperimentAggregator(log_dir=tmp_path)
    _write_run_artifacts(tmp_path, "run_a")
    _write_run_artifacts(tmp_path, "run_b")
    _write_log(
        tmp_path,
        "run_a",
        [
            {
                "event_type": "experiment_request_submitted",
                "simtime": 0.0,
                "event_payload": {"src_addr": 1, "dst_addr": 2, "connection_session_id": 1, "connection_attempt": 0},
            },
            {
                "event_type": "experiment_request_setup_accepted",
                "simtime": 1.0,
                "event_payload": {"src_addr": 1, "dst_addr": 2, "connection_session_id": 1, "connection_attempt": 0},
            },
        ],
    )
    _write_log(tmp_path, "run_b", [])

    summary_a = aggregator.build_summary("run_a", display_name="A", status="finished")
    summary_b = aggregator.build_summary("run_b", display_name="B", status="failed", status_message="boom")
    comparison = aggregator.compare([summary_a, summary_b], ["setup_success_ratio", "link_fidelity"])

    assert [run["run_id"] for run in comparison.runs] == ["run_a", "run_b"]
    rows = {row["metric_id"]: row for row in comparison.metric_rows}
    assert rows["setup_success_ratio"]["run_a"] == 1.0
    assert rows["link_fidelity"]["run_b"]["mean"] is None
