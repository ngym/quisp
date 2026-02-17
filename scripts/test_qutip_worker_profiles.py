#!/usr/bin/env python3
"""Pytest coverage for qutip worker profile routing and metadata.

These tests exercise profile resolution paths added for node/link profile support,
including custom overrides and invalid fallback behavior.
"""

from __future__ import annotations

import os
import sys
import tempfile
from typing import Any, Dict, Iterable

import pytest


def _qutip_available() -> bool:
    if not os.environ.get("MPLCONFIGDIR"):
        temp_dir = os.path.join(tempfile.gettempdir(), "qutip_worker_smoke_matplotlib")
        os.makedirs(temp_dir, exist_ok=True)
        os.environ["MPLCONFIGDIR"] = temp_dir

    try:
        import qutip  # noqa: F401
        import qutip_qip  # noqa: F401
        import qutip.qip  # noqa: F401
    except Exception as exc:
        pytest.skip(f"qutip not available: {exc}")
        return False
    return True


def _qutip_worker_module():
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(scripts_dir)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    import scripts.qutip_worker as qutip_worker

    return qutip_worker


def _call_worker(operation: Dict[str, Any], seed: int = 12345) -> Dict[str, Any]:
    qutip_worker = _qutip_worker_module()

    operation = dict(operation)
    backend_config = dict(operation.pop("backend_config", {}))
    backend_config.setdefault("python_executable", "python3")
    backend_config.setdefault("qutip_backend_class", "qutip_density_matrix")
    backend_config.setdefault("qutip_worker_timeout_ms", 5000)

    request = {
        "seed": seed,
        "operation": operation,
        "backend_config": backend_config,
    }
    return qutip_worker.run_operation(request)


def _assert_response(response: Dict[str, Any], success: bool = True) -> None:
    assert response.get("success") is success
    assert response.get("message", "") != ""
    assert isinstance(response.get("fidelity_estimate"), (float, int))


def _assert_meta(response: Dict[str, Any], key: str, expected: Any) -> None:
    meta = response.get("meta")
    assert isinstance(meta, dict)
    assert meta.get(key) == expected


def _assert_meta_contains(response: Dict[str, Any], key: str, expected_fragment: str) -> None:
    meta = response.get("meta")
    assert isinstance(meta, dict)
    value = meta.get(key)
    assert isinstance(value, str)
    assert expected_fragment in value


def _measurement_probabilities(response: Dict[str, Any], plus: float, minus: float) -> None:
    meta = response.get("meta")
    assert isinstance(meta, dict)
    assert isinstance(meta.get("measurement_plus_probability"), (float, int))
    assert isinstance(meta.get("measurement_minus_probability"), (float, int))
    assert float(meta["measurement_plus_probability"]) == plus
    assert float(meta["measurement_minus_probability"]) == minus


