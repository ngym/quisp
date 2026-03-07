from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple
import math

from .activity_models import (
    ActivityBin,
    ActivityEdgeHeat,
    ActivityGlobalTotals,
    ActivityNodeHeat,
    ActivitySnapshot,
    KeyMoment,
    PeakWindow,
    RunActivitySummary,
    ActivityDensitySummary,
)
from .models import DashboardEvent
from .store import RunStore


REQUEST_EVENT_TYPES = {
    "connectionsetuprequest",
    "connectionsetupresponse",
    "rejectconnectionsetuprequest",
    "experiment_request_submitted",
    "experiment_request_setup_accepted",
    "experiment_request_setup_rejected",
}
BELLPAIR_EVENT_TYPES = {"bellpairgenerated", "bellpairerased"}
FLYING_EVENT_TYPES = {"flying_qubit_generated", "flying_qubit_emit", "flying_qubit_sent"}
LOSS_EVENT_TYPES = {"flying_qubit_loss"}
LINK_QUALITY_EVENT_TYPES = {"experiment_link_quality_sample"}
CLASSICAL_PACKET_FAMILIES = (
    "connection_setup",
    "ruleset_forwarding",
    "swapping",
    "purification",
    "link_generation",
    "tomography",
    "routing",
    "unknown",
)
ALL_ACTIVITY_CLASSES = CLASSICAL_PACKET_FAMILIES + ("bellpairs", "flying", "loss", "link_quality")


@dataclass(frozen=True)
class _ResolvedEndpoint:
    src: str = ""
    dst: str = ""
    node_id: str = ""


