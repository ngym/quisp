from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Sequence, Set, Tuple
import bisect
import re
import time

from .layout import normalize_snapshot
from .log_reader import parse_log_event
from .models import DashboardEvent, FrameWindow, RunInfo, parse_coordinate


@dataclass
class EventIndex:
    cursor: int
    offset: int
    length: int
    sim_time: float
    event_type: str


@dataclass
class RunTopology:
    nodes: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    edges: Dict[Tuple[str, str], Dict[str, Any]] = field(default_factory=dict)


@dataclass
class RunState:
    run_id: str
    path: Path
    file_size: int = 0
    byte_cursor: int = 0
    indexes: List[EventIndex] = field(default_factory=list)
    topology: RunTopology = field(default_factory=RunTopology)
    last_event_type: Optional[str] = None
    last_sim_time: float = 0.0

    def reset_scan(self) -> None:
        self.indexes = []
        self.file_size = 0
        self.byte_cursor = 0
        self.topology = RunTopology()


@dataclass
class Metrics:
    runs_discovered: int = 0
    scans_performed: int = 0
    events_indexed: int = 0
    parse_failures: int = 0
    websocket_clients: int = 0
    events_served: int = 0
    last_topology_nodes: int = 0
    last_topology_edges: int = 0
    last_subgraph_nodes: int = 0
    last_subgraph_edges: int = 0
    created_at: float = field(default_factory=time.perf_counter)
    last_dispatched_at: float = 0.0


