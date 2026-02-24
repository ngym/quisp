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


def _call_cluster_worker(
    operation: Dict[str, Any],
    cluster_id: int,
    seed: int = 12345,
) -> Dict[str, Any]:
    operation = dict(operation)
    operation["cluster_id"] = cluster_id
    return _call_worker(operation, seed=seed)


def _clear_qutip_cluster_state() -> None:
    qutip_worker = _qutip_worker_module()
    if hasattr(qutip_worker, "_QUTIP_CLUSTER_STATES"):
        qutip_worker._QUTIP_CLUSTER_STATES.clear()


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
            "invalid_node_profile_empty",
            {
                "kind": "unitary",
                "payload": {"kind": "unitary", "gate": "X"},
                "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
                "backend_config": {"qutip_node_profile": ""},
            },
            [
                ("meta", "profile", ""),
                ("meta", "requested_profile", ""),
                ("meta", "mode", "node"),
                ("meta", "dim", 2),
            ],
        ),
        (
            "invalid_link_profile_empty",
            {
                "kind": "hom_interference",
                "duration": 0.2,
                "targets": [
                    {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0},
                    {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1},
                ],
                "backend_config": {"qutip_link_profile": ""},
            },
            [
                ("meta", "profile", ""),
                ("meta", "requested_profile", ""),
                ("meta", "mode", "link"),
                ("meta", "dim", 2),
            ],
        ),
        (
            "invalid_node_profile_none",
            {
                "kind": "unitary",
                "payload": {"kind": "unitary", "gate": "X"},
                "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
                "backend_config": {"qutip_node_profile": None},
            },
            [
                ("meta", "profile", "none"),
                ("meta", "requested_profile", "none"),
                ("meta", "mode", "node"),
                ("meta", "dim", 2),
            ],
        ),
        (
            "invalid_profile_node_name",
            {
                "kind": "unitary",
                "payload": {"kind": "unitary", "gate": "X"},
                "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
                "backend_config": {"qutip_node_profile": "does_not_exist"},
            },
            [
                ("meta", "profile", "does_not_exist"),
                ("meta", "requested_profile", "does_not_exist"),
                ("meta", "mode", "node"),
                ("meta", "dim", 2),
            ],
        ),
        (
            "invalid_profile_link_name",
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
                ("meta", "profile", "does_not_exist"),
                ("meta", "requested_profile", "does_not_exist"),
                ("meta", "mode", "link"),
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
    _clear_qutip_cluster_state()
    response = _call_worker(operation, seed=12345)
    should_fail = name in {
        "invalid_node_profile_empty",
        "invalid_link_profile_empty",
        "invalid_node_profile_none",
        "invalid_profile_node_name",
        "invalid_profile_link_name",
        "invalid_override_bool",
        "invalid_override_json_type",
    }
    _assert_response(response, success=not should_fail)
    for level, key, expected in checks:
        if level == "meta":
            _assert_meta(response, key, expected)

    if should_fail:
        assert response.get("error_category") == "invalid_profile"

    if name == "invalid_override_json_type":
        _assert_meta_contains(response, "errors", "qutip_profile_overrides must be a JSON string/object")

    if name == "invalid_override_bool":
        _assert_meta_contains(response, "errors", "invalid boolean value")


@pytest.mark.parametrize(
    "name,operation,checks",
    [
        (
            "link_profile_defaulting_on_detection",
            {
                "kind": "detection",
                "targets": [
                    {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0},
                    {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1},
                ],
                "backend_config": {
                    "qutip_node_profile": "standard_qutrit",
                    "qutip_link_profile": "standard_qutrit",
                    "qutip_worker_timeout_ms": 5000,
                    "qutip_backend_class": "qutip_density_matrix",
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
                "kind": "hom_interference",
                "duration": 0.05,
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
    _clear_qutip_cluster_state()
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
        ("node_dim_decimal", {"node_dim": 3.9}, "unitary", 2, "invalid_profile"),
        ("node_dim_negative", {"node_dim": -1}, "unitary", 2, "invalid_profile"),
        ("node_dim_decimal_string", "{\"node_dim\": \"3.7\"}", "unitary", 2, "invalid_profile"),
        ("link_mode_dim_string", {"link_mode_dim": "5"}, "detection", 5, None),
        ("link_dim_none", {"link_mode_dim": None}, "detection", 2, None),
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
    _clear_qutip_cluster_state()
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
    _assert_response(response, success=(error_code_expected is None))
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
    _clear_qutip_cluster_state()
    response = _call_worker(operation, seed=12345)
    _assert_response(response, success=True)
    assert response.get("operation_model") == "sampled_kraus"
    _measurement_probabilities(response, plus, minus)
    assert isinstance(response.get("measured_plus"), bool)
    measured_plus = bool(response.get("measured_plus"))
    branch_probability = response.get("branch_probability")
    assert branch_probability is not None
    if measured_plus:
        assert float(branch_probability) == pytest.approx(plus)
    else:
        assert float(branch_probability) == pytest.approx(minus)


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
    _assert_response(response, success=False)
    assert response.get("error_category") == expected_error_category
    _assert_meta(response, "profile", "custom")


def test_error_channel_loss_profile_uses_distance_and_node_overhead() -> None:
    _qutip_available()
    _clear_qutip_cluster_state()
    target = {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}
    attenuation_db_per_km = 0.2
    length_km = 15
    node_io_overhead_db = 0.8
    node_count = 3
    eta_fiber = 10 ** (-(attenuation_db_per_km * length_km) / 10.0)
    eta_node = 10 ** (-(node_io_overhead_db * node_count) / 10.0)
    expected_loss = pytest.approx(1.0 - (eta_fiber * eta_node), rel=1e-12)

    response = _call_worker(
        {
            "kind": "error_channel",
            "targets": [target],
            "payload": {
                "channel_profile": "loss_channel",
                "channel_loss_rate": 0.0,
                "channel_x_error_rate": 1.0,
                "attenuation_db_per_km": attenuation_db_per_km,
                "length_km": length_km,
                "node_io_overhead_db": node_io_overhead_db,
                "node_count": node_count,
            },
        },
        seed=101,
    )
    _assert_response(response, success=True)
    classical_payload = response.get("classical_payload", {})
    assert float(classical_payload.get("probability", -1.0)) == expected_loss
    assert response.get("outcome_pattern") in {"none", "pass"}


def test_error_channel_loss_uses_legacy_loss_rate_fallback() -> None:
    _qutip_available()
    _clear_qutip_cluster_state()
    target = {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1}
    legacy_loss_rate = 0.35

    response = _call_worker(
        {
            "kind": "error_channel",
            "targets": [target],
            "payload": {
                "channel_profile": "loss_channel",
                "legacy_channel_loss_rate": legacy_loss_rate,
            },
        },
        seed=102,
    )
    _assert_response(response, success=True)
    classical_payload = response.get("classical_payload", {})
    assert float(classical_payload.get("probability", -1.0)) == pytest.approx(legacy_loss_rate, rel=1e-12)


def test_error_channel_profile_is_explicit_only_for_qutip_flip_probability() -> None:
    _qutip_available()
    _clear_qutip_cluster_state()
    target = {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 2}

    response = _call_worker(
        {
            "kind": "error_channel",
            "targets": [target],
            "payload": {
                "channel_profile": "flip_channel",
                "channel_x_error_rate": 1.0,
            },
        },
        seed=303,
    )
    _assert_response(response, success=True)
    classical_payload = response.get("classical_payload", {})
    assert float(classical_payload.get("probability", -1.0)) == pytest.approx(0.0, abs=1e-12)
    assert response.get("outcome_pattern") == "pass"


_ADVANCED_SUCCESS_CASES: list[tuple[str, Dict[str, Any]]] = [
    ("kerr", {"kind": "kerr", "params": [0.3], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}], "payload": {"strength": 0.3}}),
    ("cross_kerr", {"kind": "cross_kerr", "params": [0.2], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1}, {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 2}] }),
    ("beam_splitter", {"kind": "beam_splitter", "params": [0.15], "duration": 0.2, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 3}, {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 4}] }),
    ("loss", {"kind": "loss", "params": [0.05], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 5}]}),
    ("decoherence", {"kind": "decoherence", "params": [0.04], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 6}]}),
    ("phase_shift", {"kind": "phase_shift", "params": [0.6], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 7}]}),
    ("phase_modulation", {"kind": "phase_modulation", "params": [0.6], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 8}]}),
    ("self_phase_modulation", {"kind": "self_phase_modulation", "params": [0.6], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 9}]}),
    ("cross_phase_modulation", {"kind": "cross_phase_modulation", "params": [0.1], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 10}, {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 11}] }),
    ("nonlinear", {"kind": "nonlinear", "params": [0.1], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 12}]}),
    ("polarization_rotation", {"kind": "polarization_rotation", "params": [0.2], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 13}]}),
    ("mode_coupling", {"kind": "mode_coupling", "params": [0.2], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 14}, {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 15}] }),
    ("two_mode_squeezing", {"kind": "two_mode_squeezing", "params": [0.11], "duration": 0.1, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 16}, {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 17}]}),
    ("detection", {"kind": "detection", "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 18}], "payload": {"dark_count": 0.02}}),
    (
        "detection",
        {
            "kind": "detection",
            "targets": [
                {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 19},
                {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 20},
            ],
            "payload": {"dark_count": 0.02},
        },
    ),
    ("dispersion", {"kind": "dispersion", "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 20}], "payload": {"strength": 0.02}}),
    ("squeezing", {"kind": "squeezing", "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 21}], "payload": {"strength": 0.04}}),
    ("fock_loss", {"kind": "fock_loss", "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 22}], "params": [0.03]}),
    ("photon_number_cutoff", {"kind": "photon_number_cutoff", "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 23}], "params": [4]}),
    ("loss_mode", {"kind": "loss_mode", "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 24}], "payload": {"coupling": 0.02}}),
    ("multiphoton", {"kind": "multiphoton", "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 25}], "payload": {"strength": 0.02}}),
    ("source_multiphoton", {"kind": "source_multiphoton", "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 26}], "payload": {"strength": 0.02}}),
    ("hom_interference", {"kind": "hom_interference", "duration": 0.2, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 27}, {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 28}], "payload": {"visibility": 0.92}}),
    ("photon_emission", {"kind": "photon_emission", "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 30}], "payload": {"efficiency": 0.9}}),
    ("photon_collect", {"kind": "photon_collect", "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 31}], "payload": {"coupling": 0.8}}),
    ("photon_propagation", {"kind": "photon_propagation", "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 32}], "payload": {"attenuation": 0.1, "phase_dispersion": 0.02}}),
    ("reset", {"kind": "reset", "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 29}], "duration": 0.2}),
    ("timing_jitter", {"kind": "timing_jitter", "duration": 0.3, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 30}], "params": [0.11]}),
    ("jitter", {"kind": "jitter", "duration": 0.3, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 31}], "params": [0.11]}),
    ("delay", {"kind": "delay", "duration": 0.4, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 32}], "params": [0.1], "payload": {"rate": 0.05}}),
    ("hamiltonian", {"kind": "hamiltonian", "duration": 0.2, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 33}], "payload": {"expr": "sx"}}),
    ("lindblad", {"kind": "lindblad", "duration": 0.2, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 34}], "payload": {"collapse": ["sx"]}}),
    ("dephasing", {"kind": "dephasing", "params": [0.03], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 35}]}),
    ("attenuation", {"kind": "attenuation", "params": [0.03], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 36}]}),
    ("phaseflip", {"kind": "phaseflip", "params": [0.03], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 37}]}),
    ("bitflip", {"kind": "bitflip", "params": [0.03], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 38}]}),
    ("depolarizing", {"kind": "depolarizing", "params": [0.03], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 39}]}),
    ("polarization_decoherence", {"kind": "polarization_decoherence", "params": [0.03], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 40}]}),
    ("thermal_relaxation", {"kind": "thermal_relaxation", "params": [0.03], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 41}]}),
]


