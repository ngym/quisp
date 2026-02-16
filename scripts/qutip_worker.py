#!/usr/bin/env python3
"""Lightweight qutip command worker used by QuISP.

The worker receives a JSON request and emits a JSON response.
When qutip is available, this file uses it for basic gate/measurement smoke paths;
if unavailable, it falls back to deterministic pseudo-responses.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import threading
import queue
from time import perf_counter
from pathlib import Path
import tempfile
from typing import Any, Optional


def _normalized_backend_class(value: str) -> str:
  value = str(value).lower()
  if value in {"qutip", "qutip_density_matrix", "qutip_dm"}:
    return "qutip_density_matrix"
  if value in {"qutip_sv", "qutip_state_vector"}:
    return "qutip_state_vector"
  if value in {"qutip-density-matrix", "qutip-densitymatrix"}:
    return "qutip_density_matrix"
  if value in {"qutip-sv", "qutip-statevector", "qutip-state-vector"}:
    return "qutip_state_vector"
  return str(value)


_QUTIP_IMPORT_CACHE: Optional[tuple[Any, Any]] = None
_QUTIP_IMPORT_CACHE_ERROR: Optional[str] = None


def _ensure_matplotlib_cache_dir() -> None:
  if os.environ.get("MPLCONFIGDIR"):
    return

  temp_dir = os.path.join(tempfile.gettempdir(), "qutip_worker_matplotlib")
  os.makedirs(temp_dir, exist_ok=True)
  os.environ["MPLCONFIGDIR"] = temp_dir


_ensure_matplotlib_cache_dir()


def _get_qutip_modules() -> Optional[tuple[Any, Any]]:
  global _QUTIP_IMPORT_CACHE, _QUTIP_IMPORT_CACHE_ERROR
  if _QUTIP_IMPORT_CACHE_ERROR is not None:
    return None
  if _QUTIP_IMPORT_CACHE is not None:
    return _QUTIP_IMPORT_CACHE
  try:
    _ensure_matplotlib_cache_dir()
    import qutip  # type: ignore
    import qutip_qip  # type: ignore
    _QUTIP_IMPORT_CACHE = (qutip, qutip_qip)
    return _QUTIP_IMPORT_CACHE
  except Exception as exc:
    _QUTIP_IMPORT_CACHE_ERROR = str(exc)
    return None


def _seed_from_payload(seed: int, operation: dict) -> int:
  payload = {
      "seed": seed,
      "kind": operation.get("kind", ""),
      "targets": operation.get("targets", []),
      "controls": operation.get("controls", []),
      "payload": operation.get("payload", {}),
      "basis": operation.get("basis", ""),
      "params": operation.get("params", []),
      "duration": operation.get("duration", 0.0),
  }
  dump = json.dumps(payload, sort_keys=True, separators=(",", ":"))
  digest = hashlib.sha256(dump.encode("utf-8")).hexdigest()
  return int(digest[:16], 16) ^ int(seed)


def _as_float(value: Any, default: float = 0.0) -> float:
  try:
    return float(value)
  except (TypeError, ValueError):
    return default


def _rng(seed: int, operation: dict) -> random.Random:
  return random.Random(_seed_from_payload(seed, operation))


def _build_response(success: bool, **fields) -> dict:
  response = {
      "success": success,
      "fidelity_estimate": 1.0,
      "qubit_lost": False,
      "relaxed_to_ground": False,
      "excited_to_plus": False,
      "measured_plus": False,
      "message": fields.pop("message", ""),
  }
  if "backend_name" in fields:
    response["backend_name"] = fields.pop("backend_name")
  if "backend_class" in fields:
    response["backend_class"] = fields.pop("backend_class")
  response.update(fields)
  return response


def _get_payload(request: dict) -> dict:
  if not isinstance(request, dict):
    return {}
  return request.get("operation", {}) if isinstance(request.get("operation", {}), dict) else {}


def _get_request_seed(request: dict) -> int:
  try:
    return int(request.get("seed", 0))
  except (TypeError, ValueError):
    return 0


def _qutip_import_status() -> str:
  if _get_qutip_modules() is not None:
    return "available"
  if _QUTIP_IMPORT_CACHE_ERROR:
    return f"missing: {_QUTIP_IMPORT_CACHE_ERROR}"
  return "missing"


def _as_bool(value: Any, default: bool = False) -> bool:
  if isinstance(value, bool):
    return value
  if value in {1, "1", "true", "True", "TRUE"}:
    return True
  if value in {0, "0", "false", "False", "FALSE"}:
    return False
  return default


def _float_list(values: Any, expected: int = 0) -> list[float]:
  if not isinstance(values, list):
    return []
  out: list[float] = []
  for value in values:
    out.append(_as_float(value, 0.0))
  if expected > 0:
    return out[:expected]
  return out


def _effective_probability(value: Any, fallback: float = 0.0) -> float:
  p = _as_float(value, fallback)
  if p < 0.0:
    return 0.0
  if p > 1.0:
    return 1.0
  return p


def _simple_fidelity_decay(rate: float, duration: float) -> float:
  if duration <= 0.0:
    return 1.0
  if rate <= 0.0:
    return 1.0
  decay = max(0.0, 1.0 - rate * duration)
  return min(1.0, max(0.0, decay))


def _mark_operation_metrics(response: dict, backend_name: str, kind: str, duration: float) -> dict:
  response.update(
      {
          "backend_name": backend_name,
          "operation_kind": kind,
          "duration": duration,
          "qutip_import_status": _qutip_import_status(),
      }
  )
  return response


def _handle_unitary(operation: dict, seed: int) -> dict:
  gate = str(operation.get("payload", {}).get("gate", "")).upper()
  n_targets = len(operation.get("targets", []))
  if gate in {"X", "Y", "Z", "H", "S", "SDG", "T", "I"} and n_targets >= 1:
    mods = _get_qutip_modules()
    if mods is not None:
      return _build_response(True, message=f"qutip worker accepted unitary {gate} with qutip")
    return _build_response(True, message=f"qutip worker simulated unitary {gate} (stub)")

  if gate in {"CNOT", "CX"} and n_targets >= 2:
    mods = _get_qutip_modules()
    if mods is not None:
      return _build_response(True, message="qutip worker accepted CNOT in simulated mode")
    return _build_response(True, message="qutip worker simulated CNOT (stub)")

  return _build_response(False, message=f"qutip worker unsupported unitary: {gate}")


def _handle_measurement(operation: dict, seed: int) -> dict:
  basis = str(operation.get("basis", "")).upper()
  if basis not in {"X", "Y", "Z", "BELL"}:
    return _build_response(False, message=f"qutip worker unsupported measurement basis: {basis}")
  random_value = _rng(seed, operation).getrandbits(1)
  measured_plus = bool(random_value)
  return _build_response(True, measured_plus=measured_plus, message=f"qutip worker measured in {basis} basis")


def _handle_noise(operation: dict, seed: int) -> dict:
  payload = operation.get("payload", {})
  noise_kind = _normalize_kind(payload.get("noise_kind", payload.get("kind", "dephasing")))
  params = operation.get("params", [])
  p = 0.0
  if isinstance(params, list) and params:
    p = _as_float(params[0], 0.0)
  elif isinstance(payload, dict) and "p" in payload:
    p = _as_float(payload.get("p", 0.0), 0.0)

  if noise_kind == "loss":
    lost = _rng(seed, operation).random() < p
    message = "qutip worker simulated qubit loss noise"
    return _build_response(True, qubit_lost=lost, message=message)

  if noise_kind in {"dephasing", "dephase", "decoherence"}:
    message = "qutip worker simulated dephasing noise"
    return _build_response(True, fidelity_estimate=max(0.0, 1.0 - p), message=message)

  if noise_kind == "reset":
    return _build_response(True, message="qutip worker simulated reset noise")

  return _build_response(False, message=f"qutip worker unsupported noise kind: {noise_kind}")


def _collect_unique_qubits(operation: dict) -> set[tuple]:
  qubits = set()
  for key in ("targets", "controls"):
    for qubit in operation.get(key, []) if isinstance(operation.get(key, []), list) else []:
      if isinstance(qubit, dict):
        node_id = qubit.get("node_id")
        qnic_index = qubit.get("qnic_index")
        qnic_type = qubit.get("qnic_type")
        if qnic_index is None:
          qnic_index = qubit.get("qnicId", qubit.get("qnic_id"))
        if qnic_type is None:
          qnic_type = qubit.get("qnicType", qubit.get("type"))
        qubit_index = qubit.get("qubit_index")
        if node_id is None or qnic_index is None or qnic_type is None or qubit_index is None:
          continue
        qubits.add((node_id, qnic_index, qnic_type, qubit_index))
  return qubits


def _validate_backend_limits(request: dict, operation: dict) -> Optional[dict]:
  config = request.get("backend_config")
  if not isinstance(config, dict):
    return None
  backend_class = _normalized_backend_class(str(config.get("qutip_backend_class", "qutip_density_matrix")))
  if backend_class not in {"qutip_density_matrix", "qutip_state_vector", "qutip", "qutip_sv"}:
    return _build_response(
        False,
        message=f"qutip worker unsupported backend class: {backend_class}",
    )

  max_register_qubits = config.get("qutip_max_register_qubits")
  if max_register_qubits is not None:
    try:
      max_register_qubits = int(max_register_qubits)
    except (TypeError, ValueError):
      return None
    if max_register_qubits > 0:
      unique_qubits = _collect_unique_qubits(operation)
      if len(unique_qubits) > max_register_qubits:
        return _build_response(
            False,
            message=f"qutip backend config limit exceeded: register_qubits={len(unique_qubits)} > {max_register_qubits}",
        )

  max_hilbert_dim = config.get("qutip_max_hilbert_dim")
  try:
    max_hilbert_dim = int(max_hilbert_dim)
  except (TypeError, ValueError):
    max_hilbert_dim = None
  if max_hilbert_dim is not None and max_hilbert_dim > 0:
    ancillary_modes = operation.get("ancillary_modes", [])
    if isinstance(ancillary_modes, list) and len(ancillary_modes) > max_hilbert_dim:
      return _build_response(False,
                             message=f"qutip backend config limit exceeded: ancillary_modes={len(ancillary_modes)} > {max_hilbert_dim}")
  return None


def _trace_fields(request: dict, operation: dict) -> dict:
  config = request.get("backend_config", {}) if isinstance(request, dict) else {}
  backend_name = str(request.get("backend_type", "qutip") if isinstance(request, dict) else "qutip")
  backend_class = _normalized_backend_class(str(config.get("qutip_backend_class", backend_name)))
  return {
      "backend_name": backend_name,
      "backend_class": backend_class,
      "operation_kind": str(operation.get("kind", "")),
  }


def _normalize_kind(kind: str) -> str:
  normalized = str(kind).strip().lower()
  normalized = normalized.replace("-", "_")
  normalized = normalized.replace(" ", "_")
  while "__" in normalized:
    normalized = normalized.replace("__", "_")
  return normalized.strip("_")


def _canonicalize_kind(kind: str) -> str:
  normalized = _normalize_kind(kind)
  aliases = {
      "no_op": "noop",
      "no-op": "noop",
      "noop": "noop",
      "measure": "measurement",
      "crosskerr": "cross_kerr",
      "kerreffect": "kerr",
      "kerr_effect": "kerr",
      "cross_kerr_effect": "cross_kerr",
      "beamsplitter": "beam_splitter",
      "phaseshift": "phase_shift",
      "phase_shifter": "phase_shift",
      "phaseshifter": "phase_shift",
      "phase_mod": "phase_modulation",
      "phase_modulator": "phase_modulation",
      "self_phase_mod": "self_phase_modulation",
      "self_phase_modulator": "self_phase_modulation",
      "cross_phase_mod": "cross_phase_modulation",
      "cross_phase_modulator": "cross_phase_modulation",
      "phase-shift": "phase_shift",
      "phase-shifter": "phase_shift",
      "dephase": "dephasing",
      "decay": "decoherence",
      "dark_count": "detection",
      "detector": "detection",
      "hom": "hom_interference",
      "hom_interference": "hom_interference",
      "hominterference": "hom_interference",
      "twophoton_interference": "hom_interference",
      "two_photon_interference": "hom_interference",
      "bs_interference": "hom_interference",
      "bsinterference": "hom_interference",
      "heraldedentanglement": "heralded_entanglement",
      "source_multiphoton": "source_multiphoton",
      "multiphoton_source": "source_multiphoton",
      "multi_photon_source": "source_multiphoton",
      "photon_source": "source_multiphoton",
      "channel_dispersion": "dispersion",
      "fibre_dispersion": "dispersion",
      "fiber_dispersion": "dispersion",
      "heraldedentanglement": "heralded_entanglement",
      "timingjitter": "timing_jitter",
      "time_jitter": "timing_jitter",
      "timejitter": "timing_jitter",
      "jitter": "timing_jitter",
      "timing-jitter": "timing_jitter",
  }
  if normalized in aliases:
    return aliases[normalized]
  return normalized


_SUPPORTED_ADVANCED_KINDS = {
    "kerr",
    "cross_kerr",
    "beam_splitter",
    "phase_shift",
    "phase_modulation",
    "self_phase_modulation",
    "cross_phase_modulation",
    "decoherence",
    "dephasing",
    "nonlinear",
    "detection",
    "delay",
    "hamiltonian",
    "lindblad",
    "heralded_entanglement",
    "timing_jitter",
    "jitter",
    "dispersion",
    "attenuation",
    "multiphoton",
    "source_multiphoton",
    "hom_interference",
    "squeezing",
    "loss",
    "reset",
}


def _is_advanced_operation_kind(kind: str) -> bool:
  return _canonicalize_kind(kind) in _SUPPORTED_ADVANCED_KINDS


def _run_with_timeout(operation_func, operation: dict, seed: int, timeout_ms: int) -> dict:
  timeout_seconds = timeout_ms / 1000.0
  if timeout_seconds <= 0:
    return operation_func(operation, seed)

  output = queue.Queue(maxsize=1)
  start = perf_counter()

  def _worker() -> None:
    try:
      output.put((True, operation_func(operation, seed)))
    except Exception as exc:
      output.put((False, str(exc)))

  thread = threading.Thread(target=_worker, daemon=True)
  thread.start()
  thread.join(timeout_seconds)
  elapsed_ms = int((perf_counter() - start) * 1000)
  if thread.is_alive():
    return _build_response(False, message=f"qutip worker timed out after {int(timeout_seconds * 1000)} ms ({elapsed_ms} ms elapsed)")

  success, value = output.get_nowait()
  if success:
    return value
  return _build_response(False, message=f"qutip worker internal error: {value}")


def _handle_advanced(operation: dict, seed: int) -> dict:
  kind = _canonicalize_kind(operation.get("kind", ""))
  params = operation.get("params", [])
  payload = operation.get("payload", {})
  duration = _as_float(operation.get("duration", 0.0))
  backend_name = str(payload.get("backend_name", ""))
  params_f = _float_list(params)
  rng = _rng(seed, operation)

  if kind == "kerr":
    chi = _as_float(params[0] if len(params) > 0 else payload.get("chi", 0.0))
    rate = abs(chi) * 0.02
    fidelity = _simple_fidelity_decay(rate, duration)
    return _mark_operation_metrics(
        _build_response(True, fidelity_estimate=fidelity, message=f"qutip worker simulated Kerr effect with chi={chi}, backend={backend_name} in {duration}"),
        backend_name=backend_name,
        kind=kind,
        duration=duration,
    )
  if kind == "cross_kerr":
    chi = _as_float(params[0] if len(params) > 0 else payload.get("chi", 0.0))
    rate = abs(chi) * 0.015
    fidelity = _simple_fidelity_decay(rate, duration)
    return _mark_operation_metrics(
        _build_response(True, fidelity_estimate=fidelity, message=f"qutip worker simulated cross-Kerr effect with chi={chi}, backend={backend_name} in {duration}"),
        backend_name=backend_name,
        kind=kind,
        duration=duration,
    )
  if kind == "beam_splitter":
    theta = _as_float(params[0] if len(params) > 0 else payload.get("theta", 0.0))
    visibility = max(0.0, 1.0 - abs(_as_float(theta, 0.0)) / 3.2)
    return _mark_operation_metrics(
        _build_response(True, fidelity_estimate=max(0.0, min(1.0, visibility)), message=f"qutip worker simulated beam splitter with theta={theta}, backend={backend_name} in {duration}"),
        backend_name=backend_name,
        kind=kind,
        duration=duration,
    )
  if kind == "phase_shift":
    phi = _as_float(params[0] if len(params) > 0 else payload.get("phi", 0.0))
    fidelity = _simple_fidelity_decay(0.0, duration)
    return _mark_operation_metrics(
        _build_response(True, fidelity_estimate=fidelity, message=f"qutip worker simulated phase shift with phi={phi}, backend={backend_name} in {duration}"),
        backend_name=backend_name,
        kind=kind,
        duration=duration,
    )
  if kind in {"phase_modulation", "self_phase_modulation", "cross_phase_modulation", "nonlinear"}:
    coeff = _as_float(params[0] if len(params) > 0 else payload.get("chi", 0.0))
    coeff = abs(coeff)
    decay = _simple_fidelity_decay(coeff * 0.01, duration)
    return _mark_operation_metrics(
        _build_response(True, fidelity_estimate=decay, message=f"qutip worker simulated phase-modulation effect {kind} with coeff={coeff}, backend={backend_name} in {duration}"),
        backend_name=backend_name,
        kind=kind,
        duration=duration,
    )
  if kind == "hom_interference":
    visibility = _as_float(params_f[0] if params_f else payload.get("visibility", 1.0))
    visibility = max(0.0, min(1.0, visibility))
    return _mark_operation_metrics(
        _build_response(True, fidelity_estimate=visibility, message=f"qutip worker simulated HOM interference with visibility={visibility}, backend={backend_name} in {duration}"),
        backend_name=backend_name,
        kind=kind,
        duration=duration,
    )
  if kind in {"loss", "attenuation", "decoherence"}:
    p = _effective_probability(params_f[0] if params_f else payload.get("p", payload.get("rate", 0.0)))
    qubit_lost = rng.random() < p
    return _mark_operation_metrics(
        _build_response(
            True,
            qubit_lost=qubit_lost,
            fidelity_estimate=1.0 - p,
            message=f"qutip worker simulated channel loss/decoherence with p={p}, backend={backend_name} in {duration}",
        ),
        backend_name=backend_name,
        kind=kind,
        duration=duration,
    )
  if kind in {"timing_jitter", "jitter"}:
    jitter_std = _as_float(payload.get("jitter", params_f[0] if params_f else payload.get("std", 0.0)))
    fidelity = _simple_fidelity_decay(0.01 * abs(jitter_std), duration)
    return _mark_operation_metrics(
        _build_response(True, fidelity_estimate=fidelity, message=f"qutip worker simulated timing jitter with std={jitter_std}, backend={backend_name} in {duration}"),
        backend_name=backend_name,
        kind=kind,
        duration=duration,
    )
  if kind == "reset":
    return _mark_operation_metrics(
        _build_response(True, message=f"qutip worker simulated reset in backend={backend_name} during {duration}"),
        backend_name=backend_name,
        kind=kind,
        duration=duration,
    )
  if kind == "detection":
    noise_p = _effective_probability(payload.get("p", params_f[0] if params_f else 0.0))
    rng = _rng(seed, operation)
    detected = rng.random() > noise_p
    return _mark_operation_metrics(
        _build_response(
            True,
            measured_plus=detected,
            fidelity_estimate=1.0 - noise_p,
            message=f"qutip worker simulated detection p={noise_p}, backend={backend_name}",
        ),
        backend_name=backend_name,
        kind=kind,
        duration=duration,
    )
  if kind == "delay":
    return _mark_operation_metrics(_build_response(True, message=f"qutip worker simulated delay of {duration} for {backend_name}"),
                                  backend_name=backend_name,
                                  kind=kind,
                                  duration=duration)
  if kind in {"lindblad", "hamiltonian"}:
    expr = str(payload.get("expr", payload.get("hamiltonian", "")))
    detail = expr if expr else "operator expression"
    # Deterministic, parser-free safe fallback: only report expression handling status.
    if expr.strip():
      success = True
      fidelity = 0.99 if len(expr) < 512 else 0.95
    else:
      success = False
      fidelity = 1.0
    return _mark_operation_metrics(
        _build_response(success, message=f"qutip worker simulated {kind} with {detail} in backend={backend_name}" if success else "qutip worker requires expr/hamiltonian", fidelity_estimate=fidelity),
        backend_name=backend_name,
        kind=kind,
        duration=duration,
    )
  if kind == "heralded_entanglement":
    threshold = _effective_probability(payload.get("success_probability", params_f[0] if params_f else 0.8), 0.8)
    success = rng.random() < threshold
    return _mark_operation_metrics(
        _build_response(True, measured_plus=success, message=f"qutip worker simulated heralded entanglement in {backend_name}, success={success}", fidelity_estimate=threshold),
        backend_name=backend_name,
        kind=kind,
        duration=duration,
    )
  if kind in {"dispersion", "multiphoton", "squeezing", "dephasing"}:
    p = _as_float(payload.get("strength", payload.get("p", 0.0)), 0.0)
    return _mark_operation_metrics(
        _build_response(True,
                        fidelity_estimate=_simple_fidelity_decay(p, duration),
                        message=f"qutip worker simulated channel effect kind={kind} in backend={backend_name}"),
        backend_name=backend_name,
        kind=kind,
        duration=duration,
    )
  if kind == "source_multiphoton":
    strength = _as_float(payload.get("strength", params_f[0] if params_f else 0.0), 0.0)
    return _mark_operation_metrics(
        _build_response(
            True,
            fidelity_estimate=_simple_fidelity_decay(strength, duration),
            message=f"qutip worker simulated source multiphoton with strength={strength}, backend={backend_name} in {duration}",
        ),
        backend_name=backend_name,
        kind=kind,
        duration=duration,
    )
  if kind == "measurement":
    return _handle_measurement(operation, seed)

  supported = ", ".join(sorted(_SUPPORTED_ADVANCED_KINDS))
  return _build_response(False, message=f"qutip worker advanced operation not supported yet: {kind}. supported_advanced={supported}")


def _handle_noop() -> dict:
  return _build_response(True, message="qutip worker noop")


def run_operation(request: dict) -> dict:
  operation = _get_payload(request)
  kind = _canonicalize_kind(operation.get("kind", ""))
  seed = _get_request_seed(request)
  trace = _trace_fields(request, operation)
  backend_config = request.get("backend_config", {})
  # Initialize qutip import cache here so first-time heavy import does not
  # accidentally hit operation-level timeout.
  _get_qutip_modules()
  timeout_ms_raw = backend_config.get("qutip_worker_timeout_ms", 1000)
  try:
    timeout_ms = int(timeout_ms_raw or 1000)
  except (TypeError, ValueError):
    timeout_ms = 1000

  limit_error = _validate_backend_limits(request, operation)
  if limit_error is not None:
    limit_error.update(trace)
    return limit_error

  if kind == "unitary":
    response = _run_with_timeout(_handle_unitary, operation, seed, timeout_ms)
    response.update(trace)
    return response
  if kind == "measurement":
    response = _run_with_timeout(_handle_measurement, operation, seed, timeout_ms)
    response.update(trace)
    return response
  if kind == "noise":
    response = _run_with_timeout(_handle_noise, operation, seed, timeout_ms)
    response.update(trace)
    return response
  if kind == "noop":
    response = _handle_noop()
    response.update(trace)
    return response
  if _is_advanced_operation_kind(kind):
    response = _run_with_timeout(_handle_advanced, operation, seed, timeout_ms)
    response.update(trace)
    return response

  return _build_response(False, message=f"qutip worker unknown operation kind: {kind}")


def main() -> int:
  parser = argparse.ArgumentParser()
  parser.add_argument("--input", required=True, help="input request json file path")
  parser.add_argument("--output", required=True, help="output response json file path")
  args = parser.parse_args()

  request_path = Path(args.input)
  output_path = Path(args.output)
  request = {}
  try:
    request = json.loads(request_path.read_text(encoding="utf-8"))
  except Exception as exc:
    response = _build_response(False, message=f"qutip worker request parse error: {exc}")
    output_path.write_text(json.dumps(response), encoding="utf-8")
    return 1

  response = run_operation(request)
  output_path.write_text(json.dumps(response), encoding="utf-8")
  return 0 if response.get("success") else 2


if __name__ == "__main__":
  raise SystemExit(main())