class RunStore:
    def __init__(self, log_dir: Path) -> None:
        self.log_dir = log_dir
        self._runs: Dict[str, RunState] = {}
        self.metrics = Metrics()

    # --- Discovery -----------------------------------------------------------
    def _run_id_for_path(self, path: Path) -> str:
        if path.name == "run.jsonl" and path.parent != self.log_dir:
            return path.parent.name
        return path.name

    def _discover_run_paths(self) -> Dict[str, Path]:
        if not self.log_dir.exists():
            return {}
        discovered = {}
        for entry in sorted(self.log_dir.rglob("*"), key=lambda p: p.as_posix()):
            if not entry.is_file():
                continue
            if entry.suffix.lower() not in {".log", ".jsonl", ".ndjson"}:
                continue
            run_id = self._run_id_for_path(entry)
            if not run_id:
                continue
            if run_id in discovered:
                existing = discovered[run_id]
                try:
                    if entry.stat().st_mtime <= existing.stat().st_mtime:
                        continue
                except OSError:
                    pass
            discovered[run_id] = entry
        return discovered

    def register_run_file(self, path: Path, *, run_id: str | None = None) -> str:
        run_id = run_id or path.name
        if not run_id:
            raise ValueError("run_id is required")

        state = self._runs.get(run_id)
        if state is not None:
            if state.path == path:
                return run_id
            raise ValueError(f"run_id {run_id} already exists")

        self._runs[run_id] = RunState(run_id=run_id, path=Path(path))
        return run_id

    def get_event_count(self, run_id: str) -> int:
        state = self._runs.get(run_id)
        if state is None:
            return 0
        return len(state.indexes)

    async def discover_runs(self) -> Dict[str, RunState]:
        discovered = self._discover_run_paths()
        for run_id, path in discovered.items():
            state = self._runs.get(run_id)
            if state is None:
                self._runs[run_id] = RunState(run_id=run_id, path=path)
        # remove deleted files
        for run_id in list(self._runs.keys()):
            if run_id not in discovered:
                del self._runs[run_id]

        self.metrics.runs_discovered = len(self._runs)
        for state in self._runs.values():
            await self.refresh_run(state.run_id)
        return self._runs

    def list_runs(self) -> List[RunInfo]:
        items: List[RunInfo] = []
        for state in self._runs.values():
            items.append(
                RunInfo(
                    run_id=state.run_id,
                    path=str(state.path),
                    event_count=len(state.indexes),
                    last_sim_time=state.last_sim_time,
                    last_event_type=state.last_event_type,
                    updated_at=self._mtime_iso(state.path),
                )
            )
        return sorted(items, key=lambda item: item.run_id)

    # --- Parsing / scan -----------------------------------------------------
    async def refresh_run(self, run_id: str) -> RunState:
        state = self._run_state(run_id)
        path = state.path
        if not path.exists():
            return state

        current_size = path.stat().st_size
        if current_size < state.file_size:
            state.reset_scan()

        if current_size == state.file_size:
            state.file_size = current_size
            return state

        with open(path, "rb") as fp:
            fp.seek(state.byte_cursor)
            while True:
                offset = fp.tell()
                line = fp.readline()
                if not line:
                    break
                if isinstance(line, bytes):
                    text_line = line.decode("utf-8", errors="replace")
                else:
                    text_line = str(line)
                cursor = len(state.indexes)
                state.byte_cursor = fp.tell()
                event = parse_log_event(text_line, run_id=run_id, cursor=cursor)
                state.indexes.append(
                    EventIndex(
                        cursor=cursor,
                        offset=offset,
                        length=len(line),
                        sim_time=event.sim_time,
                        event_type=event.event_type,
                    )
                )
                self.metrics.events_indexed += 1
                if isinstance(event.payload, dict) and "parse_error" in event.payload:
                    self.metrics.parse_failures += 1
                state.last_sim_time = event.sim_time
                state.last_event_type = event.event_type
                self._update_topology(state, event)
        state.file_size = current_size
        self.metrics.scans_performed += 1
        return state

    def _run_state(self, run_id: str) -> RunState:
        if run_id not in self._runs:
            raise KeyError(f"unknown run_id {run_id}")
        return self._runs[run_id]

    def _mtime_iso(self, path: Path) -> str:
        try:
            ts = path.stat().st_mtime
            import datetime

            return datetime.datetime.fromtimestamp(ts).isoformat()
        except FileNotFoundError:
            return ""

    def _read_events_at_indexes(self, state: RunState, targets: Sequence[EventIndex]) -> List[DashboardEvent]:
        results: List[DashboardEvent] = []
        if not targets:
            return results
        with open(state.path, "rb") as fp:
            for entry in targets:
                fp.seek(entry.offset)
                line = fp.read(entry.length)
                if isinstance(line, bytes):
                    text_line = line.decode("utf-8", errors="replace")
                else:
                    text_line = str(line)
                event = parse_log_event(text_line, run_id=state.run_id, cursor=entry.cursor)
                results.append(event)
        return results

    def _find_start_by_time(self, state: RunState, from_time: float) -> int:
        times = [entry.sim_time for entry in state.indexes]
        return bisect.bisect_left(times, from_time)

    async def get_events(
        self,
        run_id: str,
        from_event_id: int = 0,
        from_time: Optional[float] = None,
        limit: int = 5000,
        types: Optional[Sequence[str]] = None,
    ) -> FrameWindow:
        state = await self.refresh_run(run_id)
        filtered: List[EventIndex] = state.indexes

        start = max(0, from_event_id)
        if from_time is not None:
            start = max(0, self._find_start_by_time(state, from_time))

        type_filter = {t.strip().lower() for t in types or set() if isinstance(t, str) and t.strip()}
        selected_indexes: List[EventIndex] = []
        for entry in filtered[start:]:
            if len(selected_indexes) >= limit:
                break
            if type_filter and entry.event_type.lower() not in type_filter:
                continue
            selected_indexes.append(entry)

        events = self._read_events_at_indexes(state, selected_indexes)
        self.metrics.events_served += len(events)
        self.metrics.last_dispatched_at = time.perf_counter()
        next_cursor = selected_indexes[-1].cursor + 1 if selected_indexes else start
        has_more = False
        if next_cursor < len(state.indexes):
            # check if remaining matching events exist
            for entry in state.indexes[next_cursor:]:
                if not type_filter or entry.event_type.lower() in type_filter:
                    has_more = True
                    break

        frame_index = start // max(1, limit)
        return FrameWindow(
            window_id=f"{run_id}:{start}:{limit}",
            frame_index=frame_index,
            events=events,
            state_delta={
                "count": len(events),
                "from_event_id": from_event_id,
                "from_time": from_time,
            },
            next_cursor=next_cursor,
            has_more=has_more,
        )

    async def get_topology(self, run_id: str, max_nodes: Optional[int] = None) -> Dict[str, Any]:
        state = await self.refresh_run(run_id)
        nodes_meta = {k: dict(v) for k, v in state.topology.nodes.items()}
        edge_pairs = list(state.topology.edges.keys())

        if max_nodes is not None and max_nodes > 0:
            # keep stable deterministic subset with higher degree first
            degree = {node: 0 for node in nodes_meta}
            for src, dst in edge_pairs:
                degree[src] = degree.get(src, 0) + 1
                degree[dst] = degree.get(dst, 0) + 1
            ordered_nodes = sorted(nodes_meta.keys(), key=lambda n: (-degree.get(n, 0), str(n)))
            kept = set(ordered_nodes[:max_nodes])
            edge_pairs = [(src, dst) for src, dst in edge_pairs if src in kept and dst in kept]
            nodes_meta = {n: nodes_meta[n] for n in kept if n in nodes_meta}

        explicit_positions = {
            node_id: (node_x, node_y)
            for node_id, meta in nodes_meta.items()
            if (node_x := parse_coordinate(meta.get("x"))) is not None
            and (node_y := parse_coordinate(meta.get("y"))) is not None
        }
        node_list, edge_list = normalize_snapshot(nodes_meta, edge_pairs, explicit_positions, seed=hash(run_id) & 0xFFFF)

        self.metrics.last_topology_nodes = len(node_list)
        self.metrics.last_topology_edges = len(edge_list)
        return {
            "nodes": [n.to_dict() for n in node_list],
            "edges": [e.to_dict() for e in edge_list],
            "metadata": {
                "run_id": run_id,
                "raw_node_count": len(state.topology.nodes),
                "raw_edge_count": len(state.topology.edges),
                "returned_node_count": len(node_list),
                "returned_edge_count": len(edge_list),
            },
        }

    async def get_subgraph(
        self,
        run_id: str,
        *,
        focus: Optional[str] = None,
        hops: int = 0,
        max_nodes: int = 3000,
        node_regex: Optional[str] = None,
    ) -> Dict[str, Any]:
        state = await self.refresh_run(run_id)
        all_nodes = state.topology.nodes

        selected: Set[str] = set()

        if node_regex:
            pattern = re.compile(node_regex)
            selected.update({node for node in all_nodes if pattern.search(str(node))})

        seeds: Set[str] = set()
        if focus is not None:
            seed = str(focus)
            if seed in all_nodes:
                seeds.add(seed)
            elif seed.startswith("N") and seed[1:] in all_nodes:
                seeds.add(seed[1:])

        if seeds:
            selected.update(seeds)

        adjacency: Dict[str, Set[str]] = {}
        for src, dst in state.topology.edges:
            adjacency.setdefault(src, set()).add(dst)
            adjacency.setdefault(dst, set()).add(src)

        if seeds and hops > 0:
            q: Deque[Tuple[str, int]] = deque((seed, 0) for seed in seeds)
            seen = {seed for seed in seeds}
            while q:
                node_id, depth = q.popleft()
                if depth >= hops:
                    continue
                for nxt in adjacency.get(node_id, set()):
                    if nxt in seen:
                        continue
                    seen.add(nxt)
                    q.append((nxt, depth + 1))
            selected.update(seen)

        if not selected:
            selected = set(all_nodes.keys())

        # If selection too large, trim using degree descending.
        degree = {node: 0 for node in selected}
        for src, dst in state.topology.edges:
            if src in degree and dst in degree:
                degree[src] += 1
                degree[dst] += 1

        if max_nodes and max_nodes > 0 and len(selected) > max_nodes:
            selected = set(sorted(selected, key=lambda n: (-degree.get(n, 0), str(n)))[:max_nodes])

        nodes_meta = {node: dict(all_nodes[node]) for node in selected if node in all_nodes}
        edge_pairs = [
            (src, dst)
            for (src, dst) in state.topology.edges
            if src in selected and dst in selected
        ]
        explicit_positions = {
            node_id: (node_x, node_y)
            for node_id, meta in nodes_meta.items()
            if (node_x := parse_coordinate(meta.get("x"))) is not None
            and (node_y := parse_coordinate(meta.get("y"))) is not None
        }
        node_list, edge_list = normalize_snapshot(nodes_meta, edge_pairs, explicit_positions, seed=hash((run_id, node_regex, focus, hops)) & 0xFFFF)

        self.metrics.last_subgraph_nodes = len(node_list)
        self.metrics.last_subgraph_edges = len(edge_list)
        return {
            "nodes": [n.to_dict() for n in node_list],
            "edges": [e.to_dict() for e in edge_list],
            "metadata": {
                "run_id": run_id,
                "filter_focus": focus,
                "filter_hops": hops,
                "node_regex": node_regex,
                "returned_node_count": len(node_list),
                "returned_edge_count": len(edge_list),
            },
        }

    # --- Topology update ----------------------------------------------------
    def _parse_node_id(self, raw: Any) -> Optional[str]:
        if raw is None:
            return None
        text = str(raw).strip()
        if not text:
            return None
        return text

    def _extract_coordinates(self, payload: Dict[str, Any]) -> Optional[Tuple[float, float]]:
        for candidate in (("x", "y"), ("pos_x", "pos_y"), ("px", "py"), ("cx", "cy")):
            x = parse_coordinate(payload.get(candidate[0]))
            y = parse_coordinate(payload.get(candidate[1]))
            if x is not None and y is not None:
                return x, y
        return None

    def _update_topology(self, state: RunState, event: DashboardEvent) -> None:
        payload = event.payload if isinstance(event.payload, dict) else {}

        source = event.source.strip() if event.source else ""
        if source:
            meta = state.topology.nodes.setdefault(source, {"label": source, "last_seen": event.sim_time})
            meta["last_seen"] = event.sim_time

        coord = self._extract_coordinates(payload)
        if coord and source:
            state.topology.nodes[source]["x"] = coord[0]
            state.topology.nodes[source]["y"] = coord[1]

        def ensure_node(raw_node: Any) -> None:
            node_id = self._parse_node_id(raw_node)
            if node_id is None:
                return
            meta = state.topology.nodes.setdefault(node_id, {"label": node_id, "last_seen": event.sim_time})
            coord_here = self._extract_coordinates(payload)
            if coord_here:
                meta["x"] = coord_here[0]
                meta["y"] = coord_here[1]
            meta["last_seen"] = event.sim_time

        def ensure_edge(src: Any, dst: Any, *, kind: Optional[str] = None, weight: Optional[float] = None) -> None:
            src_id = self._parse_node_id(src)
            dst_id = self._parse_node_id(dst)
            if not src_id or not dst_id or src_id == dst_id:
                return
            ensure_node(src_id)
            ensure_node(dst_id)
            key = (src_id, dst_id)
            edge_meta = state.topology.edges.setdefault(key, {})
            if kind is not None:
                edge_meta["kind"] = kind
            if weight is not None:
                edge_meta["weight"] = weight
            edge_meta["updated_sim_time"] = max(edge_meta.get("updated_sim_time", 0.0), event.sim_time)

        etype = event.event_type.lower()

        # Explicit topology export in event payload
        if etype in {"topology", "topology_snapshot", "topology_update", "network_topology"}:
            nodes_payload = payload.get("nodes")
            if isinstance(nodes_payload, list):
                for item in nodes_payload:
                    if isinstance(item, dict):
                        node_id = self._parse_node_id(item.get("id") or item.get("node") or item.get("name"))
                        if node_id is None:
                            continue
                        meta = state.topology.nodes.setdefault(node_id, {"label": str(item.get("label", node_id)), "last_seen": event.sim_time})
                        meta["label"] = str(item.get("label", node_id))
                        node_coord = self._extract_coordinates(item)
                        if node_coord:
                            meta["x"] = node_coord[0]
                            meta["y"] = node_coord[1]
                        else:
                            coords_from_parent = coord
                            if coords_from_parent:
                                meta["x"] = coords_from_parent[0]
                                meta["y"] = coords_from_parent[1]
            edges_payload = payload.get("edges")
            if isinstance(edges_payload, list):
                for item in edges_payload:
                    if isinstance(item, dict):
                        ensure_edge(item.get("src"), item.get("dst"), kind=str(item.get("kind") or "topology"), weight=item.get("weight"))
                    elif isinstance(item, (list, tuple)) and len(item) >= 2:
                        ensure_edge(item[0], item[1], kind="topology", weight=item[2] if len(item) >= 3 else None)

        # Common pair shapes
        pair_fields = [
            ("src", "dst"),
            ("source", "destination"),
            ("from", "to"),
            ("u", "v"),
            ("node_id", "partner_addr"),
        ]
        for src_key, dst_key in pair_fields:
            src = payload.get(src_key)
            dst = payload.get(dst_key)
            ensure_edge(src, dst, kind="inferred")

        if event.event_type.startswith("BellPair") and payload.get("partner_addr") and source:
            ensure_edge(source, payload.get("partner_addr"), kind="bell_pair")

        # Raw qnode indexes list (if present)
        if isinstance(payload.get("stack_of_qnode_indices"), list):
            seq = [self._parse_node_id(n) for n in payload["stack_of_qnode_indices"]]
            for src, dst in zip(seq, seq[1:]):
                if src and dst:
                    ensure_edge(src, dst, kind="path")

    def get_metrics(self) -> Dict[str, Any]:
        uptime_seconds = max(1e-6, time.perf_counter() - self.metrics.created_at)
        return {
            "runs_discovered": self.metrics.runs_discovered,
            "scans_performed": self.metrics.scans_performed,
            "events_indexed": self.metrics.events_indexed,
            "parse_failures": self.metrics.parse_failures,
            "websocket_clients": self.metrics.websocket_clients,
            "events_served": self.metrics.events_served,
            "events_indexed_per_sec": self.metrics.events_indexed / uptime_seconds,
            "events_served_per_sec": self.metrics.events_served / uptime_seconds,
            "last_dispatched_at": self.metrics.last_dispatched_at,
            "active_runs": len(self._runs),
            "topology_nodes": self.metrics.last_topology_nodes,
            "topology_edges": self.metrics.last_topology_edges,
            "subgraph_nodes": self.metrics.last_subgraph_nodes,
            "subgraph_edges": self.metrics.last_subgraph_edges,
        }
