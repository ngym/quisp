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


def _assert_profile_meta_shape(response: Dict[str, Any], expected_keys: set[str]) -> None:
    meta = response.get("meta")
    assert isinstance(meta, dict)
    missing = sorted(expected_keys - set(meta.keys()))
    assert missing == []


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
        (
            "standard_qutrit_node_measurement",
            {
                "kind": "measurement",
                "basis": "Z",
                "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
                "backend_config": {"qutip_node_profile": "standard_qutrit"},
            },
            [
                ("meta", "profile", "standard_qutrit"),
                ("meta", "mode", "node"),
                ("meta", "dim", 3),
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
    "name,operation,checks",
    [
        (
            "link_profile_defaulting_on_herald",
            {
                "kind": "heralded_entanglement",
                "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
                "backend_config": {
                    "qutip_node_profile": "standard_qutrit",
                    "qutip_link_profile": "standard_qutrit",
                },
            },
            [
                ("meta", "profile", "standard_qutrit"),
                ("meta", "mode", "link"),
                ("meta", "dim", 4),
            ],
        ),
        (
            "link_dispersion",
            {
                "kind": "dispersion",
                "duration": 0.1,
                "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
                "backend_config": {
                    "qutip_node_profile": "high_fidelity",
                    "qutip_link_profile": "standard_qutrit",
                },
            },
            [
                ("meta", "profile", "standard_qutrit"),
                ("meta", "mode", "link"),
                ("meta", "dim", 4),
            ],
        ),
        (
            "link_multiphoton",
            {
                "kind": "multiphoton",
                "duration": 0.05,
                "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
                "backend_config": {
                    "qutip_node_profile": "standard_qutrit",
                    "qutip_link_profile": "standard_qutrit",
                },
            },
            [
                ("meta", "profile", "standard_qutrit"),
                ("meta", "mode", "link"),
                ("meta", "dim", 4),
            ],
        ),
        (
            "link_squeezing",
            {
                "kind": "squeezing",
                "duration": 0.05,
                "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
                "backend_config": {"qutip_link_profile": "standard_qutrit"},
            },
            [
                ("meta", "profile", "standard_qutrit"),
                ("meta", "mode", "link"),
                ("meta", "dim", 4),
            ],
        ),
        (
            "link_mode_coupling",
            {
                "kind": "mode_coupling",
                "duration": 0.05,
                "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
                "backend_config": {"qutip_link_profile": "standard_qutrit"},
            },
            [
                ("meta", "profile", "standard_qutrit"),
                ("meta", "mode", "link"),
                ("meta", "dim", 4),
            ],
        ),
        (
            "link_loss_mode",
            {
                "kind": "loss_mode",
                "duration": 0.05,
                "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
                "backend_config": {"qutip_link_profile": "standard_qutrit"},
            },
            [
                ("meta", "profile", "standard_qutrit"),
                ("meta", "mode", "link"),
                ("meta", "dim", 4),
            ],
        ),
        (
            "link_fock_loss",
            {
                "kind": "fock_loss",
                "duration": 0.05,
                "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
                "backend_config": {"qutip_link_profile": "standard_qutrit"},
            },
            [
                ("meta", "profile", "standard_qutrit"),
                ("meta", "mode", "link"),
                ("meta", "dim", 4),
            ],
        ),
        (
            "link_photon_number_cutoff",
            {
                "kind": "photon_number_cutoff",
                "duration": 0.05,
                "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
                "backend_config": {"qutip_link_profile": "standard_qutrit"},
            },
            [
                ("meta", "profile", "standard_qutrit"),
                ("meta", "mode", "link"),
                ("meta", "dim", 4),
            ],
        ),
        (
            "link_two_mode_squeezing",
            {
                "kind": "two_mode_squeezing",
                "duration": 0.05,
                "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
                "backend_config": {"qutip_link_profile": "standard_qutrit"},
            },
            [
                ("meta", "profile", "standard_qutrit"),
                ("meta", "mode", "link"),
                ("meta", "dim", 4),
            ],
        ),
        (
            "node_noise_uses_node_profile",
            {
                "kind": "noise",
                "payload": {"kind": "noise", "noise_kind": "dephasing", "p": 0.01},
                "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
                "backend_config": {
                    "qutip_node_profile": "standard_qutrit",
                    "qutip_link_profile": "standard_light",
                },
            },
            [
                ("meta", "profile", "standard_qutrit"),
                ("meta", "mode", "node"),
                ("meta", "dim", 3),
            ],
        ),
    ],
)
def test_profile_type_routing(name: str, operation: Dict[str, Any], checks: Iterable[tuple[str, str, Any]]) -> None:
    _qutip_available()
    response = _call_worker(operation, seed=12345)
    _assert_response(response, success=True)
    for level, key, expected in checks:
        if level == "meta":
            _assert_meta(response, key, expected)
    _assert_profile_meta_shape(response, {"profile", "mode", "dim", "node_dim", "link_dim", "truncation", "requested_profile", "errors", "leakage_enabled"})


@pytest.mark.parametrize(
    "name,overrides,kind,expected_dim,error_code_expected",
    [
        ("node_dim_string", {"node_dim": "4"}, "unitary", 4, None),
        ("node_dim_none", {"node_dim": None}, "unitary", 2, None),
        ("node_dim_decimal", {"node_dim": 3.9}, "unitary", 3, None),
        ("node_dim_negative", {"node_dim": -1}, "unitary", 2, "invalid_profile"),
        ("node_dim_decimal_string", "{\"node_dim\": \"3.7\"}", "unitary", 2, "invalid_profile"),
        ("link_mode_dim_string", {"link_mode_dim": "5"}, "heralded_entanglement", 5, None),
        ("link_dim_none", {"link_mode_dim": None}, "heralded_entanglement", 2, None),
        ("truncation_zero", {"truncation": 0}, "unitary", 2, "invalid_profile"),
        ("truncation_one", {"truncation": 1}, "unitary", 2, "invalid_profile"),
    ],
)
def test_custom_override_boundary_values(
    name: str,
    overrides: Any,
    kind: str,
    expected_dim: int,
    error_code_expected: str | None,
) -> None:
    _qutip_available()
    target = [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]
    operation = {"kind": kind, "targets": list(target)}
    if kind == "unitary":
        operation["payload"] = {"kind": "unitary", "gate": "X"}

    response = _call_worker({
        **operation,
        "backend_config": {
            "qutip_node_profile": "custom",
            "qutip_link_profile": "custom",
            "qutip_profile_overrides": overrides,
        },
    }, seed=12345)
    _assert_response(response, success=True)
    _assert_meta(response, "profile", "custom")
    _assert_meta(response, "dim", expected_dim)
    if error_code_expected is None:
        assert response.get("error_category") is None
    else:
        assert response.get("error_category") == "invalid_profile"


@pytest.mark.parametrize(
    "name,leakage_value,expected",
    [
        ("bool_true", True, True),
        ("bool_false", False, False),
        ("on", "on", True),
        ("off", "off", False),
        ("upper_false", "FALSE", False),
        ("int_one", 1, True),
        ("int_zero", 0, False),
    ],
)
def test_custom_leakage_bool_aliases(name: str, leakage_value: Any, expected: bool) -> None:
    _qutip_available()
    response = _call_worker(
        {
            "kind": "unitary",
            "payload": {"kind": "unitary", "gate": "X"},
            "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
            "backend_config": {
                "qutip_node_profile": "custom",
                "qutip_profile_overrides": {"leakage_enabled": leakage_value},
            },
        },
        seed=12345,
    )
    _assert_response(response, success=True)
    _assert_meta(response, "leakage_enabled", expected)


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
                "basis": "Z",
                "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
                "backend_config": {"qutip_node_profile": "standard_qutrit"},
            },
            1.0,
            0.0,
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
        (
            {
                "kind": "measurement",
                "basis": "Z",
                "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
                "backend_config": {
                    "qutip_node_profile": "custom",
                    "qutip_profile_overrides": "{\"node_dim\": 5, \"link_mode_dim\": 6, \"leakage_enabled\": false, \"truncation\": 9}",
                },
            },
            1.0,
            0.0,
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


def test_default_profile_preserves_baseline_compatibility() -> None:
    _qutip_available()
    response = _call_worker(
        {
            "kind": "unitary",
            "payload": {"kind": "unitary", "gate": "X"},
            "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
        },
        seed=12345,
    )
    _assert_response(response, success=True)
    _assert_meta(response, "profile", "standard_light")
    _assert_meta(response, "dim", 2)
    assert response.get("qutip_status") == "implemented"
    assert 0.0 <= response.get("fidelity_estimate", 1.0) <= 1.0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