@pytest.mark.parametrize(
    "name,operation,checks",
    [
        (
            "default",
            {
                "kind": "unitary",
                "payload": {"kind": "unitary", "gate": "X"},
                "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
                "backend_config": {},
            },
            [
                ("meta", "profile", "standard_light"),
                ("meta", "mode", "node"),
                ("meta", "dim", 2),
                ("meta", "node_dim", 2),
            ],
        ),
        (
            "standard_qutrit_node",
            {
                "kind": "unitary",
                "payload": {"kind": "unitary", "gate": "X"},
                "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
                "backend_config": {"qutip_node_profile": "standard_qutrit"},
            },
            [
                ("meta", "profile", "standard_qutrit"),
                ("meta", "mode", "node"),
                ("meta", "dim", 3),
            ],
        ),
        (
            "standard_qutrit_link",
            {
                "kind": "hom_interference",
                "duration": 0.2,
                "targets": [
                    {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0},
                    {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1},
                ],
                "backend_config": {"qutip_link_profile": "standard_qutrit"},
            },
            [
                ("meta", "profile", "standard_qutrit"),
                ("meta", "mode", "link"),
                ("meta", "dim", 4),
            ],
        ),
        (
            "link_takes_precedence",
            {
                "kind": "hom_interference",
                "duration": 0.2,
                "targets": [
                    {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0},
                    {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1},
                ],
                "backend_config": {
                    "qutip_node_profile": "standard_qutrit",
                    "qutip_link_profile": "standard_light",
                },
            },
            [
                ("meta", "profile", "standard_light"),
                ("meta", "mode", "link"),
                ("meta", "requested_profile", "standard_light"),
                ("meta", "dim", 2),
            ],
        ),
        (
            "custom_node_json",
            {
                "kind": "unitary",
                "payload": {"kind": "unitary", "gate": "X"},
                "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
                "backend_config": {
                    "qutip_node_profile": "custom",
                    "qutip_profile_overrides": "{\"node_dim\":4, \"link_mode_dim\":5, \"truncation\":7}",
                },
            },
            [
                ("meta", "profile", "custom"),
                ("meta", "dim", 4),
                ("meta", "node_dim", 4),
                ("meta", "link_dim", 5),
                ("meta", "truncation", 7),
            ],
        ),
        (
            "custom_partial",
            {
                "kind": "unitary",
                "payload": {"kind": "unitary", "gate": "Y"},
                "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
                "backend_config": {
                    "qutip_node_profile": "custom",
                    "qutip_profile_overrides": {"node_dim": "4"},
                },
            },
            [
                ("meta", "profile", "custom"),
                ("meta", "node_dim", 4),
                ("meta", "link_dim", 2),
                ("meta", "dim", 4),
            ],
        ),
        (
            "custom_link_partial",
            {
                "kind": "hom_interference",
                "duration": 0.2,
                "targets": [
                    {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0},
                    {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1},
                ],
                "backend_config": {
                    "qutip_link_profile": "custom",
                    "qutip_profile_overrides": {"link_mode_dim": "7"},
                },
            },
            [
                ("meta", "profile", "custom"),
                ("meta", "mode", "link"),
                ("meta", "link_dim", 7),
                ("meta", "dim", 7),
            ],
        ),
        (
            "invalid_name_fallback_node",
            {
                "kind": "unitary",
                "payload": {"kind": "unitary", "gate": "X"},
                "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
                "backend_config": {"qutip_node_profile": "does_not_exist"},
            },
            [
                ("meta", "profile", "standard_light"),
                ("meta", "mode", "node"),
                ("meta", "requested_profile", "does_not_exist"),
                ("meta", "dim", 2),
            ],
        ),
        (
            "invalid_name_fallback_link",
            {
                "kind": "hom_interference",
                "duration": 0.2,
                "targets": [
                    {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0},
                    {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1},
                ],
                "backend_config": {"qutip_link_profile": "does_not_exist"},
            },
            [
                ("meta", "profile", "standard_light"),
                ("meta", "mode", "link"),
                ("meta", "requested_profile", "does_not_exist"),
                ("meta", "dim", 2),
            ],
        ),
        (
            "normalized_names",
            {
                "kind": "unitary",
                "payload": {"kind": "unitary", "gate": "X"},
                "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
                "backend_config": {"qutip_node_profile": "Standard Qutrit"},
            },
            [
                ("meta", "profile", "standard_qutrit"),
                ("meta", "requested_profile", "standard_qutrit"),
                ("meta", "dim", 3),
            ],
        ),
        (
            "custom_bool_true",
            {
                "kind": "noise",
                "payload": {"kind": "noise", "noise_kind": "dephasing", "p": 0.04},
                "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
                "backend_config": {
                    "qutip_node_profile": "custom",
                    "qutip_profile_overrides": {"leakage_enabled": "true"},
                },
            },
            [
                ("meta", "profile", "custom"),
                ("meta", "leakage_enabled", True),
            ],
        ),
        (
            "invalid_override_bool",
            {
                "kind": "measurement",
                "basis": "Z",
                "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
                "backend_config": {
                    "qutip_node_profile": "custom",
                    "qutip_profile_overrides": "{\"leakage_enabled\": \"not-bool\", \"node_dim\": 4}",
                },
            },
            [
                ("meta", "profile", "custom"),
                ("meta", "node_dim", 4),
            ],
        ),
        (
            "invalid_override_json_type",
            {
                "kind": "measurement",
                "basis": "Z",
                "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
                "backend_config": {
                    "qutip_node_profile": "custom",
                    "qutip_profile_overrides": 123,
                },
            },
            [
                ("meta", "profile", "custom"),
                ("meta", "dim", 2),
            ],
        ),
    ],
)
def test_profile_matrix(name: str, operation: Dict[str, Any], checks: Iterable[tuple[str, str, Any]]) -> None:
    _qutip_available()
    response = _call_worker(operation, seed=12345)
    _assert_response(response, success=True)
    for level, key, expected in checks:
        if level == "meta":
            _assert_meta(response, key, expected)

    if name == "invalid_name_fallback_node":
        assert response.get("error_category") == "invalid_profile"

    if name == "invalid_name_fallback_link":
        assert response.get("error_category") == "invalid_profile"

    if name == "invalid_override_json_type":
        assert response.get("error_category") == "invalid_profile"
        _assert_meta_contains(response, "errors", "qutip_profile_overrides must be a JSON string/object")

    if name == "invalid_override_bool":
        assert response.get("error_category") == "invalid_profile"
        _assert_meta_contains(response, "errors", "invalid boolean value")


@pytest.mark.parametrize(
    "operation,plus,minus",
    [
        (
            {
                "kind": "measurement",
                "basis": "X",
                "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
                "backend_config": {"qutip_node_profile": "standard_qutrit"},
            },
            0.5,
            0.5,
        ),
        (
            {
                "kind": "measurement",
                "basis": "BELL",
                "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
                "backend_config": {"qutip_node_profile": "custom", "qutip_profile_overrides": {"node_dim": 3}},
            },
            0.5,
            0.5,
        ),
    ],
)
def test_measurement_profile_probabilities(operation: Dict[str, Any], plus: float, minus: float) -> None:
    _qutip_available()
    response = _call_worker(operation, seed=12345)
    _assert_response(response, success=True)
    _measurement_probabilities(response, plus, minus)
    assert isinstance(response.get("measured_plus"), bool)


@pytest.mark.parametrize(
    "operation,expected_error_category",
    [
        (
            {
                "kind": "measurement",
                "basis": "Z",
                "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
                "backend_config": {
                    "qutip_node_profile": "custom",
                    "qutip_profile_overrides": "[1,2,3]",
                },
            },
            "invalid_profile",
        ),
        (
            {
                "kind": "unitary",
                "payload": {"kind": "unitary", "gate": "Y"},
                "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
                "backend_config": {
                    "qutip_node_profile": "custom",
                    "qutip_profile_overrides": {"node_dim": 0, "link_mode_dim": 0, "truncation": 0},
                },
            },
            "invalid_profile",
        ),
    ],
)
def test_profile_invalid_error_paths(operation: Dict[str, Any], expected_error_category: str) -> None:
    _qutip_available()
    response = _call_worker(operation, seed=12345)
    _assert_response(response, success=True)
    assert response.get("error_category") == expected_error_category
    _assert_meta(response, "profile", "custom")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