@pytest.mark.parametrize("kind,operation", _ADVANCED_SUCCESS_CASES)
def test_supported_advanced_kinds_cluster_success(kind: str, operation: Dict[str, Any]) -> None:
    del kind
    _qutip_available()
    _clear_qutip_cluster_state()
    response = _call_worker(operation, seed=555)
    _assert_response(response, success=True)
    qutip_worker = _qutip_worker_module()
    expected_model = qutip_worker._operation_model_for_kind(qutip_worker._canonicalize_kind(operation["kind"]))
    assert response.get("operation_model") == expected_model
    assert response.get("error_category") is None


def test_detection_success_probability_depends_on_cluster_state() -> None:
    _qutip_available()
    _clear_qutip_cluster_state()
    target0 = {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}
    cluster_id = 9001

    response_fail = _call_cluster_worker(
        {
            "kind": "detection",
            "targets": [target0],
            "backend_config": {
                "qutip_link_profile": "standard_light",
            },
        },
        cluster_id=cluster_id,
        seed=777,
    )
    _assert_response(response_fail, success=True)
    assert response_fail.get("operation_model") == "sampled_kraus"
    assert response_fail.get("outcome") == "no_click"
    fail_success_probability = float(response_fail.get("meta", {}).get("detection_success_probability", 0.0))
    fail_failure_probability = float(response_fail.get("meta", {}).get("detection_failure_probability", 1.0))
    assert fail_success_probability == pytest.approx(0.0)
    assert fail_failure_probability == pytest.approx(1.0)
    assert float(response_fail.get("branch_probability", -1.0)) == pytest.approx(1.0)
    assert response_fail.get("measured_plus") is False

    response_success = _call_cluster_worker(
        {
            "kind": "detection",
            "targets": [target0],
            "backend_config": {
                "qutip_link_profile": "standard_light",
            },
            "payload": {"dark_count": 1.0},
        },
        cluster_id=cluster_id,
        seed=778,
    )
    _assert_response(response_success, success=True)
    assert response_success.get("operation_model") == "sampled_kraus"
    assert response_success.get("outcome") == "click"
    success_success_probability = float(response_success.get("meta", {}).get("detection_success_probability", 1.0))
    success_failure_probability = float(response_success.get("meta", {}).get("detection_failure_probability", 0.0))
    assert success_success_probability == pytest.approx(1.0)
    assert success_failure_probability == pytest.approx(0.0)
    assert float(response_success.get("branch_probability", -1.0)) == pytest.approx(1.0)
    assert response_success.get("measured_plus") is True


