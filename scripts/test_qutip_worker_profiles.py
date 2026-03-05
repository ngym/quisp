#!/usr/bin/env python3
"""Pytest coverage for qutip worker profile routing and metadata.

These tests exercise profile resolution paths added for node/link profile support,
including custom overrides and invalid fallback behavior.
"""

from __future__ import annotations

import os
import math
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
    operation.setdefault("cluster_id", int(seed) + 100000)
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


def test_profile_default_metadata() -> None:
    _qutip_available()
    _clear_qutip_cluster_state()
    response = _call_worker(
        {
            "kind": "unitary",
            "payload": {"kind": "unitary", "gate": "X"},
            "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
            "backend_config": {},
        },
        seed=12345,
    )
    _assert_response(response, success=True)
    _assert_meta(response, "profile", "standard_light")
    _assert_meta(response, "requested_profile", "standard_light")
    _assert_meta(response, "dim", 2)
    _assert_profile_meta_shape(response, {"profile", "requested_profile", "dim", "truncation", "errors", "leakage_enabled"})


def test_profile_standard_qutrit_uses_single_dim_for_all_kinds() -> None:
    _qutip_available()
    _clear_qutip_cluster_state()
    target0 = {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}
    target1 = {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1}
    config = {"qutip_profile": "standard_qutrit"}

    response_unitary = _call_worker(
        {
            "kind": "unitary",
            "payload": {"kind": "unitary", "gate": "X"},
            "targets": [target0],
            "backend_config": config,
        },
        seed=123,
    )
    response_detection = _call_worker(
        {
            "kind": "detection",
            "targets": [target0, target1],
            "backend_config": config,
        },
        seed=124,
    )
    _assert_response(response_unitary, success=True)
    _assert_response(response_detection, success=True)
    _assert_meta(response_unitary, "profile", "standard_qutrit")
    _assert_meta(response_detection, "profile", "standard_qutrit")
    _assert_meta(response_unitary, "dim", 4)
    _assert_meta(response_detection, "dim", 4)


def test_profile_custom_dim_override() -> None:
    _qutip_available()
    _clear_qutip_cluster_state()
    response = _call_worker(
        {
            "kind": "unitary",
            "payload": {"kind": "unitary", "gate": "X"},
            "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
            "backend_config": {"qutip_profile": "custom", "qutip_profile_overrides": {"dim": 5, "truncation": 9}},
        },
        seed=456,
    )
    _assert_response(response, success=True)
    _assert_meta(response, "profile", "custom")
    _assert_meta(response, "dim", 5)
    _assert_meta(response, "truncation", 9)


@pytest.mark.parametrize("leakage_value,expected", [(True, True), (False, False), ("on", True), ("off", False), ("FALSE", False), (1, True), (0, False)])
def test_profile_custom_leakage_bool_aliases(leakage_value: Any, expected: bool) -> None:
    _qutip_available()
    response = _call_worker(
        {
            "kind": "unitary",
            "payload": {"kind": "unitary", "gate": "X"},
            "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
            "backend_config": {"qutip_profile": "custom", "qutip_profile_overrides": {"leakage_enabled": leakage_value}},
        },
        seed=789,
    )
    _assert_response(response, success=True)
    _assert_meta(response, "leakage_enabled", expected)


@pytest.mark.parametrize(
    "backend_config",
    [
        {"qutip_node_profile": "standard_qutrit"},
        {"qutip_link_profile": "standard_qutrit"},
        {"qutip_node_profile": "standard_qutrit", "qutip_link_profile": "standard_light"},
    ],
)
def test_profile_legacy_keys_rejected(backend_config: Dict[str, Any]) -> None:
    _qutip_available()
    response = _call_worker(
        {
            "kind": "unitary",
            "payload": {"kind": "unitary", "gate": "X"},
            "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
            "backend_config": backend_config,
        },
        seed=1001,
    )
    _assert_response(response, success=False)
    assert response.get("error_category") == "invalid_profile"
    _assert_meta_contains(response, "errors", "legacy profile keys are not supported")


@pytest.mark.parametrize(
    "overrides",
    [
        {"node_dim": 4},
        {"link_mode_dim": 5},
        {"node_dim": 4, "link_mode_dim": 5},
        "{\"node_dim\": 4}",
    ],
)
def test_profile_legacy_custom_override_keys_rejected(overrides: Any) -> None:
    _qutip_available()
    response = _call_worker(
        {
            "kind": "unitary",
            "payload": {"kind": "unitary", "gate": "X"},
            "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
            "backend_config": {"qutip_profile": "custom", "qutip_profile_overrides": overrides},
        },
        seed=1002,
    )
    _assert_response(response, success=False)
    assert response.get("error_category") == "invalid_profile"
    _assert_meta_contains(response, "errors", "legacy custom override keys are not supported")


