from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
import json
import math

from .experiment_metrics import summarize_distribution
from .experiment_models import (
    ArtifactPaths,
    ExperimentComparisonResponse,
    ExperimentRunSummary,
    ExperimentTimeseries,
    ExperimentTimeseriesPoint,
)
from .log_reader import parse_log_event


class ExperimentAggregator:
    DEFAULT_METRICS = [
        "setup_success_ratio",
        "bellpair_generation_rate_per_s",
        "setup_latency_s",
        "link_fidelity",
        "link_bellpair_rate_per_s",
        "photon_loss_rate_per_s",
        "bellpair_inventory_peak",
        "bellpair_inventory_mean",
    ]

    def __init__(self, *, log_dir: Path) -> None:
        self.log_dir = log_dir

    def _run_dir(self, run_id: str) -> Path:
        return self.log_dir / run_id

    def _summary_path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "experiment_summary.json"

    def _timeseries_path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "experiment_timeseries.jsonl"

    def _spec_path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "experiment_spec.json"

    def _resolved_overrides_path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "resolved_overrides.json"

    def _log_path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "run.jsonl"

    def _read_json(self, path: Path, default: Any) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return default

    def _iter_events(self, run_id: str) -> Iterable[Any]:
        log_path = self._log_path(run_id)
        if not log_path.exists():
            return []
        with log_path.open("r", encoding="utf-8", errors="replace") as handle:
            for cursor, raw_line in enumerate(handle):
                yield parse_log_event(raw_line, run_id=run_id, cursor=cursor)

    @staticmethod
    def _request_key(payload: Dict[str, Any]) -> str:
        session = payload.get("connection_session_id", -1)
        attempt = payload.get("connection_attempt", 0)
        if session not in {None, "", -1, "-1"}:
            return f"session:{session}:attempt:{attempt}"
        src = payload.get("src_addr", payload.get("actual_src_addr", payload.get("source", "")))
        dst = payload.get("dst_addr", payload.get("actual_dest_addr", ""))
        return f"{src}->{dst}:{session}:{attempt}"

    @staticmethod
    def _bin_index(sim_time: float, bin_s: float) -> int:
        if not math.isfinite(sim_time) or sim_time < 0:
            return 0
        return int(sim_time // bin_s)

    def _collect(self, run_id: str, *, status: str = "", status_message: Optional[str] = None, bin_s: float = 1.0) -> Dict[str, Any]:
        request_submitted_times: Dict[str, float] = {}
        request_terminal_keys: set[str] = set()
        request_submitted_count = 0
        request_setup_success_count = 0
        request_setup_reject_count = 0
        setup_latencies: list[float] = []
        bellpair_generated_count = 0
        bellpair_erased_count = 0
        photon_loss_count = 0
        failure_reason_breakdown: Dict[str, int] = defaultdict(int)
        inventory = 0
        inventory_peak = 0
        inventory_area = 0.0
        inventory_last_time = 0.0
        link_fidelity_samples: list[float] = []
        link_rate_samples: list[float] = []
        link_quality_latest: Dict[str, Dict[str, Any]] = {}
        timeseries_counts: Dict[str, Dict[int, float]] = defaultdict(lambda: defaultdict(float))
        timeseries_samples: Dict[str, Dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
        max_sim_time = 0.0

        for event in self._iter_events(run_id):
            payload = dict(event.payload or {})
            sim_time = float(event.sim_time or 0.0)
            max_sim_time = max(max_sim_time, sim_time)

            if sim_time >= inventory_last_time:
                inventory_area += inventory * (sim_time - inventory_last_time)
                inventory_last_time = sim_time

            if event.event_type == "experiment_request_submitted":
                key = self._request_key(payload)
                request_submitted_times[key] = sim_time
                request_submitted_count += 1
                timeseries_counts["request_submit_rate"][self._bin_index(sim_time, bin_s)] += 1
                continue

            if event.event_type == "experiment_request_setup_accepted":
                key = self._request_key(payload)
                if key not in request_terminal_keys:
                    request_terminal_keys.add(key)
                    request_setup_success_count += 1
                    timeseries_counts["request_setup_success_rate"][self._bin_index(sim_time, bin_s)] += 1
                    if key in request_submitted_times:
                        setup_latencies.append(max(0.0, sim_time - request_submitted_times[key]))
                continue

            if event.event_type == "experiment_request_setup_rejected":
                key = self._request_key(payload)
                if key not in request_terminal_keys:
                    request_terminal_keys.add(key)
                    request_setup_reject_count += 1
                    reason = str(payload.get("reason") or "unknown")
                    failure_reason_breakdown[reason] += 1
                    if key in request_submitted_times:
                        setup_latencies.append(max(0.0, sim_time - request_submitted_times[key]))
                continue

            if event.event_type == "BellPairGenerated":
                bellpair_generated_count += 1
                inventory += 1
                inventory_peak = max(inventory_peak, inventory)
                timeseries_counts["bellpair_generation_rate"][self._bin_index(sim_time, bin_s)] += 1
                timeseries_counts["bellpair_inventory_total"][self._bin_index(sim_time, bin_s)] = inventory
                continue

            if event.event_type == "BellPairErased":
                bellpair_erased_count += 1
                inventory = max(0, inventory - 1)
                timeseries_counts["bellpair_inventory_total"][self._bin_index(sim_time, bin_s)] = inventory
                continue

            if event.event_type == "flying_qubit_loss":
                photon_loss_count += 1
                timeseries_counts["photon_loss_rate"][self._bin_index(sim_time, bin_s)] += 1
                continue

            if event.event_type == "experiment_link_quality_sample":
                fidelity = payload.get("fidelity")
                bellpair_per_sec = payload.get("bellpair_per_sec")
                partner_addr = payload.get("partner_addr")
                qnic_index = payload.get("qnic_index")
                if fidelity is not None:
                    link_fidelity_samples.append(float(fidelity))
                    timeseries_samples["link_fidelity_avg"][self._bin_index(sim_time, bin_s)].append(float(fidelity))
                if bellpair_per_sec is not None:
                    link_rate_samples.append(float(bellpair_per_sec))
                key = f"{partner_addr}:{qnic_index}"
                link_quality_latest[key] = {
                    "partner_addr": partner_addr,
                    "qnic_index": qnic_index,
                    "distance_km": payload.get("distance_km"),
                    "link_cost": payload.get("link_cost"),
                    "fidelity": fidelity,
                    "bellpair_per_sec": bellpair_per_sec,
                }

        if status == "failed" and status_message:
            failure_reason_breakdown["run_failure"] += 1

        sim_span = max(max_sim_time, inventory_last_time, 0.0)
        inventory_mean = (inventory_area / sim_span) if sim_span > 0 else float(inventory)
        setup_success_ratio = (request_setup_success_count / request_submitted_count) if request_submitted_count else None
        generation_rate = (bellpair_generated_count / sim_span) if sim_span > 0 else None
        photon_loss_rate = (photon_loss_count / sim_span) if sim_span > 0 else None

        return {
            "request_submitted_count": request_submitted_count,
            "request_setup_success_count": request_setup_success_count,
            "request_setup_reject_count": request_setup_reject_count,
            "setup_success_ratio": setup_success_ratio,
            "setup_latency_s": summarize_distribution(setup_latencies).model_dump(),
            "bellpair_generated_count": bellpair_generated_count,
            "bellpair_erased_count": bellpair_erased_count,
            "bellpair_generation_rate_per_s": generation_rate,
            "bellpair_inventory_peak": inventory_peak,
            "bellpair_inventory_mean": inventory_mean,
            "photon_loss_count": photon_loss_count,
            "photon_loss_rate_per_s": photon_loss_rate,
            "link_fidelity": summarize_distribution(link_fidelity_samples).model_dump(),
            "link_bellpair_rate_per_s": summarize_distribution(link_rate_samples).model_dump(),
            "failure_reason_breakdown": dict(sorted(failure_reason_breakdown.items())),
            "link_quality_latest": sorted(link_quality_latest.values(), key=lambda item: (item.get("partner_addr"), item.get("qnic_index"))),
            "timeseries_counts": timeseries_counts,
            "timeseries_samples": timeseries_samples,
        }

    def build_summary(self, run_id: str, *, display_name: str, status: str, experiment_profile_id: Optional[str] = None, status_message: Optional[str] = None) -> ExperimentRunSummary:
        spec = self._read_json(self._spec_path(run_id), {})
        resolved_overrides = self._read_json(self._resolved_overrides_path(run_id), {})
        collected = self._collect(run_id, status=status, status_message=status_message, bin_s=1.0)
        summary = ExperimentRunSummary(
            run_id=run_id,
            display_name=display_name,
            status=status,
            experiment_profile_id=experiment_profile_id or spec.get("experiment_profile_id"),
            parameter_values=dict(spec.get("parameter_values") or {}),
            resolved_overrides=dict(resolved_overrides or {}),
            requested_metrics=list(spec.get("requested_metrics") or self.DEFAULT_METRICS),
            metric_summaries={
                "request_submitted_count": {"kind": "scalar", "value": collected["request_submitted_count"], "unit": "count"},
                "request_setup_success_count": {"kind": "scalar", "value": collected["request_setup_success_count"], "unit": "count"},
                "request_setup_reject_count": {"kind": "scalar", "value": collected["request_setup_reject_count"], "unit": "count"},
                "setup_success_ratio": {"kind": "scalar", "value": collected["setup_success_ratio"], "unit": "ratio", "unavailable": collected["setup_success_ratio"] is None},
                "setup_latency_s": {"kind": "distribution", **collected["setup_latency_s"], "unit": "s"},
                "bellpair_generated_count": {"kind": "scalar", "value": collected["bellpair_generated_count"], "unit": "count"},
                "bellpair_erased_count": {"kind": "scalar", "value": collected["bellpair_erased_count"], "unit": "count"},
                "bellpair_generation_rate_per_s": {"kind": "scalar", "value": collected["bellpair_generation_rate_per_s"], "unit": "/s", "unavailable": collected["bellpair_generation_rate_per_s"] is None},
                "bellpair_inventory_peak": {"kind": "scalar", "value": collected["bellpair_inventory_peak"], "unit": "count"},
                "bellpair_inventory_mean": {"kind": "scalar", "value": collected["bellpair_inventory_mean"], "unit": "count"},
                "photon_loss_count": {"kind": "scalar", "value": collected["photon_loss_count"], "unit": "count"},
                "photon_loss_rate_per_s": {"kind": "scalar", "value": collected["photon_loss_rate_per_s"], "unit": "/s", "unavailable": collected["photon_loss_rate_per_s"] is None},
                "link_fidelity": {"kind": "distribution", **collected["link_fidelity"], "unit": "ratio"},
                "link_bellpair_rate_per_s": {"kind": "distribution", **collected["link_bellpair_rate_per_s"], "unit": "/s"},
            },
            failure_reason_breakdown=collected["failure_reason_breakdown"],
            link_quality_latest=collected["link_quality_latest"],
            timeseries_metric_ids=[
                "request_submit_rate",
                "request_setup_success_rate",
                "bellpair_inventory_total",
                "bellpair_generation_rate",
                "photon_loss_rate",
                "link_fidelity_avg",
            ],
            artifacts=ArtifactPaths(
                spec_path=str(self._spec_path(run_id)),
                summary_path=str(self._summary_path(run_id)),
                timeseries_path=str(self._timeseries_path(run_id)),
            ),
        )
        self._summary_path(run_id).write_text(
            json.dumps(summary.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return summary

    def build_timeseries(self, run_id: str, *, metric_id: str, bin_s: float, display_name: str, status: str, experiment_profile_id: Optional[str] = None, status_message: Optional[str] = None) -> ExperimentTimeseries:
        collected = self._collect(run_id, status=status, status_message=status_message, bin_s=bin_s)
        counts = collected["timeseries_counts"]
        samples = collected["timeseries_samples"]
        points: list[ExperimentTimeseriesPoint] = []
        unavailable = False

        if metric_id in {"request_submit_rate", "request_setup_success_rate", "bellpair_generation_rate", "photon_loss_rate"}:
            source = counts.get(metric_id, {})
            for bin_index in sorted(source):
                points.append(
                    ExperimentTimeseriesPoint(
                        bin_index=bin_index,
                        sim_time_start=bin_index * bin_s,
                        sim_time_end=(bin_index + 1) * bin_s,
                        value=float(source[bin_index]) / bin_s,
                    )
                )
        elif metric_id == "bellpair_inventory_total":
            source = counts.get(metric_id, {})
            for bin_index in sorted(source):
                points.append(
                    ExperimentTimeseriesPoint(
                        bin_index=bin_index,
                        sim_time_start=bin_index * bin_s,
                        sim_time_end=(bin_index + 1) * bin_s,
                        value=float(source[bin_index]),
                    )
                )
        elif metric_id == "link_fidelity_avg":
            source = samples.get(metric_id, {})
            for bin_index in sorted(source):
                values = source[bin_index]
                if not values:
                    continue
                points.append(
                    ExperimentTimeseriesPoint(
                        bin_index=bin_index,
                        sim_time_start=bin_index * bin_s,
                        sim_time_end=(bin_index + 1) * bin_s,
                        value=sum(values) / len(values),
                    )
                )
        else:
            unavailable = True

        result = ExperimentTimeseries(run_id=run_id, metric_id=metric_id, bin_s=bin_s, unavailable=unavailable, points=points)
        path = self._timeseries_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        existing: list[str] = []
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as handle:
                    existing = [line.rstrip("\n") for line in handle if line.strip()]
            except OSError:
                existing = []
        filtered = []
        for line in existing:
            try:
                payload = json.loads(line)
            except (TypeError, ValueError):
                continue
            if payload.get("metric_id") == metric_id and float(payload.get("bin_s", 0.0)) == float(bin_s):
                continue
            filtered.append(json.dumps(payload, ensure_ascii=False))
        filtered.append(json.dumps(result.model_dump(), ensure_ascii=False))
        path.write_text("\n".join(filtered) + ("\n" if filtered else ""), encoding="utf-8")
        return result

    def compare(self, run_summaries: list[ExperimentRunSummary], metric_ids: list[str]) -> ExperimentComparisonResponse:
        warnings: list[str] = []
        if not metric_ids:
            metric_ids = self.DEFAULT_METRICS
        rows: list[Dict[str, Any]] = []
        for metric_id in metric_ids:
            row: Dict[str, Any] = {"metric_id": metric_id}
            for summary in run_summaries:
                metric = summary.metric_summaries.get(metric_id)
                if not metric:
                    row[summary.run_id] = "unavailable"
                    continue
                if metric.get("kind") == "distribution":
                    row[summary.run_id] = {
                        "mean": metric.get("mean"),
                        "p50": metric.get("p50"),
                        "p95": metric.get("p95"),
                        "p99": metric.get("p99"),
                    }
                else:
                    row[summary.run_id] = metric.get("value")
            rows.append(row)
        return ExperimentComparisonResponse(
            runs=[
                {
                    "run_id": summary.run_id,
                    "display_name": summary.display_name,
                    "profile_id": summary.experiment_profile_id,
                    "status": summary.status,
                }
                for summary in run_summaries
            ],
            metric_rows=rows,
            warnings=warnings,
        )