def test_photon_pipeline_representation_transitions() -> None:
    _qutip_available()
    _clear_qutip_cluster_state()

    cluster_id = 5001
    base_target = {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}
    second_target = {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1}
    profile = {"qutip_link_profile": "standard_qutrit"}

    response_emission = _call_cluster_worker(
        {
            "kind": "photon_emission",
            "targets": [base_target],
            "payload": {"efficiency": 0.93},
            "backend_config": profile,
        },
        cluster_id=cluster_id,
        seed=501,
    )
    _assert_response(response_emission, success=True)
    _assert_meta(response_emission, "cluster_id", cluster_id)
    _assert_meta(response_emission, "cluster_mode", "link")
    _assert_meta(response_emission, "cluster_representation", "emission")
    _assert_meta(response_emission, "cluster_size", 1)

    response_collect = _call_cluster_worker(
        {
            "kind": "photon_collect",
            "targets": [base_target],
            "payload": {"coupling": 0.75},
            "backend_config": profile,
        },
        cluster_id=cluster_id,
        seed=502,
    )
    _assert_response(response_collect, success=True)
    _assert_meta(response_collect, "cluster_representation", "collect")
    _assert_meta(response_collect, "cluster_size", 1)
    transition_collect = response_collect.get("meta", {}).get("cluster_representation_transition", "")
    assert transition_collect.startswith("link/emission->link/collect")

    response_propagation = _call_cluster_worker(
        {
            "kind": "photon_propagation",
            "targets": [base_target],
            "payload": {"attenuation": 0.08, "phase_dispersion": 0.05},
            "duration": 0.2,
            "backend_config": profile,
        },
        cluster_id=cluster_id,
        seed=503,
    )
    _assert_response(response_propagation, success=True)
    _assert_meta(response_propagation, "cluster_representation", "propagation")
    _assert_meta(response_propagation, "cluster_size", 1)
    transition_propagation = response_propagation.get("meta", {}).get("cluster_representation_transition", "")
    assert transition_propagation.startswith("link/collect->link/propagation")
    _assert_meta(response_propagation, "propagation_attenuation", 0.08)
    _assert_meta(response_propagation, "propagation_dispersion", 0.05)

    response_hom = _call_cluster_worker(
        {
            "kind": "hom_interference",
            "duration": 0.3,
            "targets": [base_target, second_target],
            "payload": {"visibility": 0.9},
            "backend_config": profile,
        },
        cluster_id=cluster_id,
        seed=504,
    )
    _assert_response(response_hom, success=True)
    _assert_meta(response_hom, "cluster_representation", "hom_interference")
    _assert_meta(response_hom, "cluster_id", cluster_id)
    _assert_meta(response_hom, "cluster_size", 2)
    transition_hom = response_hom.get("meta", {}).get("cluster_representation_transition", "")
    assert transition_hom.startswith("link/propagation->link/hom_interference")