class ActivityAggregator:
    def __init__(self, *, store: RunStore) -> None:
        self.store = store
        self._snapshot_cache: dict[tuple[Any, ...], ActivitySnapshot] = {}
        self._summary_cache: dict[tuple[Any, ...], RunActivitySummary] = {}

    @staticmethod
    def _normalize_classes(classes: Optional[Sequence[str]]) -> tuple[str, ...]:
        if not classes:
            return tuple()
        normalized = []
        for value in classes:
            text = str(value or "").strip().lower()
            if text in ALL_ACTIVITY_CLASSES and text not in normalized:
                normalized.append(text)
        return tuple(normalized)

    @staticmethod
    def _event_class(event: DashboardEvent) -> str:
        event_type = str(event.event_type or "").strip().lower()
        payload = event.payload if isinstance(event.payload, dict) else {}
        protocol_family = str(payload.get("protocol_family") or "").strip().lower()
        if event_type in {"classical_packet_hop", "classical_packet_deliver_local"}:
            return protocol_family if protocol_family in CLASSICAL_PACKET_FAMILIES else "unknown"
        if event_type in REQUEST_EVENT_TYPES:
            return "summary"
        if event_type in BELLPAIR_EVENT_TYPES:
            return "bellpairs"
        if event_type in FLYING_EVENT_TYPES:
            return "flying"
        if event_type in LOSS_EVENT_TYPES:
            return "loss"
        if event_type in LINK_QUALITY_EVENT_TYPES:
            return "link_quality"
        return "unknown"

    @staticmethod
    def _parse_node(value: Any) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        return text

    def _resolve_endpoints(self, event: DashboardEvent) -> _ResolvedEndpoint:
        payload = event.payload if isinstance(event.payload, dict) else {}
        event_type = str(event.event_type or "").strip().lower()
        source = self._parse_node(
            payload.get("src_node_id")
            or payload.get("actual_src_addr")
            or payload.get("src_addr")
            or payload.get("src")
            or payload.get("source")
            or payload.get("node_id")
            or payload.get("partner_addr")
            or event.source
        )
        destination = self._parse_node(
            payload.get("dst_node_id")
            or payload.get("actual_dest_addr")
            or payload.get("dst_addr")
            or payload.get("dst_node_id")
            or payload.get("dst")
            or payload.get("destination")
            or payload.get("to")
            or payload.get("partner_addr")
        )
        if event_type in {"bellpairgenerated", "bellpairerased"}:
            source = source or self._parse_node(payload.get("node_id") or event.source)
            destination = destination or self._parse_node(payload.get("partner_addr"))
        if event_type == "experiment_link_quality_sample":
            source = source or self._parse_node(payload.get("node_id"))
            destination = destination or self._parse_node(payload.get("partner_addr"))
        node_id = source or destination
        return _ResolvedEndpoint(src=source, dst=destination, node_id=node_id)

    @staticmethod
    def _canonical_edge(src: str, dst: str) -> tuple[str, str]:
        if not src or not dst:
            return ("", "")
        return tuple(sorted((src, dst)))

    @staticmethod
    def _intensity(total_count: int) -> float:
        if total_count <= 0:
            return 0.0
        return min(1.0, math.log1p(total_count) / math.log1p(20))

    @staticmethod
    def _dominant_class(counts: Dict[str, int]) -> str:
        filtered = [(key, value) for key, value in counts.items() if value > 0]
        if not filtered:
            return "mixed"
        filtered.sort(key=lambda item: (-item[1], item[0]))
        return filtered[0][0]

    @staticmethod
    def _summarize_numeric(values: Sequence[float]) -> ActivityDensitySummary:
        if not values:
            return ActivityDensitySummary(count=0)
        ordered = sorted(float(value) for value in values)

        def percentile(p: float) -> float:
            if len(ordered) == 1:
                return ordered[0]
            rank = (len(ordered) - 1) * p
            lo = math.floor(rank)
            hi = math.ceil(rank)
            if lo == hi:
                return ordered[lo]
            left = ordered[lo]
            right = ordered[hi]
            return left + (right - left) * (rank - lo)

        return ActivityDensitySummary(
            count=len(ordered),
            mean=sum(ordered) / len(ordered),
            min=ordered[0],
            max=ordered[-1],
            p50=percentile(0.50),
            p95=percentile(0.95),
            p99=percentile(0.99),
        )

    async def build_snapshot(
        self,
        run_id: str,
        *,
        anchor_cursor: Optional[int] = None,
        window_s: float = 1.0,
        lookback_s: float = 15.0,
        classes: Optional[Sequence[str]] = None,
        focus: Optional[str] = None,
        hops: int = 0,
        max_nodes: int = 3000,
        node_regex: Optional[str] = None,
        run_status: Optional[str] = None,
        status_message: Optional[str] = None,
    ) -> ActivitySnapshot:
        normalized_classes = self._normalize_classes(classes)
        latest_cursor = self.store.get_latest_cursor(run_id)
        target_cursor = latest_cursor if anchor_cursor is None else max(0, min(anchor_cursor, latest_cursor))
        cache_key = (
            run_id,
            target_cursor // 100,
            round(window_s, 3),
            round(lookback_s, 3),
            normalized_classes,
            focus or "",
            hops,
            max_nodes,
            node_regex or "",
            run_status or "",
            status_message or "",
        )
        cached = self._snapshot_cache.get(cache_key)
        if cached is not None:
            return cached

        await self.store.refresh_run(run_id)
        anchor_sim_time = None
        if latest_cursor >= 0:
            events_at_anchor = self.store.get_events_between_cursors(run_id, target_cursor, target_cursor)
            if events_at_anchor:
                anchor_sim_time = events_at_anchor[0].sim_time
        if anchor_sim_time is None:
            snapshot = ActivitySnapshot(
                run_id=run_id,
                anchor_cursor=target_cursor,
                live_edge_cursor=latest_cursor,
                anchor_sim_time=None,
                window_s=window_s,
                lookback_s=lookback_s,
                global_totals=ActivityGlobalTotals(),
                bins=[],
                view_node_activity=[],
                view_edge_activity=[],
                key_moments=[],
            )
            self._snapshot_cache[cache_key] = snapshot
            return snapshot

        start_sim_time = max(0.0, anchor_sim_time - lookback_s)
        start_cursor = self.store.find_cursor_at_or_before_sim_time(run_id, start_sim_time)
        window_events = self.store.get_events_between_cursors(run_id, start_cursor, target_cursor)
        filtered_events = []
        for event in window_events:
            event_class = self._event_class(event)
            if event_class not in ALL_ACTIVITY_CLASSES:
                continue
            if normalized_classes and event_class not in normalized_classes:
                continue
            filtered_events.append(event)

        subgraph = await self.store.get_subgraph(
            run_id,
            focus=focus,
            hops=hops,
            max_nodes=max_nodes,
            node_regex=node_regex,
        )
        view_nodes = {str(node.get("id")) for node in subgraph.get("nodes", [])}
        raw_view_edges = [
            (str(edge.get("src")), str(edge.get("dst")))
            for edge in subgraph.get("edges", [])
            if edge.get("src") is not None and edge.get("dst") is not None
        ]
        view_edges: list[tuple[str, str]] = []
        view_edge_lookup: set[tuple[str, str]] = set()
        for src, dst in raw_view_edges:
            canonical_edge = self._canonical_edge(src, dst)
            if canonical_edge == ("", "") or canonical_edge in view_edge_lookup:
                continue
            view_edge_lookup.add(canonical_edge)
            view_edges.append((src, dst))

        sim_span = max(0.0, anchor_sim_time - start_sim_time)
        bucket_count = max(1, int(math.ceil(max(sim_span, window_s) / max(window_s, 1e-6))))
        bins: list[dict[str, Any]] = []
        for index in range(bucket_count):
            bin_start = start_sim_time + index * window_s
            if bin_start >= anchor_sim_time:
                break
            bin_end = min(anchor_sim_time, bin_start + window_s)
            bins.append(
                {
                    "start_sim_time": bin_start,
                    "end_sim_time": bin_end,
                    "count": 0,
                    "request_submit_rate": 0.0,
                    "request_accept_rate": 0.0,
                    "request_reject_rate": 0.0,
                    "bellpair_generation_rate": 0.0,
                    "photon_loss_rate": 0.0,
                    "nodes": set(),
                    "edges": set(),
                    "counts_by_class": defaultdict(int),
                }
            )

        global_counts_by_class: Dict[str, int] = defaultdict(int)
        global_nodes: set[str] = set()
        global_edges: set[tuple[str, str]] = set()
        view_node_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        view_edge_counts: Dict[tuple[str, str], Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        key_moments: list[KeyMoment] = []

        for event in window_events:
            event_class = self._event_class(event)
            endpoints = self._resolve_endpoints(event)
            bucket = None
            if sim_span > 0 and bins:
                offset = max(0.0, event.sim_time - start_sim_time)
                bucket_index = min(len(bins) - 1, int(offset // max(window_s, 1e-6)))
                bucket = bins[bucket_index]

            if event_class in ALL_ACTIVITY_CLASSES and (not normalized_classes or event_class in normalized_classes):
                global_counts_by_class[event_class] += 1
                if endpoints.src:
                    global_nodes.add(endpoints.src)
                if endpoints.dst:
                    global_nodes.add(endpoints.dst)
                if endpoints.src and endpoints.dst and endpoints.src != endpoints.dst:
                    global_edges.add(self._canonical_edge(endpoints.src, endpoints.dst))

                if bucket is not None:
                    bucket["count"] += 1
                    bucket["counts_by_class"][event_class] += 1
                    if endpoints.src:
                        bucket["nodes"].add(endpoints.src)
                    if endpoints.dst:
                        bucket["nodes"].add(endpoints.dst)
                    if endpoints.src and endpoints.dst and endpoints.src != endpoints.dst:
                        bucket["edges"].add(self._canonical_edge(endpoints.src, endpoints.dst))
                    if event.event_type == "BellPairGenerated":
                        bucket["bellpair_generation_rate"] += 1.0
                    elif event.event_type == "flying_qubit_loss":
                        bucket["photon_loss_rate"] += 1.0

                if endpoints.src and endpoints.src in view_nodes:
                    view_node_counts[endpoints.src][event_class] += 1
                if endpoints.dst and endpoints.dst in view_nodes:
                    view_node_counts[endpoints.dst][event_class] += 1
                edge_key = self._canonical_edge(endpoints.src, endpoints.dst)
                if edge_key != ("", "") and edge_key in view_edge_lookup:
                    view_edge_counts[edge_key][event_class] += 1

            if bucket is not None:
                if event.event_type == "experiment_request_submitted":
                    bucket["request_submit_rate"] += 1.0
                elif event.event_type == "experiment_request_setup_accepted":
                    bucket["request_accept_rate"] += 1.0
                elif event.event_type == "experiment_request_setup_rejected":
                    bucket["request_reject_rate"] += 1.0

            if event.event_type == "experiment_request_setup_rejected":
                reason = str((event.payload or {}).get("reason") or "request rejected")
                key_moments.append(KeyMoment(cursor=event.cursor or 0, sim_time=event.sim_time, event_type=event.event_type, label=reason, severity="bad", src=endpoints.src or None, dst=endpoints.dst or None, node_id=endpoints.node_id or None))
            elif event.event_type == "experiment_request_setup_accepted":
                key_moments.append(KeyMoment(cursor=event.cursor or 0, sim_time=event.sim_time, event_type=event.event_type, label="setup accepted", severity="info", src=endpoints.src or None, dst=endpoints.dst or None, node_id=endpoints.node_id or None))
            elif event.event_type == "experiment_link_quality_sample":
                fidelity = float((event.payload or {}).get("fidelity") or 0.0)
                if fidelity < 0.6:
                    key_moments.append(KeyMoment(cursor=event.cursor or 0, sim_time=event.sim_time, event_type=event.event_type, label=f"low fidelity {fidelity:.3f}", severity="warn", src=endpoints.src or None, dst=endpoints.dst or None, node_id=endpoints.node_id or None))

        for bucket in bins:
            duration = max(window_s, 1e-6)
            loss_count = int(bucket["counts_by_class"].get("loss", 0))
            bellpair_count = int(bucket["counts_by_class"].get("bellpairs", 0))
            if loss_count >= 5:
                key_moments.append(KeyMoment(cursor=target_cursor, sim_time=bucket["end_sim_time"], event_type="loss_burst", label=f"loss burst ({loss_count})", severity="bad"))
            if bellpair_count >= 10:
                key_moments.append(KeyMoment(cursor=target_cursor, sim_time=bucket["end_sim_time"], event_type="bellpair_burst", label=f"bellpair burst ({bellpair_count})", severity="info"))
            bucket["request_submit_rate"] /= duration
            bucket["request_accept_rate"] /= duration
            bucket["request_reject_rate"] /= duration
            bucket["bellpair_generation_rate"] /= duration
            bucket["photon_loss_rate"] /= duration

        if run_status in {"finished", "failed", "terminated"}:
            severity = "info" if run_status == "finished" else ("warn" if run_status == "terminated" else "bad")
            key_moments.append(KeyMoment(cursor=target_cursor, sim_time=anchor_sim_time, event_type=run_status, label=status_message or run_status, severity=severity))

        duration = max(sim_span, 1e-6)
        global_totals = ActivityGlobalTotals(
            events_per_s=len(filtered_events) / duration if sim_span > 0 else 0.0,
            visible_event_density=(len(filtered_events) / sim_span) if sim_span > 0 else None,
            request_submit_rate=sum(1 for event in window_events if event.event_type == "experiment_request_submitted") / duration if sim_span > 0 else 0.0,
            request_accept_rate=sum(1 for event in window_events if event.event_type == "experiment_request_setup_accepted") / duration if sim_span > 0 else 0.0,
            request_reject_rate=sum(1 for event in window_events if event.event_type == "experiment_request_setup_rejected") / duration if sim_span > 0 else 0.0,
            bellpair_generation_rate=sum(1 for event in filtered_events if event.event_type == "BellPairGenerated") / duration if sim_span > 0 else 0.0,
            photon_loss_rate=sum(1 for event in filtered_events if event.event_type == "flying_qubit_loss") / duration if sim_span > 0 else 0.0,
            active_node_count=len(global_nodes),
            active_edge_count=len(global_edges),
        )

        node_heat = []
        for node in subgraph.get("nodes", []):
            node_id = str(node.get("id"))
            counts = dict(view_node_counts.get(node_id, {}))
            total_count = sum(counts.values())
            node_heat.append(ActivityNodeHeat(
                id=node_id,
                total_count=total_count,
                rate_per_s=(total_count / duration) if sim_span > 0 else 0.0,
                intensity=self._intensity(total_count),
                dominant_class=self._dominant_class(counts),
                counts_by_class=counts,
            ))

        edge_heat = []
        for src, dst in view_edges:
            counts = dict(view_edge_counts.get(self._canonical_edge(src, dst), {}))
            total_count = sum(counts.values())
            edge_heat.append(ActivityEdgeHeat(
                src=src,
                dst=dst,
                total_count=total_count,
                rate_per_s=(total_count / duration) if sim_span > 0 else 0.0,
                intensity=self._intensity(total_count),
                dominant_class=self._dominant_class(counts),
                counts_by_class=counts,
            ))

        bin_models = []
        for bucket in bins:
            duration_bucket = max(bucket["end_sim_time"] - bucket["start_sim_time"], 1e-6)
            bin_models.append(ActivityBin(
                start_sim_time=bucket["start_sim_time"],
                end_sim_time=bucket["end_sim_time"],
                events_per_s=bucket["count"] / duration_bucket,
                visible_event_density=(bucket["count"] / duration_bucket) if bucket["count"] > 0 else 0.0,
                request_submit_rate=bucket["request_submit_rate"],
                request_accept_rate=bucket["request_accept_rate"],
                request_reject_rate=bucket["request_reject_rate"],
                bellpair_generation_rate=bucket["bellpair_generation_rate"],
                photon_loss_rate=bucket["photon_loss_rate"],
                active_node_count=len(bucket["nodes"]),
                active_edge_count=len(bucket["edges"]),
            ))

        key_moments.sort(key=lambda item: ((item.sim_time or 0.0), item.cursor))
        snapshot = ActivitySnapshot(
            run_id=run_id,
            anchor_cursor=target_cursor,
            live_edge_cursor=latest_cursor,
            anchor_sim_time=anchor_sim_time,
            window_s=window_s,
            lookback_s=lookback_s,
            global_totals=global_totals,
            bins=bin_models,
            view_node_activity=sorted(node_heat, key=lambda item: (-item.total_count, item.id)),
            view_edge_activity=sorted(edge_heat, key=lambda item: (-item.total_count, item.src, item.dst)),
            key_moments=key_moments[-10:],
        )
        self._snapshot_cache[cache_key] = snapshot
        return snapshot

    async def build_summary(
        self,
        run_id: str,
        *,
        bin_s: float = 1.0,
        classes: Optional[Sequence[str]] = None,
    ) -> RunActivitySummary:
        normalized_classes = self._normalize_classes(classes)
        cache_key = (run_id, round(bin_s, 3), normalized_classes)
        cached = self._summary_cache.get(cache_key)
        if cached is not None:
            return cached

        await self.store.refresh_run(run_id)
        latest_cursor = self.store.get_latest_cursor(run_id)
        events = self.store.get_events_between_cursors(run_id, 0, latest_cursor)
        filtered_events = []
        global_counts_by_class: Dict[str, int] = defaultdict(int)
        if not events:
            summary = RunActivitySummary(run_id=run_id, bin_s=bin_s, classes=list(normalized_classes), visible_event_density=ActivityDensitySummary(), peak_windows=[], global_counts_by_class={})
            self._summary_cache[cache_key] = summary
            return summary

        min_sim_time = min(event.sim_time for event in events)
        max_sim_time = max(event.sim_time for event in events)
        bin_map: Dict[int, Dict[str, Any]] = defaultdict(lambda: {"count": 0, "class_counts": defaultdict(int), "start": None, "end": None})
        for event in events:
            event_class = self._event_class(event)
            if event_class not in ALL_ACTIVITY_CLASSES:
                continue
            if normalized_classes and event_class not in normalized_classes:
                continue
            filtered_events.append(event)
            global_counts_by_class[event_class] += 1
            bucket_index = int(max(0.0, event.sim_time - min_sim_time) // max(bin_s, 1e-6))
            bucket = bin_map[bucket_index]
            bucket["count"] += 1
            bucket["class_counts"][event_class] += 1
            bucket["start"] = event.sim_time if bucket["start"] is None else min(bucket["start"], event.sim_time)
            bucket["end"] = event.sim_time if bucket["end"] is None else max(bucket["end"], event.sim_time)

        densities = []
        peak_windows = []
        for bucket_index, bucket in sorted(bin_map.items()):
            start = min_sim_time + bucket_index * bin_s
            end = max(start + bin_s, bucket["end"] if bucket["end"] is not None else start + bin_s)
            duration = max(end - start, 1e-6)
            density = bucket["count"] / duration
            densities.append(density)
            peak_windows.append(PeakWindow(
                start_sim_time=start,
                end_sim_time=end,
                visible_event_density=density,
                dominant_class=self._dominant_class(dict(bucket["class_counts"])),
            ))

        peak_windows.sort(key=lambda item: (-item.visible_event_density, item.start_sim_time))
        summary = RunActivitySummary(
            run_id=run_id,
            bin_s=bin_s,
            classes=list(normalized_classes),
            visible_event_density=self._summarize_numeric(densities),
            peak_windows=peak_windows[:5],
            global_counts_by_class=dict(sorted(global_counts_by_class.items())),
        )
        self._summary_cache[cache_key] = summary
        return summary
