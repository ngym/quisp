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
      ("unitary:X", {"kind": "unitary", "payload": {"kind": "unitary", "gate": "X"}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}], "params": []}, True, ["status:simulated"]),
      ("unitary:x lower", {"kind": "unitary", "payload": {"kind": "unitary", "gate": "x"}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}], "params": []}, True, ["status:simulated"]),
      ("unitary:CNOT", {"kind": "unitary", "payload": {"kind": "unitary", "gate": "CNOT"}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}, {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1}]}, True, []),
      ("unitary:missing gate", {"kind": "unitary", "payload": {"kind": "unitary"}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, False, ["message:qutip worker unsupported unitary", "category:unsupported_gate"]),
      ("unitary:bad gate", {"kind": "unitary", "payload": {"kind": "unitary", "gate": "ZZ"}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, False, ["message:qutip worker unsupported unitary", "category:unsupported_gate"]),
      ("measurement:Z", {"kind": "measurement", "basis": "Z", "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:simulated", "measured_plus"]),
      ("measurement:alias measure", {"kind": "measure", "basis": "Z", "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["measured_plus"]),
      ("measurement:BELL", {"kind": "measurement", "basis": "BELL", "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["measured_plus"]),
      ("measurement:invalid basis", {"kind": "measurement", "basis": "W", "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, False, ["message:unsupported measurement basis", "category:unsupported_measurement"]),
      ("noise:dephasing", {"kind": "noise", "payload": {"kind": "noise", "noise_kind": "dephasing", "p": 0.05}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:simulated"]),
      ("noise:dephase alias", {"kind": "noise", "payload": {"kind": "noise", "noise_kind": "dephase", "p": 0.02}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("noise:decoherence alias", {"kind": "noise", "payload": {"kind": "noise", "noise_kind": "decoherence", "p": 0.02}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("noise:loss", {"kind": "noise", "payload": {"kind": "noise", "noise_kind": "loss", "p": 0.01}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("noise:loss payload scalar", {"kind": "noise", "payload": {"kind": "noise", "noise_kind": "loss", "p": 0.07}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("noise:reset", {"kind": "noise", "payload": {"kind": "noise", "noise_kind": "reset"}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("noise:amplitude_damping", {"kind": "noise", "payload": {"kind": "noise", "noise_kind": "amplitude_damping", "p": 0.06}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("noise:thermal_relaxation", {"kind": "noise", "payload": {"kind": "noise", "noise_kind": "thermal_relaxation", "p": 0.07}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("noise:bitflip", {"kind": "noise", "payload": {"kind": "noise", "noise_kind": "bitflip", "p": 0.08}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("noise:phaseflip", {"kind": "noise", "payload": {"kind": "noise", "noise_kind": "phaseflip", "p": 0.09}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("noise:depolarizing", {"kind": "noise", "payload": {"kind": "noise", "noise_kind": "depolarizing", "p": 0.05}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
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
      ("advanced:polarization_rotation", {"kind": "polarization_rotation", "params": [0.14], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:polarization_decoherence", {"kind": "polarization_decoherence", "params": [0.04], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:phase_shift", {"kind": "phase_shift", "params": [0.5], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:simulated"]),
      ("advanced:phase-shift", {"kind": "phase-shift", "params": [0.5], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:phaseshift", {"kind": "phaseshift", "params": [0.5], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:phaseshifter", {"kind": "phaseshifter", "params": [0.5], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:phase_modulation", {"kind": "phase_modulation", "params": [0.13], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:phase_modulator", {"kind": "phase_modulator", "params": [0.13], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:self_phase_modulator", {"kind": "self_phase_modulator", "params": [0.13], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:cross_phase_modulator", {"kind": "cross_phase_modulator", "params": [0.13], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:nonlinear", {"kind": "nonlinear", "params": [0.13], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:decoherence", {"kind": "decoherence", "params": [0.03], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:dephasing", {"kind": "dephasing", "params": [0.03], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:detection", {"kind": "detection", "payload": {"p": 0.01}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["measured_plus"]),
      ("advanced:dark_count alias", {"kind": "detection", "payload": {"dark_count": 0.01}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["measured_plus"]),
      ("advanced:detector alias", {"kind": "detection", "payload": {"detector": 0.01}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["measured_plus"]),
      ("advanced:loss", {"kind": "loss", "params": [0.02], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:attenuation", {"kind": "attenuation", "params": [0.02], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:delay", {"kind": "delay", "duration": 0.2, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:hamiltonian", {"kind": "hamiltonian", "payload": {"expr": "sx"}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["status:implemented"]),
      ("advanced:lindblad", {"kind": "lindblad", "payload": {"expr": "sigmax"}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:hamiltonian invalid", {"kind": "hamiltonian", "payload": {"expr": ""}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, False, ["message:qutip worker requires expr"]),
      ("advanced:lindblad invalid", {"kind": "lindblad", "payload": {"expr": ""}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, False, ["message:qutip worker requires expr"]),
      ("advanced:heralded_entanglement", {"kind": "heralded_entanglement", "params": [0.8], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["measured_plus"]),
      ("advanced:heralded-entanglement alias", {"kind": "heralded-entanglement", "params": [0.8], "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, ["measured_plus"]),
      ("advanced:dispersion", {"kind": "dispersion", "payload": {"strength": 0.05}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:channel_dispersion", {"kind": "channel_dispersion", "payload": {"strength": 0.04}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:fiber_dispersion", {"kind": "fiber_dispersion", "payload": {"strength": 0.04}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:fibre_dispersion", {"kind": "fibre_dispersion", "payload": {"strength": 0.04}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:multiphoton", {"kind": "multiphoton", "payload": {"strength": 0.02}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:hom", {"kind": "hom", "duration": 0.3, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}, {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1}]}, True, []),
      ("advanced:hom_interference", {"kind": "hom_interference", "duration": 0.3, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}, {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1}], "payload": {"visibility": 0.92}}, True, []),
      ("advanced:two_photon_interference", {"kind": "two_photon_interference", "duration": 0.3, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}, {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1}]}, True, []),
      ("advanced:hominterference alias", {"kind": "hominterference", "duration": 0.3, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}, {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1}]}, True, []),
      ("advanced:bs_interference", {"kind": "bs_interference", "duration": 0.3, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}, {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1}]}, True, []),
      ("advanced:bsinterference alias", {"kind": "bsinterference", "duration": 0.3, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}, {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1}]}, True, []),
      ("advanced:twophoton_interference alias", {"kind": "twophoton_interference", "duration": 0.3, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}, {"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 1}]}, True, []),
      ("advanced:source_multiphoton", {"kind": "source_multiphoton", "payload": {"strength": 0.04}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:multiphoton_source", {"kind": "multiphoton_source", "payload": {"strength": 0.04}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:multi_photon_source alias", {"kind": "multi_photon_source", "payload": {"strength": 0.04}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:squeezing", {"kind": "squeezing", "payload": {"strength": 0.02}, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:timing_jitter", {"kind": "timing_jitter", "params": [0.12], "duration": 0.4, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:jitter alias", {"kind": "jitter", "params": [0.12], "duration": 0.4, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:time_jitter alias", {"kind": "time_jitter", "params": [0.12], "duration": 0.4, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:time-jitter alias", {"kind": "time-jitter", "params": [0.12], "duration": 0.4, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
      ("advanced:timing-jitter alias", {"kind": "timing-jitter", "params": [0.12], "duration": 0.4, "targets": [{"node_id": 1, "qnic_index": 0, "qnic_type": 0, "qubit_index": 0}]}, True, []),
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

  strict_reject_operation = {
    "kind": "phase_shift",
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