_ADVANCED_SINGLE_TARGET_INVALID_CASES = [
    ("cross_kerr", {"kind": "cross_kerr", "params": [0.2], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}] }),
    ("beam_splitter", {"kind": "beam_splitter", "params": [0.2], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1}] }),
    ("two_mode_squeezing", {"kind": "two_mode_squeezing", "params": [0.2], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 2}] }),
    ("mode_coupling", {"kind": "mode_coupling", "params": [0.2], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 3}] }),
]


@pytest.mark.parametrize("kind,operation", _ADVANCED_SINGLE_TARGET_INVALID_CASES)
def test_two_target_advanced_kinds_reject_single_target(kind: str, operation: Dict[str, Any]) -> None:
    _qutip_available()
    _clear_qutip_cluster_state()
    response = _call_worker(operation, seed=556)
    assert response.get("success") is False
    assert response.get("error_category") == "invalid_payload"
    message = str(response.get("message", "")).lower()
    assert ("at least 2 target" in message) or ("exactly 2 target" in message)


def test_cluster_state_isolated_profiles() -> None:
    _qutip_available()
    _clear_qutip_cluster_state()

    qutip_worker = _qutip_worker_module()
    response_node = _call_cluster_worker(
        {
            "kind": "unitary",
            "payload": {"kind": "unitary", "gate": "X"},
            "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
            "backend_config": {"qutip_node_profile": "standard_qutrit"},
        },
        cluster_id=3001,
        seed=100,
    )
    _assert_response(response_node, success=True)
    _assert_meta(response_node, "cluster_id", 3001)
    _assert_meta(response_node, "cluster_size", 1)
    _assert_meta(response_node, "cluster_mode", "node")

    response_node_2 = _call_cluster_worker(
        {
            "kind": "unitary",
            "payload": {"kind": "unitary", "gate": "Y"},
            "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1}],
            "backend_config": {"qutip_node_profile": "standard_qutrit"},
        },
        cluster_id=3002,
        seed=100,
    )
    _assert_response(response_node_2, success=True)
    _assert_meta(response_node_2, "cluster_id", 3002)
    _assert_meta(response_node_2, "cluster_size", 1)
    _assert_meta(response_node_2, "cluster_mode", "node")

    assert (3001, "node") in qutip_worker._QUTIP_CLUSTER_STATES
    assert (3002, "node") in qutip_worker._QUTIP_CLUSTER_STATES
    assert len(qutip_worker._QUTIP_CLUSTER_STATES) >= 2


