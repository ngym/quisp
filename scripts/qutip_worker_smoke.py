#!/usr/bin/env python3
"""Smoke checks for qutip worker operation coverage.

This script validates that the requested operations are accepted by the worker
and returns response fields in the expected shape. It intentionally focuses on
surface-level contract checks (success/failure and field validity), not full
quantum-physics numerics.
"""

from __future__ import annotations

import argparse
import math
import tempfile
from typing import Any, Dict
import os
import sys


def _qutip_available() -> bool:
  if not os.environ.get("MPLCONFIGDIR"):
    temp_dir = os.path.join(tempfile.gettempdir(), "qutip_worker_smoke_matplotlib")
    os.makedirs(temp_dir, exist_ok=True)
    os.environ["MPLCONFIGDIR"] = temp_dir

  try:
    import qutip  # noqa: F401
    import qutip_qip  # noqa: F401
    import qutip.qip  # noqa: F401
    return True
  except Exception as exc:
    print(f"qutip import failed: {exc}")
    return False


def _call_worker(operation: Dict[str, Any], seed: int = 12345) -> Dict[str, Any]:
  scripts_dir = os.path.dirname(os.path.abspath(__file__))
  repo_root = os.path.dirname(scripts_dir)
  if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

  import scripts.qutip_worker as qutip_worker

  operation = dict(operation)
  backend_config = dict(
      operation.pop("backend_config", {
          "python_executable": "python3",
          "qutip_backend_class": "qutip_density_matrix",
          "qutip_worker_timeout_ms": 5000,
      })
  )
  request = {
      "seed": seed,
      "operation": operation,
      "backend_config": backend_config,
  }
  return qutip_worker.run_operation(request)


def _assert_fidelity_bounds(response: Dict[str, Any], kind: str) -> None:
  fidelity = response.get("fidelity_estimate")
  if not isinstance(fidelity, (float, int)):
    raise AssertionError(f"{kind}: fidelity_estimate must be numeric, got {type(fidelity).__name__}")
  if not (math.isfinite(float(fidelity)) and 0.0 <= float(fidelity) <= 1.0):
    raise AssertionError(f"{kind}: fidelity_estimate out of bounds: {fidelity}")


def _assert_bool_field(response: Dict[str, Any], field: str, kind: str) -> None:
  value = response.get(field)
  if not isinstance(value, bool):
    raise AssertionError(f"{kind}: expected boolean response field '{field}', got {type(value).__name__}")


def _assert_message_contains(response: Dict[str, Any], expected_substring: str, kind: str) -> None:
  message = str(response.get("message", ""))
  if expected_substring not in message:
    raise AssertionError(f"{kind}: expected message to contain '{expected_substring}', got '{message}'")


def _assert_qutip_status(response: Dict[str, Any], expected_status: str, kind: str) -> None:
  status = response.get("qutip_status")
  if status != expected_status:
    raise AssertionError(f"{kind}: expected qutip_status='{expected_status}', got '{status}'")


def _assert_error_category(response: Dict[str, Any], expected_category: str, kind: str) -> None:
  category = response.get("error_category")
  if category is None:
    message = str(response.get("message", ""))
    marker = "[category="
    if marker in message:
      start = message.index(marker) + len(marker)
      end = message.find("]", start)
      if end != -1:
        category = message[start:end]
  if category != expected_category:
    raise AssertionError(f"{kind}: expected error_category='{expected_category}', got '{category}'")


def _assert_meta_field(response: Dict[str, Any], key: str, expected: Any, kind: str) -> None:
  meta = response.get("meta")
  if not isinstance(meta, dict):
    raise AssertionError(f"{kind}: expected response meta, got {type(meta).__name__}")
  if meta.get(key) != expected:
    raise AssertionError(f"{kind}: expected meta['{key}']={expected!r}, got {meta.get(key)!r}")


def _assert_meta_numeric_field(response: Dict[str, Any], key: str, lower: float, upper: float, kind: str) -> None:
  meta = response.get("meta")
  if not isinstance(meta, dict):
    raise AssertionError(f"{kind}: expected response meta, got {type(meta).__name__}")
  value = meta.get(key)
  if not isinstance(value, (int, float)):
    raise AssertionError(f"{kind}: expected numeric meta['{key}'], got {type(value).__name__}")
  if not (lower <= float(value) <= upper):
    raise AssertionError(f"{kind}: expected meta['{key}'] in [{lower}, {upper}], got {value}")


def _assert_meta_contains(response: Dict[str, Any], key: str, fragment: str, kind: str) -> None:
  meta = response.get("meta")
  if not isinstance(meta, dict):
    raise AssertionError(f"{kind}: expected response meta, got {type(meta).__name__}")
  value = meta.get(key)
  if not isinstance(value, str):
    raise AssertionError(f"{kind}: expected meta['{key}'] to be str, got {type(value).__name__}")
  if fragment not in value:
    raise AssertionError(f"{kind}: expected meta['{key}'] to contain '{fragment}', got {value!r}")


def _assert_response(success_expected: bool, operation: str, response: Dict[str, Any]) -> None:
  if response.get("success") != success_expected:
    raise AssertionError(f"{operation}: success expected {success_expected}, got {response.get('success')}\nmessage={response.get('message', '')}")
  if response.get("message") == "":
    raise AssertionError(f"{operation}: message must be present")
  _assert_fidelity_bounds(response, operation)


