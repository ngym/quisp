from __future__ import annotations

from scripts.dashboard.backend.app.layout import normalize_snapshot


def test_layout_deterministic_for_large_nodes() -> None:
    nodes = {str(index): {} for index in range(10000)}
    edges = [(str(index), str((index + 1) % 10000)) for index in range(10000)]

    first_nodes, _ = normalize_snapshot(nodes, edges, seed=42)
    second_nodes, _ = normalize_snapshot(nodes, edges, seed=42)

    first = {(node.id, round(node.x, 9), round(node.y, 9)) for node in first_nodes}
    second = {(node.id, round(node.x, 9), round(node.y, 9)) for node in second_nodes}
    assert first == second


def test_layout_unique_coordinates_when_many_nodes() -> None:
    nodes = {str(index): {} for index in range(1000)}
    edges = []
    node_objs, _ = normalize_snapshot(nodes, edges, seed=7)

    coords = [(node.x, node.y) for node in node_objs]
    assert len(coords) == len(set(coords))