def test_cluster_state_node_and_link_modes_separate() -> None:
    _qutip_available()
    _clear_qutip_cluster_state()

    qutip_worker = _qutip_worker_module()
    cluster_id = 3003

    response_node = _call_cluster_worker(
        {
            "kind": "unitary",
            "payload": {"kind": "unitary", "gate": "X"},
            "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
            "backend_config": {"qutip_node_profile": "standard_qutrit"},
        },
        cluster_id=cluster_id,
        seed=200,
    )
    _assert_response(response_node, success=True)
    _assert_meta(response_node, "cluster_mode", "node")
    _assert_meta(response_node, "cluster_size", 1)

    response_link = _call_cluster_worker(
        {
            "kind": "loss",
            "targets": [
                {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1},
            ],
            "payload": {"p": 0.05},
            "backend_config": {"qutip_link_profile": "standard_qutrit"},
        },
        cluster_id=cluster_id,
        seed=201,
    )
    _assert_response(response_link, success=True)
    _assert_meta(response_link, "cluster_mode", "link")
    _assert_meta(response_link, "cluster_size", 1)

    assert (cluster_id, "node") in qutip_worker._QUTIP_CLUSTER_STATES
    assert (cluster_id, "link") in qutip_worker._QUTIP_CLUSTER_STATES
    assert len(qutip_worker._QUTIP_CLUSTER_STATES) >= 2