def main() -> int:
  parser = argparse.ArgumentParser()
  parser.add_argument("--seed", type=int, default=12345, help="seed value for randomized worker branches")
  args = parser.parse_args()

  if not _qutip_available():
    print("qutip not available. install dependencies and rerun.")
    return 2

  cases = [
      ("unitary:X", {"kind": "unitary", "payload": {"kind": "unitary", "gate": "X"}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}], "params": []}, True, ["status:implemented"]),
      ("unitary:x lower", {"kind": "unitary", "payload": {"kind": "unitary", "gate": "x"}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}], "params": []}, True, ["status:implemented"]),
      ("unitary:CNOT", {"kind": "unitary", "payload": {"kind": "unitary", "gate": "CNOT"}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}, {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1}]}, True, ["status:implemented"]),
      ("unitary:qutrit H", {"kind": "unitary", "payload": {"kind": "unitary", "gate": "H"}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}], "backend_config": {"qutip_node_profile": "standard_qutrit", "qutip_worker_timeout_ms": 5000, "qutip_backend_class": "qutip_density_matrix"}}, True, ["status:implemented"]),
      ("unitary:missing gate", {"kind": "unitary", "payload": {"kind": "unitary"}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, False, ["message:qutip worker unsupported unitary", "category:unsupported_gate"]),
      ("unitary:bad gate", {"kind": "unitary", "payload": {"kind": "unitary", "gate": "ZZ"}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, False, ["message:qutip worker unsupported unitary", "category:unsupported_gate"]),
      ("measurement:Z", {"kind": "measurement", "basis": "Z", "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:simulated", "measured_plus"]),
      ("measurement:alias measure", {"kind": "measure", "basis": "Z", "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["measured_plus"]),
      ("measurement:BELL", {"kind": "measurement", "basis": "BELL", "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["measured_plus"]),
      ("measurement:invalid basis", {"kind": "measurement", "basis": "W", "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, False, ["message:unsupported measurement basis", "category:unsupported_measurement"]),
      ("noise:dephasing", {"kind": "noise", "payload": {"kind": "noise", "noise_kind": "dephasing", "p": 0.05}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:implemented"]),
      ("noise:dephase alias", {"kind": "noise", "payload": {"kind": "noise", "noise_kind": "dephase", "p": 0.02}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:implemented"]),
      ("noise:decoherence alias", {"kind": "noise", "payload": {"kind": "noise", "noise_kind": "decoherence", "p": 0.02}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:implemented"]),
      ("noise:loss", {"kind": "noise", "payload": {"kind": "noise", "noise_kind": "loss", "p": 0.01}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:implemented"]),
      ("noise:loss payload scalar", {"kind": "noise", "payload": {"kind": "noise", "noise_kind": "loss", "p": 0.07}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:implemented"]),
      ("noise:reset", {"kind": "noise", "payload": {"kind": "noise", "noise_kind": "reset"}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:implemented"]),
      ("noise:amplitude_damping", {"kind": "noise", "payload": {"kind": "noise", "noise_kind": "amplitude_damping", "p": 0.06}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:implemented"]),
      ("noise:thermal_relaxation", {"kind": "noise", "payload": {"kind": "noise", "noise_kind": "thermal_relaxation", "p": 0.07}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:implemented"]),
      ("noise:bitflip", {"kind": "noise", "payload": {"kind": "noise", "noise_kind": "bitflip", "p": 0.08}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:implemented"]),
      ("noise:phaseflip", {"kind": "noise", "payload": {"kind": "noise", "noise_kind": "phaseflip", "p": 0.09}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:implemented"]),
      ("noise:depolarizing", {"kind": "noise", "payload": {"kind": "noise", "noise_kind": "depolarizing", "p": 0.05}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:implemented"]),
      ("noise:unknown", {"kind": "noise", "payload": {"kind": "noise", "noise_kind": "not_a_noise"}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, False, ["message:unsupported noise kind", "category:unsupported_noise"]),
      ("advanced:kerr", {"kind": "kerr", "params": [0.2], "duration": 0.5, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:implemented"]),
      ("advanced:kerr alias", {"kind": "kerr_effect", "params": [0.2], "duration": 0.5, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:kerr effect alias", {"kind": "kerreffect", "params": [0.2], "duration": 0.5, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:cross-kerr alias", {"kind": "cross_kerr_effect", "params": [0.2], "duration": 0.5, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}, {"node_id": 1, "qnic_index": 1, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:cross_kerr", {"kind": "cross_kerr", "params": [0.4], "duration": 0.3, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}, {"node_id": 1, "qnic_index": 1, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:cross-kerr", {"kind": "cross-kerr", "params": [0.4], "duration": 0.3, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}, {"node_id": 1, "qnic_index": 1, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:beam_splitter", {"kind": "beam_splitter", "params": [0.25], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}, {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1}]}, True, []),
      ("advanced:beamsplitter", {"kind": "beamsplitter", "params": [0.25], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}, {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1}]}, True, []),
      ("advanced:beam splitter", {"kind": "beam splitter", "params": [0.25], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}, {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1}]}, True, []),
      ("advanced:beam-splitter", {"kind": "beam-splitter", "params": [0.25], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}, {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1}]}, True, []),
      ("advanced:mode_coupling", {"kind": "mode_coupling", "params": [0.15], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}], "ancillary_modes": [0, 1]}, True, []),
      ("advanced:loss_mode", {"kind": "loss_mode", "payload": {"coupling": 0.08}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}], "ancillary_modes": [0]}, True, []),
      ("advanced:photon_number_cutoff", {"kind": "photon_number_cutoff", "params": [4], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}], "ancillary_modes": [0]}, True, []),
      ("advanced:two_mode_squeezing", {"kind": "two_mode_squeezing", "params": [0.19], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}, {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1}]}, True, []),
      ("advanced:fock_loss", {"kind": "fock_loss", "params": [0.11], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:polarization_rotation", {"kind": "polarization_rotation", "params": [0.14], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:implemented"]),
      ("advanced:polarization_decoherence", {"kind": "polarization_decoherence", "params": [0.04], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:implemented"]),
      ("advanced:phase_shift", {"kind": "phase_shift", "params": [0.5], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:implemented"]),
      ("advanced:phase-shift", {"kind": "phase-shift", "params": [0.5], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:implemented"]),
      ("advanced:phaseshift", {"kind": "phaseshift", "params": [0.5], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:implemented"]),
      ("advanced:phaseshifter", {"kind": "phaseshifter", "params": [0.5], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:implemented"]),
      ("advanced:phase_modulation", {"kind": "phase_modulation", "params": [0.13], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:implemented"]),
      ("advanced:phase_modulator", {"kind": "phase_modulator", "params": [0.13], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:implemented"]),
      ("advanced:self_phase_modulator", {"kind": "self_phase_modulator", "params": [0.13], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:implemented"]),
      ("advanced:cross_phase_modulator", {"kind": "cross_phase_modulator", "params": [0.13], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:implemented"]),
      ("advanced:nonlinear", {"kind": "nonlinear", "params": [0.13], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:implemented"]),
      ("advanced:decoherence", {"kind": "decoherence", "params": [0.03], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:implemented"]),
      ("advanced:dephasing", {"kind": "dephasing", "params": [0.03], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:implemented"]),
      ("advanced:detection", {"kind": "detection", "payload": {"p": 0.01}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:implemented", "measured_plus"]),
      ("advanced:dark_count alias", {"kind": "detection", "payload": {"dark_count": 0.01}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:implemented", "measured_plus"]),
      ("advanced:detector alias", {"kind": "detection", "payload": {"detector": 0.01}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:implemented", "measured_plus"]),
      ("advanced:loss", {"kind": "loss", "params": [0.02], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:implemented"]),
      ("advanced:attenuation", {"kind": "attenuation", "params": [0.02], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:implemented"]),
      ("advanced:delay", {"kind": "delay", "duration": 0.2, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:implemented"]),
      ("advanced:hamiltonian", {"kind": "hamiltonian", "payload": {"expr": "sx"}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:implemented"]),
      ("advanced:lindblad", {"kind": "lindblad", "payload": {"expr": "sigmax"}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:implemented"]),
      ("advanced:hamiltonian invalid", {"kind": "hamiltonian", "payload": {"expr": ""}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, False, ["message:qutip worker requires expr"]),
      ("advanced:lindblad invalid", {"kind": "lindblad", "payload": {"expr": ""}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, False, ["message:qutip worker requires expr"]),
      ("advanced:heralded_entanglement", {"kind": "heralded_entanglement", "params": [0.8], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["measured_plus"]),
      ("advanced:heralded-entanglement alias", {"kind": "heralded-entanglement", "params": [0.8], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["measured_plus"]),
      ("advanced:dispersion", {"kind": "dispersion", "payload": {"strength": 0.05}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:channel_dispersion", {"kind": "channel_dispersion", "payload": {"strength": 0.04}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:fiber_dispersion", {"kind": "fiber_dispersion", "payload": {"strength": 0.04}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:fibre_dispersion", {"kind": "fibre_dispersion", "payload": {"strength": 0.04}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:multiphoton", {"kind": "multiphoton", "payload": {"strength": 0.02}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:hom", {"kind": "hom", "duration": 0.3, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}, {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1}]}, True, ["status:implemented"]),
      ("advanced:hom_interference", {"kind": "hom_interference", "duration": 0.3, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}, {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1}], "payload": {"visibility": 0.92}}, True, ["status:implemented"]),
      ("advanced:two_photon_interference", {"kind": "two_photon_interference", "duration": 0.3, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}, {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1}]}, True, ["status:implemented"]),
      ("advanced:hominterference alias", {"kind": "hominterference", "duration": 0.3, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}, {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1}]}, True, ["status:implemented"]),
      ("advanced:bs_interference", {"kind": "bs_interference", "duration": 0.3, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}, {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1}]}, True, ["status:implemented"]),
      ("advanced:bsinterference alias", {"kind": "bsinterference", "duration": 0.3, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}, {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1}]}, True, ["status:implemented"]),
      ("advanced:twophoton_interference alias", {"kind": "twophoton_interference", "duration": 0.3, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}, {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1}]}, True, ["status:implemented"]),
      ("advanced:reset", {"kind": "reset", "duration": 0.2, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:implemented"]),
      ("advanced:source_multiphoton", {"kind": "source_multiphoton", "payload": {"strength": 0.04}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:multiphoton_source", {"kind": "multiphoton_source", "payload": {"strength": 0.04}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:multi_photon_source alias", {"kind": "multi_photon_source", "payload": {"strength": 0.04}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:squeezing", {"kind": "squeezing", "payload": {"strength": 0.02}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:timing_jitter", {"kind": "timing_jitter", "params": [0.12], "duration": 0.4, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:implemented"]),
      ("advanced:jitter alias", {"kind": "jitter", "params": [0.12], "duration": 0.4, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:implemented"]),
      ("advanced:time_jitter alias", {"kind": "time_jitter", "params": [0.12], "duration": 0.4, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:implemented"]),
      ("advanced:time-jitter alias", {"kind": "time-jitter", "params": [0.12], "duration": 0.4, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:implemented"]),
      ("advanced:timing-jitter alias", {"kind": "timing-jitter", "params": [0.12], "duration": 0.4, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:implemented"]),
      ("backend class:state vector", {"kind": "kerr", "params": [0.2], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}], "backend_config": {"qutip_backend_class": "qutip_state_vector", "python_executable": "python3", "qutip_worker_timeout_ms": 5000}}, True, []),
      ("backend class:invalid", {"kind": "kerr", "params": [0.2], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}], "backend_config": {"qutip_backend_class": "not_a_backend", "python_executable": "python3", "qutip_worker_timeout_ms": 5000}}, False, ["message:unsupported backend class", "category:unsupported_backend_class"]),
      ("limit:qubit count exceeded", {"kind": "kerr", "params": [0.2], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}, {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1}], "backend_config": {"qutip_backend_class": "qutip_density_matrix", "qutip_max_register_qubits": 1, "qutip_worker_timeout_ms": 5000}}, False, ["message:qutip backend config limit exceeded", "category:exceeded_limit"]),
      ("limit:ancillary mode exceeded", {"kind": "kerr", "params": [0.2], "ancillary_modes": [0, 1, 2], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}], "backend_config": {"qutip_backend_class": "qutip_density_matrix", "qutip_max_hilbert_dim": 2, "qutip_worker_timeout_ms": 5000}}, False, ["message:ancillary_modes", "category:exceeded_limit"]),
      ("invalid:qutip_max_register_qubits payload", {"kind": "kerr", "params": [0.2], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}], "backend_config": {"qutip_backend_class": "qutip_density_matrix", "qutip_max_register_qubits": "bad", "qutip_worker_timeout_ms": 5000}}, False, ["message:invalid_payload", "category:invalid_payload"]),
      ("invalid:qutip_max_hilbert_dim payload", {"kind": "kerr", "params": [0.2], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}], "backend_config": {"qutip_backend_class": "qutip_density_matrix", "qutip_max_hilbert_dim": "bad", "qutip_worker_timeout_ms": 5000}}, False, ["message:invalid_payload", "category:invalid_payload"]),
      ("unsupported:unknown", {"kind": "not_a_kind", "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, False, ["status:unsupported", "category:unsupported_kind"]),
      ("kind:no-op", {"kind": "no-op", "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
  ]

  status_counts = {"implemented": 0, "simulated": 0, "unsupported": 0, "unknown": 0}
  passed = 0

  for name, operation, expected, asserts in cases:
    try:
      response = _call_worker(operation, seed=args.seed)
      _assert_response(expected, name, response)
      for expected_field in asserts:
        if expected_field.startswith("message:"):
          _assert_message_contains(response, expected_field[len("message:"):], name)
        elif expected_field.startswith("status:"):
          _assert_qutip_status(response, expected_field[len("status:"):], name)
        elif expected_field.startswith("category:"):
          _assert_error_category(response, expected_field[len("category:"):], name)
        else:
          _assert_bool_field(response, expected_field, name)

      qutip_status = response.get("qutip_status")
      if qutip_status in {"implemented", "simulated", "unsupported"}:
        status_counts[qutip_status] += 1
      else:
        status_counts["unknown"] += 1

      print(f"PASS {name}: {response.get('message')}")
      passed += 1
    except Exception as exc:
      print(f"FAIL {name}: {exc}")
      return 1

  print(f"qutip worker smoke checks: {passed}/{len(cases)} passed")
  total_status_ops = sum(status_counts.values())
  if total_status_ops > 0:
    implemented_ratio = status_counts["implemented"] / total_status_ops * 100.0
    simulated_ratio = status_counts["simulated"] / total_status_ops * 100.0
    unsupported_ratio = status_counts["unsupported"] / total_status_ops * 100.0
    print(
        "qutip status counts: "
        + f"implemented={status_counts['implemented']} ({implemented_ratio:.1f}%), "
        + f"simulated={status_counts['simulated']} ({simulated_ratio:.1f}%), "
        + f"unsupported={status_counts['unsupported']} ({unsupported_ratio:.1f}%), "
        + f"unknown={status_counts['unknown']}"
    )

    if status_counts["unsupported"] >= total_status_ops and any("strict" in name for name, *_ in cases):
      print("qutip status: all operations were unsupported; check script case coverage")

  profile_default_operation = {
    "kind": "unitary",
    "payload": {"kind": "unitary", "gate": "X"},
    "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
  }
  profile_default_response = _call_worker(profile_default_operation, seed=args.seed)
  _assert_response(True, "profile:default", profile_default_response)
  _assert_meta_field(profile_default_response, "profile", "standard_light", "profile:default")
  _assert_meta_field(profile_default_response, "mode", "node", "profile:default")
  _assert_meta_field(profile_default_response, "dim", 2, "profile:default")
  _assert_meta_field(profile_default_response, "node_dim", 2, "profile:default")

  profile_qutrit_measurement_operation = {
    "kind": "measurement",
    "basis": "Z",
    "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
    "backend_config": {
      "qutip_node_profile": "standard_qutrit",
      "qutip_worker_timeout_ms": 5000,
      "qutip_backend_class": "qutip_density_matrix",
    },
  }
  profile_qutrit_measurement_response = _call_worker(profile_qutrit_measurement_operation, seed=args.seed)
  _assert_response(True, "profile:qutrit measurement", profile_qutrit_measurement_response)
  _assert_meta_field(profile_qutrit_measurement_response, "profile", "standard_qutrit", "profile:qutrit measurement")
  _assert_meta_field(profile_qutrit_measurement_response, "dim", 3, "profile:qutrit measurement")
  _assert_meta_numeric_field(profile_qutrit_measurement_response, "measurement_plus_probability", 0.0, 1.0, "profile:qutrit measurement")
  _assert_bool_field(profile_qutrit_measurement_response, "measured_plus", "profile:qutrit measurement")

  profile_link_operation = {
    "kind": "hom_interference",
    "duration": 0.3,
    "targets": [
      {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0},
      {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1},
    ],
    "backend_config": {
      "qutip_link_profile": "standard_qutrit",
      "qutip_node_profile": "standard_light",
      "qutip_worker_timeout_ms": 5000,
      "qutip_backend_class": "qutip_density_matrix",
    },
  }
  profile_link_response = _call_worker(profile_link_operation, seed=args.seed)
  _assert_response(True, "profile:link qutrit", profile_link_response)
  _assert_meta_field(profile_link_response, "profile", "standard_qutrit", "profile:link qutrit")
  _assert_meta_field(profile_link_response, "mode", "link", "profile:link qutrit")
  _assert_meta_field(profile_link_response, "dim", 4, "profile:link qutrit")

  profile_link_mode_coupling_operation = {
    "kind": "mode_coupling",
    "params": [0.2],
    "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
    "duration": 0.1,
    "backend_config": {
      "qutip_node_profile": "standard_light",
      "qutip_link_profile": "standard_qutrit",
      "qutip_worker_timeout_ms": 5000,
      "qutip_backend_class": "qutip_density_matrix",
    },
  }
  profile_link_mode_coupling_response = _call_worker(profile_link_mode_coupling_operation, seed=args.seed)
  _assert_response(True, "profile:mode_coupling link qutrit", profile_link_mode_coupling_response)
  _assert_meta_field(profile_link_mode_coupling_response, "profile", "standard_qutrit", "profile:mode_coupling link qutrit")
  _assert_meta_field(profile_link_mode_coupling_response, "mode", "link", "profile:mode_coupling link qutrit")
  _assert_meta_field(profile_link_mode_coupling_response, "dim", 4, "profile:mode_coupling link qutrit")

  profile_link_alias_operation = {
    "kind": "hom",
    "duration": 0.2,
    "targets": [
      {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0},
      {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1},
    ],
    "backend_config": {
      "qutip_node_profile": "standard_light",
      "qutip_link_profile": "standard_qutrit",
      "qutip_worker_timeout_ms": 5000,
      "qutip_backend_class": "qutip_density_matrix",
    },
  }
  profile_link_alias_response = _call_worker(profile_link_alias_operation, seed=args.seed)
  _assert_response(True, "profile:link alias", profile_link_alias_response)
  _assert_meta_field(profile_link_alias_response, "profile", "standard_qutrit", "profile:link alias")
  _assert_meta_field(profile_link_alias_response, "mode", "link", "profile:link alias")
  _assert_meta_field(profile_link_alias_response, "dim", 4, "profile:link alias")

  profile_link_loss_operation = {
    "kind": "loss",
    "params": [0.05],
    "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
    "duration": 0.2,
    "backend_config": {
      "qutip_node_profile": "standard_light",
      "qutip_link_profile": "standard_qutrit",
      "qutip_worker_timeout_ms": 5000,
      "qutip_backend_class": "qutip_density_matrix",
    },
  }
  profile_link_loss_response = _call_worker(profile_link_loss_operation, seed=args.seed)
  _assert_response(True, "profile:loss link qutrit", profile_link_loss_response)
  _assert_meta_field(profile_link_loss_response, "profile", "standard_qutrit", "profile:loss link qutrit")
  _assert_meta_field(profile_link_loss_response, "mode", "link", "profile:loss link qutrit")
  _assert_meta_field(profile_link_loss_response, "dim", 4, "profile:loss link qutrit")

  profile_custom_operation = {
    "kind": "unitary",
    "payload": {"kind": "unitary", "gate": "H"},
    "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
    "backend_config": {
      "qutip_node_profile": "custom",
      "qutip_profile_overrides": '{"node_dim":4, "link_mode_dim":5, "truncation": 7}',
      "qutip_worker_timeout_ms": 5000,
      "qutip_backend_class": "qutip_density_matrix",
    },
  }
  profile_custom_response = _call_worker(profile_custom_operation, seed=args.seed)
  _assert_response(True, "profile:custom", profile_custom_response)
  _assert_meta_field(profile_custom_response, "profile", "custom", "profile:custom")
  _assert_meta_field(profile_custom_response, "dim", 4, "profile:custom")

  profile_node_reset_operation = {
    "kind": "noise",
    "payload": {"kind": "noise", "noise_kind": "reset"},
    "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
    "backend_config": {
      "qutip_node_profile": "standard_qutrit",
      "qutip_link_profile": "standard_light",
      "qutip_worker_timeout_ms": 5000,
      "qutip_backend_class": "qutip_density_matrix",
    },
  }
  profile_node_reset_response = _call_worker(profile_node_reset_operation, seed=args.seed)
  _assert_response(True, "profile:node qutrit reset", profile_node_reset_response)
  _assert_meta_field(profile_node_reset_response, "profile", "standard_qutrit", "profile:node qutrit reset")
  _assert_meta_field(profile_node_reset_response, "mode", "node", "profile:node qutrit reset")
  _assert_meta_field(profile_node_reset_response, "dim", 3, "profile:node qutrit reset")

  profile_normalized_name_operation = {
    "kind": "unitary",
    "payload": {"kind": "unitary", "gate": "X"},
    "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
    "backend_config": {
      "qutip_node_profile": "Standard Qutrit",
      "qutip_worker_timeout_ms": 5000,
      "qutip_backend_class": "qutip_density_matrix",
    },
  }
  profile_normalized_name_response = _call_worker(profile_normalized_name_operation, seed=args.seed)
  _assert_response(True, "profile:normalized preset name", profile_normalized_name_response)
  _assert_meta_field(profile_normalized_name_response, "profile", "standard_qutrit", "profile:normalized preset name")
  _assert_meta_field(profile_normalized_name_response, "requested_profile", "standard_qutrit", "profile:normalized preset name")
  _assert_meta_field(profile_normalized_name_response, "dim", 3, "profile:normalized preset name")

  profile_none_node_name_operation = {
    "kind": "unitary",
    "payload": {"kind": "unitary", "gate": "X"},
    "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
    "backend_config": {
      "qutip_node_profile": None,
      "qutip_worker_timeout_ms": 5000,
      "qutip_backend_class": "qutip_density_matrix",
    },
  }
  profile_none_node_name_response = _call_worker(profile_none_node_name_operation, seed=args.seed)
  _assert_response(True, "profile:node profile is null", profile_none_node_name_response)
  _assert_meta_field(profile_none_node_name_response, "profile", "standard_light", "profile:node profile is null")
  _assert_meta_field(profile_none_node_name_response, "mode", "node", "profile:node profile is null")
  _assert_meta_field(profile_none_node_name_response, "dim", 2, "profile:node profile is null")

  profile_node_link_split_case = {
    "kind": "hom_interference",
    "duration": 0.2,
    "targets": [
      {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0},
      {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1},
    ],
    "backend_config": {
      "qutip_node_profile": "standard_qutrit",
      "qutip_link_profile": "standard_light",
      "qutip_worker_timeout_ms": 5000,
      "qutip_backend_class": "qutip_density_matrix",
    },
  }
  profile_node_link_split_response = _call_worker(profile_node_link_split_case, seed=args.seed)
  _assert_response(True, "profile:link respects link profile", profile_node_link_split_response)
  _assert_meta_field(profile_node_link_split_response, "profile", "standard_light", "profile:link respects link profile")
  _assert_meta_field(profile_node_link_split_response, "requested_profile", "standard_light", "profile:link respects link profile")
  _assert_meta_field(profile_node_link_split_response, "mode", "link", "profile:link respects link profile")
  _assert_meta_field(profile_node_link_split_response, "dim", 2, "profile:link respects link profile")

  profile_custom_dict_operation = {
    "kind": "unitary",
    "payload": {"kind": "unitary", "gate": "X"},
    "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
    "backend_config": {
      "qutip_node_profile": "custom",
      "qutip_profile_overrides": {"node_dim": 4, "link_mode_dim": 5, "truncation": 7},
      "qutip_worker_timeout_ms": 5000,
      "qutip_backend_class": "qutip_density_matrix",
    },
  }
  profile_custom_dict_response = _call_worker(profile_custom_dict_operation, seed=args.seed)
  _assert_response(True, "profile:custom dict overrides", profile_custom_dict_response)
  _assert_meta_field(profile_custom_dict_response, "profile", "custom", "profile:custom dict overrides")
  _assert_meta_field(profile_custom_dict_response, "node_dim", 4, "profile:custom dict overrides")
  _assert_meta_field(profile_custom_dict_response, "dim", 4, "profile:custom dict overrides")

  profile_custom_invalid_type_operation = {
    "kind": "measurement",
    "basis": "Z",
    "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
    "backend_config": {
      "qutip_node_profile": "custom",
      "qutip_profile_overrides": 123,
      "qutip_worker_timeout_ms": 5000,
      "qutip_backend_class": "qutip_density_matrix",
    },
  }
  profile_custom_invalid_type_response = _call_worker(profile_custom_invalid_type_operation, seed=args.seed)
  _assert_response(True, "profile:custom invalid override type", profile_custom_invalid_type_response)
  _assert_error_category(profile_custom_invalid_type_response, "invalid_profile", "profile:custom invalid override type")
  _assert_meta_field(profile_custom_invalid_type_response, "profile", "custom", "profile:custom invalid override type")
  _assert_meta_field(profile_custom_invalid_type_response, "dim", 2, "profile:custom invalid override type")
  _assert_meta_contains(profile_custom_invalid_type_response, "errors", "qutip_profile_overrides must be a JSON string/object", "profile:custom invalid override type")

  profile_custom_below_min_operation = {
    "kind": "unitary",
    "payload": {"kind": "unitary", "gate": "Y"},
    "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
    "backend_config": {
      "qutip_node_profile": "custom",
      "qutip_profile_overrides": {"node_dim": 1, "link_mode_dim": 0, "truncation": 1},
      "qutip_worker_timeout_ms": 5000,
      "qutip_backend_class": "qutip_density_matrix",
    },
  }
  profile_custom_below_min_response = _call_worker(profile_custom_below_min_operation, seed=args.seed)
  _assert_response(True, "profile:custom below minimum", profile_custom_below_min_response)
  _assert_error_category(profile_custom_below_min_response, "invalid_profile", "profile:custom below minimum")
  _assert_meta_field(profile_custom_below_min_response, "profile", "custom", "profile:custom below minimum")
  _assert_meta_field(profile_custom_below_min_response, "node_dim", 2, "profile:custom below minimum")
  _assert_meta_field(profile_custom_below_min_response, "dim", 2, "profile:custom below minimum")
  _assert_meta_contains(profile_custom_below_min_response, "errors", "profile value below minimum", "profile:custom below minimum")

  profile_node_link_invalid_profile_operation = {
    "kind": "heralded_entanglement",
    "params": [0.9],
    "targets": [
      {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0},
      {"node_id": 1, "qnic_index": 1, "qnic_type": 0, "qubit_index": 0},
    ],
    "backend_config": {
      "qutip_node_profile": "standard_light",
      "qutip_link_profile": "not_a_profile",
      "qutip_worker_timeout_ms": 5000,
      "qutip_backend_class": "qutip_density_matrix",
    },
  }
  profile_node_link_invalid_profile_response = _call_worker(profile_node_link_invalid_profile_operation, seed=args.seed)
  _assert_response(True, "profile:invalid link profile fallback", profile_node_link_invalid_profile_response)
  _assert_error_category(profile_node_link_invalid_profile_response, "invalid_profile", "profile:invalid link profile fallback")
  _assert_meta_field(profile_node_link_invalid_profile_response, "profile", "standard_light", "profile:invalid link profile fallback")
  _assert_meta_field(profile_node_link_invalid_profile_response, "requested_profile", "not_a_profile", "profile:invalid link profile fallback")
  _assert_meta_field(profile_node_link_invalid_profile_response, "mode", "link", "profile:invalid link profile fallback")
  _assert_meta_field(profile_node_link_invalid_profile_response, "dim", 2, "profile:invalid link profile fallback")

  profile_node_op_invalid_node_with_valid_link_operation = {
    "kind": "unitary",
    "payload": {"kind": "unitary", "gate": "X"},
    "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
    "backend_config": {
      "qutip_node_profile": "not_existing_node",
      "qutip_link_profile": "standard_qutrit",
      "qutip_worker_timeout_ms": 5000,
      "qutip_backend_class": "qutip_density_matrix",
    },
  }
  profile_node_op_invalid_node_with_valid_link_response = _call_worker(profile_node_op_invalid_node_with_valid_link_operation, seed=args.seed)
  _assert_response(True, "profile:invalid node fallback for node op", profile_node_op_invalid_node_with_valid_link_response)
  _assert_error_category(profile_node_op_invalid_node_with_valid_link_response, "invalid_profile", "profile:invalid node fallback for node op")
  _assert_meta_field(profile_node_op_invalid_node_with_valid_link_response, "profile", "standard_light", "profile:invalid node fallback for node op")
  _assert_meta_field(profile_node_op_invalid_node_with_valid_link_response, "requested_profile", "not_existing_node", "profile:invalid node fallback for node op")
  _assert_meta_field(profile_node_op_invalid_node_with_valid_link_response, "mode", "node", "profile:invalid node fallback for node op")
  _assert_meta_field(profile_node_op_invalid_node_with_valid_link_response, "dim", 2, "profile:invalid node fallback for node op")

  profile_custom_empty_overrides_operation = {
    "kind": "unitary",
    "payload": {"kind": "unitary", "gate": "X"},
    "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
    "backend_config": {
      "qutip_node_profile": "custom",
      "qutip_profile_overrides": "   ",
      "qutip_worker_timeout_ms": 5000,
      "qutip_backend_class": "qutip_density_matrix",
    },
  }
  profile_custom_empty_overrides_response = _call_worker(profile_custom_empty_overrides_operation, seed=args.seed)
  _assert_response(True, "profile:custom empty overrides", profile_custom_empty_overrides_response)
  _assert_meta_field(profile_custom_empty_overrides_response, "profile", "custom", "profile:custom empty overrides")
  _assert_meta_field(profile_custom_empty_overrides_response, "dim", 2, "profile:custom empty overrides")
  _assert_meta_field(profile_custom_empty_overrides_response, "node_dim", 2, "profile:custom empty overrides")

  profile_custom_false_leakage_operation = {
    "kind": "noise",
    "payload": {"kind": "noise", "noise_kind": "dephasing", "p": 0.05},
    "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
    "backend_config": {
      "qutip_node_profile": "custom",
      "qutip_profile_overrides": {"leakage_enabled": False},
      "qutip_worker_timeout_ms": 5000,
      "qutip_backend_class": "qutip_density_matrix",
    },
  }
  profile_custom_false_leakage_response = _call_worker(profile_custom_false_leakage_operation, seed=args.seed)
  _assert_response(True, "profile:custom leakage false", profile_custom_false_leakage_response)
  _assert_meta_field(profile_custom_false_leakage_response, "profile", "custom", "profile:custom leakage false")
  _assert_meta_field(profile_custom_false_leakage_response, "leakage_enabled", False, "profile:custom leakage false")

  profile_custom_true_leakage_operation = {
    "kind": "noise",
    "payload": {"kind": "noise", "noise_kind": "dephasing", "p": 0.05},
    "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
    "backend_config": {
      "qutip_node_profile": "custom",
      "qutip_profile_overrides": {"leakage_enabled": "true"},
      "qutip_worker_timeout_ms": 5000,
      "qutip_backend_class": "qutip_density_matrix",
    },
  }
  profile_custom_true_leakage_response = _call_worker(profile_custom_true_leakage_operation, seed=args.seed)
  _assert_response(True, "profile:custom leakage true", profile_custom_true_leakage_response)
  _assert_meta_field(profile_custom_true_leakage_response, "profile", "custom", "profile:custom leakage true")
  _assert_meta_field(profile_custom_true_leakage_response, "leakage_enabled", True, "profile:custom leakage true")

  profile_custom_truncation_str_operation = {
    "kind": "unitary",
    "payload": {"kind": "unitary", "gate": "Y"},
    "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
    "backend_config": {
      "qutip_node_profile": "custom",
      "qutip_profile_overrides": {"truncation": "9"},
      "qutip_worker_timeout_ms": 5000,
      "qutip_backend_class": "qutip_density_matrix",
    },
  }
  profile_custom_truncation_str_response = _call_worker(profile_custom_truncation_str_operation, seed=args.seed)
  _assert_response(True, "profile:custom truncation string", profile_custom_truncation_str_response)
  _assert_meta_field(profile_custom_truncation_str_response, "profile", "custom", "profile:custom truncation string")
  _assert_meta_field(profile_custom_truncation_str_response, "truncation", 9, "profile:custom truncation string")

  profile_custom_overrides_array_operation = {
    "kind": "unitary",
    "payload": {"kind": "unitary", "gate": "Y"},
    "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
    "backend_config": {
      "qutip_node_profile": "custom",
      "qutip_profile_overrides": "[1, 2, 3]",
      "qutip_worker_timeout_ms": 5000,
      "qutip_backend_class": "qutip_density_matrix",
    },
  }
  profile_custom_overrides_array_response = _call_worker(profile_custom_overrides_array_operation, seed=args.seed)
  _assert_response(True, "profile:custom overrides array", profile_custom_overrides_array_response)
  _assert_error_category(profile_custom_overrides_array_response, "invalid_profile", "profile:custom overrides array")
  _assert_meta_field(profile_custom_overrides_array_response, "profile", "custom", "profile:custom overrides array")
  _assert_meta_contains(profile_custom_overrides_array_response, "errors", "must be a JSON object", "profile:custom overrides array")

  profile_custom_invalid_boolean_operation = {
    "kind": "measurement",
    "basis": "Z",
    "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
    "backend_config": {
      "qutip_node_profile": "custom",
      "qutip_profile_overrides": '{"leakage_enabled": "not-bool", "node_dim": 4}',
      "qutip_worker_timeout_ms": 5000,
      "qutip_backend_class": "qutip_density_matrix",
    },
  }
  profile_custom_invalid_boolean_response = _call_worker(profile_custom_invalid_boolean_operation, seed=args.seed)
  _assert_response(True, "profile:custom invalid leakage bool", profile_custom_invalid_boolean_response)
  _assert_error_category(profile_custom_invalid_boolean_response, "invalid_profile", "profile:custom invalid leakage bool")
  _assert_meta_field(profile_custom_invalid_boolean_response, "node_dim", 4, "profile:custom invalid leakage bool")
  _assert_meta_contains(profile_custom_invalid_boolean_response, "errors", "invalid boolean value", "profile:custom invalid leakage bool")

  profile_normalized_link_name_operation = {
    "kind": "heralded_entanglement",
    "params": [0.8],
    "targets": [
      {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0},
      {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1},
    ],
    "backend_config": {
      "qutip_link_profile": "  HIGH-FIDELITY  ",
      "qutip_worker_timeout_ms": 5000,
      "qutip_backend_class": "qutip_density_matrix",
    },
  }
  profile_normalized_link_name_response = _call_worker(profile_normalized_link_name_operation, seed=args.seed)
  _assert_response(True, "profile:normalized link name", profile_normalized_link_name_response)
  _assert_meta_field(profile_normalized_link_name_response, "profile", "high_fidelity", "profile:normalized link name")
  _assert_meta_field(profile_normalized_link_name_response, "requested_profile", "high_fidelity", "profile:normalized link name")
  _assert_meta_field(profile_normalized_link_name_response, "dim", 6, "profile:normalized link name")

  profile_custom_partial_overrides_operation = {
    "kind": "unitary",
    "payload": {"kind": "unitary", "gate": "X"},
    "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
    "backend_config": {
      "qutip_node_profile": "custom",
      "qutip_profile_overrides": {"node_dim": "4"},
      "qutip_worker_timeout_ms": 5000,
      "qutip_backend_class": "qutip_density_matrix",
    },
  }
  profile_custom_partial_overrides_response = _call_worker(profile_custom_partial_overrides_operation, seed=args.seed)
  _assert_response(True, "profile:custom partial override", profile_custom_partial_overrides_response)
  _assert_meta_field(profile_custom_partial_overrides_response, "profile", "custom", "profile:custom partial override")
  _assert_meta_field(profile_custom_partial_overrides_response, "node_dim", 4, "profile:custom partial override")
  _assert_meta_field(profile_custom_partial_overrides_response, "link_dim", 2, "profile:custom partial override")
  _assert_meta_field(profile_custom_partial_overrides_response, "dim", 4, "profile:custom partial override")

  profile_custom_unknown_override_operation = {
    "kind": "unitary",
    "payload": {"kind": "unitary", "gate": "Y"},
    "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
    "backend_config": {
      "qutip_node_profile": "custom",
      "qutip_profile_overrides": {"node_dim": 4, "bogus_option": 123, "another_one": "keep"},
      "qutip_worker_timeout_ms": 5000,
      "qutip_backend_class": "qutip_density_matrix",
    },
  }
  profile_custom_unknown_override_response = _call_worker(profile_custom_unknown_override_operation, seed=args.seed)
  _assert_response(True, "profile:custom unknown override key", profile_custom_unknown_override_response)
  _assert_meta_field(profile_custom_unknown_override_response, "profile", "custom", "profile:custom unknown override key")
  _assert_meta_field(profile_custom_unknown_override_response, "errors", None, "profile:custom unknown override key")
  _assert_meta_field(profile_custom_unknown_override_response, "node_dim", 4, "profile:custom unknown override key")

  profile_custom_link_partial_overrides_operation = {
    "kind": "hom_interference",
    "duration": 0.2,
    "targets": [
      {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0},
      {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1},
    ],
    "backend_config": {
      "qutip_link_profile": "custom",
      "qutip_profile_overrides": {"link_mode_dim": "7"},
      "qutip_worker_timeout_ms": 5000,
      "qutip_backend_class": "qutip_density_matrix",
    },
  }
  profile_custom_link_partial_overrides_response = _call_worker(profile_custom_link_partial_overrides_operation, seed=args.seed)
  _assert_response(True, "profile:custom link partial override", profile_custom_link_partial_overrides_response)
  _assert_meta_field(profile_custom_link_partial_overrides_response, "profile", "custom", "profile:custom link partial override")
  _assert_meta_field(profile_custom_link_partial_overrides_response, "mode", "link", "profile:custom link partial override")
  _assert_meta_field(profile_custom_link_partial_overrides_response, "link_dim", 7, "profile:custom link partial override")
  _assert_meta_field(profile_custom_link_partial_overrides_response, "dim", 7, "profile:custom link partial override")

  profile_high_fidelity_node_operation = {
    "kind": "unitary",
    "payload": {"kind": "unitary", "gate": "H"},
    "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
    "backend_config": {
      "qutip_node_profile": "high_fidelity",
      "qutip_worker_timeout_ms": 5000,
      "qutip_backend_class": "qutip_density_matrix",
    },
  }
  profile_high_fidelity_node_response = _call_worker(profile_high_fidelity_node_operation, seed=args.seed)
  _assert_response(True, "profile:high fidelity node", profile_high_fidelity_node_response)
  _assert_meta_field(profile_high_fidelity_node_response, "profile", "high_fidelity", "profile:high fidelity node")
  _assert_meta_field(profile_high_fidelity_node_response, "mode", "node", "profile:high fidelity node")
  _assert_meta_field(profile_high_fidelity_node_response, "dim", 5, "profile:high fidelity node")

  profile_high_fidelity_link_operation = {
    "kind": "hom_interference",
    "duration": 0.2,
    "targets": [
      {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0},
      {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1},
    ],
    "backend_config": {
      "qutip_link_profile": "high_fidelity",
      "qutip_worker_timeout_ms": 5000,
      "qutip_backend_class": "qutip_density_matrix",
    },
  }
  profile_high_fidelity_link_response = _call_worker(profile_high_fidelity_link_operation, seed=args.seed)
  _assert_response(True, "profile:high fidelity link", profile_high_fidelity_link_response)
  _assert_meta_field(profile_high_fidelity_link_response, "profile", "high_fidelity", "profile:high fidelity link")
  _assert_meta_field(profile_high_fidelity_link_response, "mode", "link", "profile:high fidelity link")
  _assert_meta_field(profile_high_fidelity_link_response, "dim", 6, "profile:high fidelity link")

  profile_qutrit_measurement_x_operation = {
    "kind": "measurement",
    "basis": "X",
    "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
    "backend_config": {
      "qutip_node_profile": "standard_qutrit",
      "qutip_worker_timeout_ms": 5000,
      "qutip_backend_class": "qutip_density_matrix",
    },
  }
  profile_qutrit_measurement_x_response = _call_worker(profile_qutrit_measurement_x_operation, seed=args.seed)
  _assert_response(True, "profile:qutrit measurement X", profile_qutrit_measurement_x_response)
  _assert_meta_field(profile_qutrit_measurement_x_response, "profile", "standard_qutrit", "profile:qutrit measurement X")
  _assert_meta_numeric_field(profile_qutrit_measurement_x_response, "measurement_plus_probability", 0.5, 0.5, "profile:qutrit measurement X")
  _assert_meta_numeric_field(profile_qutrit_measurement_x_response, "measurement_minus_probability", 0.5, 0.5, "profile:qutrit measurement X")

  profile_bad_name_node_operation = {
    "kind": "unitary",
    "payload": {"kind": "unitary", "gate": "X"},
    "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
    "backend_config": {
      "qutip_node_profile": "definitely_not_a_profile",
      "qutip_worker_timeout_ms": 5000,
      "qutip_backend_class": "qutip_density_matrix",
    },
  }
  profile_bad_name_node_response = _call_worker(profile_bad_name_node_operation, seed=args.seed)
  _assert_response(True, "profile:invalid profile fallback", profile_bad_name_node_response)
  _assert_error_category(profile_bad_name_node_response, "invalid_profile", "profile:invalid profile fallback")
  _assert_meta_field(profile_bad_name_node_response, "profile", "standard_light", "profile:invalid profile fallback")
  _assert_meta_field(profile_bad_name_node_response, "requested_profile", "definitely_not_a_profile", "profile:invalid profile fallback")
  _assert_meta_field(profile_bad_name_node_response, "node_dim", 2, "profile:invalid profile fallback")

  profile_invalid_operation = {
    "kind": "unitary",
    "payload": {"kind": "unitary", "gate": "Y"},
    "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
    "backend_config": {
      "qutip_node_profile": "standard_light",
      "qutip_profile_overrides": "{broken-json",
      "qutip_worker_timeout_ms": 5000,
      "qutip_backend_class": "qutip_density_matrix",
    },
  }
  profile_invalid_response = _call_worker(profile_invalid_operation, seed=args.seed)
  _assert_response(True, "profile:invalid override", profile_invalid_response)
  _assert_error_category(profile_invalid_response, "invalid_profile", "profile:invalid override")
  _assert_meta_field(profile_invalid_response, "profile", "standard_light", "profile:invalid override")

  strict_reject_operation = {
    "kind": "mode_coupling",
    "params": [0.4],
    "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}],
    "duration": 0.3,
    "backend_config": {
      "qutip_strict_simulated": True,
      "qutip_backend_class": "qutip_density_matrix",
      "python_executable": "python3",
      "qutip_worker_timeout_ms": 5000,
    },
  }
  strict_allow_operation = dict(strict_reject_operation)
  strict_allow_operation["backend_config"] = dict(strict_reject_operation["backend_config"])
  strict_allow_operation["backend_config"]["qutip_strict_simulated"] = False

  strict_reject_response = _call_worker(strict_reject_operation, seed=args.seed)
  _assert_response(False, "strict:simulated reject", strict_reject_response)
  _assert_qutip_status(strict_reject_response, "simulated", "strict:simulated reject")
  _assert_error_category(strict_reject_response, "simulated_operation_rejected", "strict:simulated reject")
  _assert_message_contains(
      strict_reject_response,
      "qutip strict mode rejected simulated kind",
      "strict:simulated reject",
  )

  strict_allow_response = _call_worker(strict_allow_operation, seed=args.seed)
  _assert_response(True, "strict:simulated allow", strict_allow_response)
  _assert_qutip_status(strict_allow_response, "simulated", "strict:simulated allow")

  return 0


if __name__ == "__main__":
  raise SystemExit(main())
