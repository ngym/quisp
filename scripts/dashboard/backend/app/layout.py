from __future__ import annotations

from collections import deque
from typing import Dict, Iterable, List, Sequence, Tuple
import hashlib
import math

from .models import TopologyEdge, TopologyNode


def _seed_offset(seed: str) -> int:
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _deterministic_offset(idx: int, seed: int) -> float:
    value = (seed * 1103515245 + idx * 12345 + 123) % (1 << 31)
    return (value / float(1 << 31)) - 0.5

def _coerce_node_id(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(int(value))
    text = str(value).strip()
    return text if text else ""


def _neighbor_map(edges: Iterable[Tuple[str, str]]) -> Dict[str, List[str]]:
    neighbors: Dict[str, List[str]] = {}
    for src, dst in edges:
        src = _coerce_node_id(src)
        dst = _coerce_node_id(dst)
        if not src or not dst or src == dst:
            continue
        neighbors.setdefault(src, []).append(dst)
        neighbors.setdefault(dst, []).append(src)
    return neighbors


def build_layout(
    nodes: Dict[str, dict],
    edges: Sequence[Tuple[str, str]],
    *,
    explicit_positions: Dict[str, Tuple[float, float]] | None = None,
    seed: int = 42,
) -> Tuple[Dict[str, Tuple[float, float]], Dict[str, dict]]:
    """Return node positions and node meta merged with fallback deterministic layout."""
    explicit_positions = explicit_positions or {}
    normalized_nodes = { _coerce_node_id(node_id): dict(meta) for node_id, meta in nodes.items() if _coerce_node_id(node_id)}

    for node_id, (x, y) in explicit_positions.items():
        if node_id in normalized_nodes:
            normalized_nodes[node_id]["x"] = x
            normalized_nodes[node_id]["y"] = y

    # Ensure every node exists and has metadata.
    for src, dst in edges:
        src = _coerce_node_id(src)
        dst = _coerce_node_id(dst)
        if not src or not dst or src == dst:
            continue
        normalized_nodes.setdefault(src, {})
        normalized_nodes.setdefault(dst, {})

    positions: Dict[str, Tuple[float, float]] = {}
    neighbors = _neighbor_map([(u, v) for (u, v) in edges if _coerce_node_id(u) and _coerce_node_id(v) and _coerce_node_id(u) != _coerce_node_id(v)])
    visited = set(n for n in normalized_nodes if "x" in normalized_nodes[n] and "y" in normalized_nodes[n])
    for node_id, meta in explicit_positions.items():
        if node_id in normalized_nodes:
            positions[node_id] = (float(meta[0]), float(meta[1]))
            visited.add(node_id)

    unresolved = {node_id for node_id in normalized_nodes if "x" not in normalized_nodes[node_id] or "y" not in normalized_nodes[node_id]}
    comp_id = 0
    for node_id in sorted(unresolved):
        if node_id in visited:
            continue
        comp_id += 1
        queue = deque([node_id])
        visited.add(node_id)
        component = []
        order = 0

        while queue:
            current = queue.popleft()
            component.append(current)
            for nxt in sorted(neighbors.get(current, []), key=str):
                if nxt not in visited:
                    visited.add(nxt)
                    queue.append(nxt)

        if not component:
            continue

        # Place component on a spiral around origin.
        comp_seed = _seed_offset(f"{seed}:{comp_id}")
        angle_center = (comp_seed % 360) * math.pi / 180.0
        radius_center = 120.0 + 90.0 * math.sqrt(max(1, len(component)))
        center_x = radius_center * math.cos(angle_center)
        center_y = radius_center * math.sin(angle_center)

        depth_map = {node: 0 for node in component}
        for depth in range(0, len(component)):
            layer = [n for n in component if depth_map.get(n) == depth]
            if not layer:
                continue
            for idx, current in enumerate(layer):
                theta = 2 * math.pi * (idx / max(1, len(layer))) + angle_center + 0.17 * depth
                spread = 36.0 + depth * 28.0
                noise = _deterministic_offset(order + idx + comp_id, comp_seed)
                x = center_x + spread * math.cos(theta) + noise * 14.0
                y = center_y + spread * math.sin(theta) + noise * 14.0
                if current not in explicit_positions:
                    positions[current] = (x, y)
                    normalized_nodes[current]["x"] = x
                    normalized_nodes[current]["y"] = y
                order += 1

            # Expand depth-map frontier only once so layout remains bounded.
            for current in layer:
                for nxt in neighbors.get(current, []):
                    if nxt in component and nxt not in depth_map:
                        depth_map[nxt] = depth + 1

        # Place any still-unpositioned node in component.
        for current in component:
            if current not in positions:
                local_seed = _seed_offset(f"{seed}:{comp_id}:{current}")
                radius = 20.0 + (local_seed % 300) / 4.0
                theta = (local_seed % 628) / 100.0
                x = center_x + radius * math.cos(theta)
                y = center_y + radius * math.sin(theta)
                positions[current] = (x, y)
                normalized_nodes[current]["x"] = x
                normalized_nodes[current]["y"] = y

    # Ensure all explicitly-positioned nodes are included.
    for node_id, meta in explicit_positions.items():
        positions.setdefault(node_id, (float(meta[0]), float(meta[1])))

    # Fallback for empty graph: place nodes in circle.
    if not positions and normalized_nodes:
        total = len(normalized_nodes)
        for idx, node_id in enumerate(sorted(normalized_nodes.keys())):
            theta = 2 * math.pi * idx / max(1, total)
            radius = 120 + 20 * math.log(max(2, total))
            x = radius * math.cos(theta)
            y = radius * math.sin(theta)
            positions[node_id] = (x, y)
            normalized_nodes[node_id]["x"] = x
            normalized_nodes[node_id]["y"] = y

    return positions, normalized_nodes


def normalize_snapshot(
    nodes: Dict[str, dict],
    edges: Sequence[Tuple[str, str]],
    explicit_positions: Dict[str, Tuple[float, float]] | None = None,
    *,
    seed: int = 42,
) -> Tuple[List[TopologyNode], List[TopologyEdge]]:
    positions, normalized_nodes = build_layout(nodes, edges, explicit_positions=explicit_positions, seed=seed)

    node_entries: List[TopologyNode] = []
    for node_id, meta in normalized_nodes.items():
        x, y = positions.get(node_id, (0.0, 0.0))
        label = str(meta.get("label") or node_id)
        node_entries.append(
            TopologyNode(
                id=node_id,
                label=label,
                x=float(x),
                y=float(y),
                meta={k: v for k, v in meta.items() if k not in {"x", "y", "label"}},
            )
        )

    edge_map = {}
    for src, dst in edges:
        src_id = _coerce_node_id(src)
        dst_id = _coerce_node_id(dst)
        if not src_id or not dst_id:
            continue
        if src_id == dst_id:
            continue
        key = (src_id, dst_id)
        if key in edge_map:
            continue
        edge_map[key] = TopologyEdge(
            src=src_id,
            dst=dst_id,
            weight=None,
            kind=None,
            meta={},
        )

    return node_entries, list(edge_map.values())