def test_cluster_state_entangle_measurement_detach() -> None:
    _qutip_available()
    _clear_qutip_cluster_state()
    qutip_worker = _qutip_worker_module()

    response_entangle = _call_cluster_worker(
        {
            "kind": "unitary",
            "payload": {"kind": "unitary", "gate": "CNOT"},
            "targets": [
                {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0},
                {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1},
            ],
            "backend_config": {"qutip_node_profile": "standard_qutrit"},
        },
        cluster_id=4001,
        seed=101,
    )
    _assert_response(response_entangle, success=True)
    _assert_meta(response_entangle, "cluster_id", 4001)
    _assert_meta(response_entangle, "cluster_size", 2)

    response_measure_first = _call_cluster_worker(
        {
            "kind": "measurement",
            "basis": "Z",
            "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
            "backend_config": {"qutip_node_profile": "standard_qutrit"},
        },
        cluster_id=4001,
        seed=102,
    )
    _assert_response(response_measure_first, success=True)
    _assert_meta(response_measure_first, "cluster_id", 4001)
    _assert_meta(response_measure_first, "cluster_size", 1)

    response_measure_second = _call_cluster_worker(
        {
            "kind": "measurement",
            "basis": "Z",
            "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1}],
            "backend_config": {"qutip_node_profile": "standard_qutrit"},
        },
        cluster_id=4001,
        seed=103,
    )
    _assert_response(response_measure_second, success=True)
    assert "cluster_size" not in response_measure_second.get("meta", {})
    assert (4001, "node") not in qutip_worker._QUTIP_CLUSTER_STATES


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
    assert response.get("operation_model") == "unitary"
    assert 0.0 <= response.get("fidelity_estimate", 1.0) <= 1.0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