@pytest.mark.parametrize(
    "overrides,expected_dim,error_expected",
    [
        ({"dim": "4"}, 4, None),
        ({"dim": None}, 2, None),
        ({"dim": 3.9}, 2, "invalid_profile"),
        ({"dim": -1}, 2, "invalid_profile"),
        ("{\"dim\": \"3.7\"}", 2, "invalid_profile"),
        ({"truncation": 0}, 2, "invalid_profile"),
        ({"truncation": 1}, 2, "invalid_profile"),
    ],
)
def test_profile_custom_override_boundary_values(overrides: Any, expected_dim: int, error_expected: Optional[str]) -> None:
    _qutip_available()
    response = _call_worker(
        {
            "kind": "unitary",
            "payload": {"kind": "unitary", "gate": "X"},
            "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
            "backend_config": {"qutip_profile": "custom", "qutip_profile_overrides": overrides},
        },
        seed=1003,
    )
    _assert_response(response, success=(error_expected is None))
    _assert_meta(response, "profile", "custom")
    _assert_meta(response, "dim", expected_dim)
    if error_expected is None:
        assert response.get("error_category") is None
    else:
        assert response.get("error_category") == error_expected


@pytest.mark.parametrize(
    "operation,plus,minus",
    [
        (
            {
                "kind": "measurement",
                "basis": "X",
                "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
                "backend_config": {"qutip_profile": "standard_qutrit"},
            },
            0.5,
            0.5,
        ),
        (
            {
                "kind": "measurement",
                "basis": "Z",
                "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
                "backend_config": {"qutip_profile": "standard_qutrit"},
            },
            1.0,
            0.0,
        ),
        (
            {
                "kind": "measurement",
                "basis": "BELL",
                "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
                "backend_config": {"qutip_profile": "custom", "qutip_profile_overrides": {"dim": 3}},
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
                    "qutip_profile": "custom",
                    "qutip_profile_overrides": "{\"dim\": 5, \"leakage_enabled\": false, \"truncation\": 9}",
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
                    "qutip_profile": "custom",
                    "qutip_profile_overrides": "[1,2,3]",
                },
            },
            "invalid_profile",
        ),
        (
            {
                "kind": "measurement",
                "basis": "Z",
                "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
                "backend_config": {
                    "qutip_profile": "custom",
                    "qutip_profile_overrides": 123,
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
                "qutip_profile": "standard_light",
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
                "qutip_profile": "standard_light",
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


def test_detection_two_photon_pattern_for_psi_plus() -> None:
    _qutip_available()
    _clear_qutip_cluster_state()
    target0 = {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 10}
    target1 = {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 11}
    cluster_id = 9101

    _call_cluster_worker(
        {"kind": "unitary", "targets": [target1], "payload": {"gate": "X"}},
        cluster_id=cluster_id,
        seed=111,
    )
    _call_cluster_worker(
        {
            "kind": "unitary",
            "targets": [target0],
            "payload": {"gate": "H"},
        },
        cluster_id=cluster_id,
        seed=112,
    )
    _call_cluster_worker(
        {
            "kind": "unitary",
            "targets": [target0, target1],
            "payload": {"gate": "CNOT"},
        },
        cluster_id=cluster_id,
        seed=113,
    )
    _call_cluster_worker(
        {
            "kind": "hom_interference",
            "targets": [target0, target1],
        },
        cluster_id=cluster_id,
        seed=114,
    )

    response = _call_cluster_worker(
        {
            "kind": "detection",
            "targets": [target0, target1],
            "payload": {"efficiency": 1.0, "visibility": 1.0},
        },
        cluster_id=cluster_id,
        seed=115,
    )
    _assert_response(response, success=True)
    assert response.get("outcome_pattern") in {"d0,d1", "d2,d3"}
    assert response.get("detection_click_count") == 2


def test_detection_two_photon_pattern_for_psi_minus() -> None:
    _qutip_available()
    _clear_qutip_cluster_state()
    target0 = {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 12}
    target1 = {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 13}
    cluster_id = 9102

    _call_cluster_worker(
        {"kind": "unitary", "targets": [target1], "payload": {"gate": "X"}},
        cluster_id=cluster_id,
        seed=121,
    )
    _call_cluster_worker(
        {"kind": "unitary", "targets": [target0], "payload": {"gate": "H"}},
        cluster_id=cluster_id,
        seed=122,
    )
    _call_cluster_worker(
        {
            "kind": "unitary",
            "targets": [target0, target1],
            "payload": {"gate": "CNOT"},
        },
        cluster_id=cluster_id,
        seed=123,
    )
    _call_cluster_worker(
        {
            "kind": "unitary",
            "targets": [target1],
            "payload": {"gate": "Z"},
        },
        cluster_id=cluster_id,
        seed=124,
    )
    _call_cluster_worker(
        {
            "kind": "hom_interference",
            "targets": [target0, target1],
        },
        cluster_id=cluster_id,
        seed=125,
    )

    response = _call_cluster_worker(
        {
            "kind": "detection",
            "targets": [target0, target1],
            "payload": {"efficiency": 1.0, "visibility": 1.0},
        },
        cluster_id=cluster_id,
        seed=126,
    )
    _assert_response(response, success=True)
    assert response.get("outcome_pattern") in {"d0,d3", "d1,d2"}
    assert response.get("detection_click_count") == 2


def test_hom_interference_defaults_to_50_50_angle_when_omitted() -> None:
    _qutip_available()
    _clear_qutip_cluster_state()
    target0 = {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 20}
    target1 = {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 21}
    target2 = {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 22}
    target3 = {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 23}
    cluster_default = 9301
    cluster_explicit = 9302

    response_default = _call_cluster_worker(
        {"kind": "hom_interference", "targets": [target0, target1]},
        cluster_id=cluster_default,
        seed=930,
    )
    _assert_response(response_default, success=True)
    assert float(response_default.get("meta", {}).get("hom_interference_angle")) == pytest.approx(math.pi / 4)
    assert float(response_default.get("meta", {}).get("hom_interference_duration")) == pytest.approx(1.0)

    response_explicit = _call_cluster_worker(
        {
            "kind": "hom_interference",
            "targets": [target2, target3],
            "payload": {"theta": math.pi / 4},
        },
        cluster_id=cluster_explicit,
        seed=930,
    )
    _assert_response(response_explicit, success=True)
    assert float(response_explicit.get("meta", {}).get("hom_interference_angle")) == pytest.approx(math.pi / 4)
    assert response_default.get("meta", {}).get("hom_interference_angle") == response_explicit.get("meta", {}).get("hom_interference_angle")

    detection_default = _call_cluster_worker(
        {
            "kind": "detection",
            "targets": [target0, target1],
            "payload": {"efficiency": 1.0, "visibility": 1.0},
        },
        cluster_id=cluster_default,
        seed=931,
    )
    detection_explicit = _call_cluster_worker(
        {
            "kind": "detection",
            "targets": [target2, target3],
            "payload": {"efficiency": 1.0, "visibility": 1.0},
        },
        cluster_id=cluster_explicit,
        seed=931,
    )
    _assert_response(detection_default, success=True)
    _assert_response(detection_explicit, success=True)
    assert detection_default.get("outcome_pattern") == detection_explicit.get("outcome_pattern")


def test_detection_two_photon_visibility_extremes() -> None:
    _qutip_available()
    _clear_qutip_cluster_state()
    target0 = {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 30}
    target1 = {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 31}
    target2 = {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 32}
    target3 = {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 33}
    cluster_plus = 9303
    cluster_minus = 9304

    _call_cluster_worker(
        {"kind": "unitary", "targets": [target1], "payload": {"gate": "X"}},
        cluster_id=cluster_plus,
        seed=9311,
    )
    _call_cluster_worker(
        {"kind": "unitary", "targets": [target0], "payload": {"gate": "H"}},
        cluster_id=cluster_plus,
        seed=9312,
    )
    _call_cluster_worker(
        {
            "kind": "unitary",
            "targets": [target0, target1],
            "payload": {"gate": "CNOT"},
        },
        cluster_id=cluster_plus,
        seed=9313,
    )
    _call_cluster_worker(
        {"kind": "hom_interference", "targets": [target0, target1]},
        cluster_id=cluster_plus,
        seed=9314,
    )

    response_plus_vis0 = _call_cluster_worker(
        {
            "kind": "detection",
            "targets": [target0, target1],
            "payload": {"efficiency": 1.0, "visibility": 0.0},
        },
        cluster_id=cluster_plus,
        seed=9315,
    )
    _assert_response(response_plus_vis0, success=True)
    assert response_plus_vis0.get("outcome_pattern") == "none"

    response_plus_vis1 = _call_cluster_worker(
        {
            "kind": "detection",
            "targets": [target0, target1],
            "payload": {"efficiency": 1.0, "visibility": 1.0},
        },
        cluster_id=cluster_plus,
        seed=9316,
    )
    _assert_response(response_plus_vis1, success=True)
    assert response_plus_vis1.get("outcome_pattern") in {"d0,d1", "d2,d3"}

    _call_cluster_worker(
        {"kind": "unitary", "targets": [target3], "payload": {"gate": "X"}},
        cluster_id=cluster_minus,
        seed=9321,
    )
    _call_cluster_worker(
        {"kind": "unitary", "targets": [target2], "payload": {"gate": "H"}},
        cluster_id=cluster_minus,
        seed=9322,
    )
    _call_cluster_worker(
        {"kind": "unitary", "targets": [target2, target3], "payload": {"gate": "CNOT"}},
        cluster_id=cluster_minus,
        seed=9323,
    )
    _call_cluster_worker(
        {"kind": "unitary", "targets": [target3], "payload": {"gate": "Z"}},
        cluster_id=cluster_minus,
        seed=9324,
    )
    _call_cluster_worker(
        {"kind": "hom_interference", "targets": [target2, target3]},
        cluster_id=cluster_minus,
        seed=9325,
    )

    response_minus_vis0 = _call_cluster_worker(
        {
            "kind": "detection",
            "targets": [target2, target3],
            "payload": {"efficiency": 1.0, "visibility": 0.0},
        },
        cluster_id=cluster_minus,
        seed=9326,
    )
    _assert_response(response_minus_vis0, success=True)
    assert response_minus_vis0.get("outcome_pattern") == "none"

    response_minus_vis1 = _call_cluster_worker(
        {
            "kind": "detection",
            "targets": [target2, target3],
            "payload": {"efficiency": 1.0, "visibility": 1.0},
        },
        cluster_id=cluster_minus,
        seed=9327,
    )
    _assert_response(response_minus_vis1, success=True)
    assert response_minus_vis1.get("outcome_pattern") in {"d0,d3", "d1,d2"}


def test_photon_pipeline_representation_transitions() -> None:
    _qutip_available()
    _clear_qutip_cluster_state()

    cluster_id = 5001
    base_target = {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}
    second_target = {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1}
    profile = {"qutip_profile": "standard_qutrit"}

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
    _assert_meta(response_emission, "cluster_representation", "cluster_dm")
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
    _assert_meta(response_collect, "cluster_representation", "cluster_dm")
    _assert_meta(response_collect, "cluster_size", 1)

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
    _assert_meta(response_propagation, "cluster_representation", "cluster_dm")
    _assert_meta(response_propagation, "cluster_size", 1)
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
    _assert_meta(response_hom, "cluster_representation", "cluster_dm")
    _assert_meta(response_hom, "cluster_id", cluster_id)
    _assert_meta(response_hom, "cluster_size", 2)


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
            "backend_config": {"qutip_profile": "standard_qutrit"},
        },
        cluster_id=3001,
        seed=100,
    )
    _assert_response(response_node, success=True)
    _assert_meta(response_node, "cluster_id", 3001)
    _assert_meta(response_node, "cluster_size", 1)

    response_node_2 = _call_cluster_worker(
        {
            "kind": "unitary",
            "payload": {"kind": "unitary", "gate": "Y"},
            "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1}],
            "backend_config": {"qutip_profile": "standard_qutrit"},
        },
        cluster_id=3002,
        seed=100,
    )
    _assert_response(response_node_2, success=True)
    _assert_meta(response_node_2, "cluster_id", 3002)
    _assert_meta(response_node_2, "cluster_size", 1)

    assert 3001 in qutip_worker._QUTIP_CLUSTER_STATES
    assert 3002 in qutip_worker._QUTIP_CLUSTER_STATES
    assert len(qutip_worker._QUTIP_CLUSTER_STATES) >= 2


def test_cluster_state_single_cluster_id_across_mixed_operations() -> None:
    _qutip_available()
    _clear_qutip_cluster_state()

    qutip_worker = _qutip_worker_module()
    cluster_id = 3003

    response_node = _call_cluster_worker(
        {
            "kind": "unitary",
            "payload": {"kind": "unitary", "gate": "X"},
            "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
            "backend_config": {"qutip_profile": "standard_qutrit"},
        },
        cluster_id=cluster_id,
        seed=200,
    )
    _assert_response(response_node, success=True)
    _assert_meta(response_node, "cluster_size", 1)

    response_hom = _call_cluster_worker(
        {
            "kind": "hom_interference",
            "targets": [
                {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0},
                {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1},
            ],
            "duration": 0.1,
            "backend_config": {"qutip_profile": "standard_qutrit"},
        },
        cluster_id=cluster_id,
        seed=201,
    )
    _assert_response(response_hom, success=True)
    _assert_meta(response_hom, "cluster_size", 2)

    response_detection = _call_cluster_worker(
        {
            "kind": "detection",
            "targets": [
                {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0},
                {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1},
            ],
            "payload": {"efficiency": 1.0, "visibility": 1.0},
            "backend_config": {"qutip_profile": "standard_qutrit"},
        },
        cluster_id=cluster_id,
        seed=202,
    )
    _assert_response(response_detection, success=True)

    response_error = _call_cluster_worker(
        {
            "kind": "error_channel",
            "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1}],
            "payload": {"channel_profile": "loss_channel", "channel_loss_rate": 0.0},
            "backend_config": {"qutip_profile": "standard_qutrit"},
        },
        cluster_id=cluster_id,
        seed=203,
    )
    _assert_response(response_error, success=True)
    assert cluster_id in qutip_worker._QUTIP_CLUSTER_STATES
    assert len(qutip_worker._QUTIP_CLUSTER_STATES) == 1


def test_cluster_meta_has_no_mode_and_cluster_key_is_plain_id() -> None:
    _qutip_available()
    _clear_qutip_cluster_state()
    cluster_id = 3010
    response = _call_cluster_worker(
        {
            "kind": "unitary",
            "payload": {"kind": "unitary", "gate": "X"},
            "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
            "backend_config": {"qutip_profile": "standard_qutrit"},
        },
        cluster_id=cluster_id,
        seed=333,
    )
    _assert_response(response, success=True)
    meta = response.get("meta", {})
    assert "cluster_mode" not in meta
    assert str(meta.get("cluster_key")) == str(cluster_id)
    assert ":" not in str(meta.get("cluster_key"))


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
            "backend_config": {"qutip_profile": "standard_qutrit"},
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
            "backend_config": {"qutip_profile": "standard_qutrit"},
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
            "backend_config": {"qutip_profile": "standard_qutrit"},
        },
        cluster_id=4001,
        seed=103,
    )
    _assert_response(response_measure_second, success=True)
    assert "cluster_size" not in response_measure_second.get("meta", {})
    assert 4001 not in qutip_worker._QUTIP_CLUSTER_STATES


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


def test_normalize_detector_pattern_orders_and_lowercases_tokens() -> None:
    worker = _qutip_worker_module()

    assert worker._normalize_detector_pattern("d1,d0") == "d0,d1"
    assert worker._normalize_detector_pattern(" D2 , d3 ") == "d2,d3"
    assert worker._normalize_detector_pattern("D0,d3") == "d0,d3"
    assert worker._normalize_detector_pattern("") == ""


def test_compute_channel_loss_probability_with_distance_and_overhead_model() -> None:
    worker = _qutip_worker_module()

    payload = {
        "attenuation_db_per_km": 0.2,
        "channel_length_km": 10.0,
        "node_io_overhead_db": 0.1,
        "node_count": 2,
    }
    loss_probability = float(worker._compute_channel_loss_probability(payload))
    expected_eta_fiber = 10 ** (-(0.2 * 10.0) / 10.0)
    expected_eta_node = 10 ** (-(0.1 * 2) / 10.0)
    expected_loss = 1.0 - (expected_eta_fiber * expected_eta_node)
    assert loss_probability == pytest.approx(expected_loss, rel=1e-8)


def test_compute_channel_loss_probability_falls_back_to_legacy_loss_rate() -> None:
    worker = _qutip_worker_module()

    payload = {
        "legacy_channel_loss_rate": 0.2,
        "channel_loss_rate": 0.3,
    }
    loss_probability = float(worker._compute_channel_loss_probability(payload))
    assert loss_probability == pytest.approx(0.2, rel=1e-8)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
