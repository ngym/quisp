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
import math
import random
import re
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
_OPERATION_SEQUENCE = 0


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


def _build_response(success: bool, error_category: Optional[str] = None, qutip_status: Optional[str] = None, **fields) -> dict:
  response = {
      "success": success,
      "fidelity_estimate": 1.0,
      "qubit_lost": False,
      "relaxed_to_ground": False,
      "excited_to_plus": False,
      "measured_plus": False,
      "message": fields.pop("message", ""),
  }
  if error_category is None:
    error_category = fields.pop("error_category", None)
  if error_category:
    response["error_category"] = error_category
  if "backend_name" in fields:
    response["backend_name"] = fields.pop("backend_name")
  if "backend_class" in fields:
    response["backend_class"] = fields.pop("backend_class")
  if qutip_status in {"implemented", "simulated", "unsupported"}:
    response["qutip_status"] = qutip_status
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


def _categorize_error(category: str, message: str) -> str:
  return f"{message} [category={category}]"


def _next_operation_id(request: dict, operation: dict) -> int:
  global _OPERATION_SEQUENCE
  candidate = request.get("operation_id")
  try:
    return int(candidate)
  except (TypeError, ValueError):
    pass

  if not isinstance(operation.get("op_id"), (int, float, str)):
    _OPERATION_SEQUENCE += 1
    return _OPERATION_SEQUENCE
  try:
    return int(operation["op_id"])
  except (TypeError, ValueError):
    _OPERATION_SEQUENCE += 1
    return _OPERATION_SEQUENCE


def _as_bool(value: Any, default: bool = False) -> bool:
  if isinstance(value, bool):
    return value
  if value in {1, "1", "true", "True", "TRUE"}:
    return True
  if value in {0, "0", "false", "False", "FALSE"}:
    return False
  return default


def _strict_simulated_enabled(request: dict) -> bool:
  config = request.get("backend_config", {}) if isinstance(request, dict) else {}
  if not isinstance(config, dict):
    return False
  return _as_bool(config.get("qutip_strict_simulated", False), False)


def _apply_strict_simulated_mode(response: dict, strict: bool, kind: str) -> dict:
  if not strict:
    return response
  if response.get("qutip_status") != "simulated" or not response.get("success"):
    return response
  rejected = response.copy()
  rejected["success"] = False
  rejected["fidelity_estimate"] = rejected.get("fidelity_estimate", 1.0)
  rejected["message"] = f"qutip strict mode rejected simulated kind: {kind}"
  rejected["error_category"] = "simulated_operation_rejected"
  rejected["qutip_status"] = "simulated"
  return rejected


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


def _mark_operation_metrics(response: dict, backend_name: str, kind: str, duration: float, qutip_status: Optional[str] = None) -> dict:
  response.update(
      {
          "backend_name": backend_name,
          "operation_kind": kind,
          "duration": duration,
          "qutip_import_status": _qutip_import_status(),
      }
  )
  if qutip_status in {"implemented", "simulated", "unsupported"}:
    response["qutip_status"] = qutip_status
  return response


def _normalize_status(status: str) -> str:
  status_lower = str(status).lower()
  if status_lower in {"implemented", "simulated", "unsupported"}:
    return status_lower
  return "unsupported"


def _coerce_qutip_modules() -> Optional[tuple[Any, Any]]:
  modules = _get_qutip_modules()
  if modules is None:
    return None
  qutip, qutip_qip = modules
  if qutip is None:
    return None
  return (qutip, qutip_qip)


def _parse_single_pauli(expr: str, qutip: Any) -> Optional[Any]:
  normalized = expr.strip().lower().replace(" ", "")
  normalized = re.sub(r"[^a-z0-9_]+", "", normalized)

  pauli_map = {
      "sx": qutip.sigmax,
      "sigmax": qutip.sigmax,
      "x": qutip.sigmax,
      "sy": qutip.sigmay,
      "sigmay": qutip.sigmay,
      "y": qutip.sigmay,
      "sz": qutip.sigmaz,
      "sigmaz": qutip.sigmaz,
      "z": qutip.sigmaz,
      "sxp": qutip.sigmap,
      "sigmap": qutip.sigmap,
      "sxm": qutip.sigmam,
      "sigmam": qutip.sigmam,
      "sp": qutip.sigmap,
      "sm": qutip.sigmam,
      "i": qutip.qeye,
      "id": qutip.qeye,
      "identity": qutip.qeye,
      "eye": qutip.qeye,
  }
  if normalized in pauli_map:
    op_factory = pauli_map[normalized]
    if op_factory in (qutip.qeye,):
      return op_factory(2)
    return op_factory()
  return None


def _parse_operator_expr(expr: str, n_targets: int, qutip: Any) -> Optional[Any]:
  if n_targets <= 0:
    return None
  if expr is None:
    return None

  raw = str(expr).strip().lower()
  if not raw:
    return None

  normalized = raw.replace(" ", "")
  normalized = normalized.replace("⊗", "*")
  tokens = [token for token in normalized.split("*") if token]
  if not tokens:
    return None

  parsed = []
  for token in tokens:
    op = _parse_single_pauli(token, qutip)
    if op is None:
      return None
    parsed.append(op)

  if len(parsed) == 1 and n_targets == 1:
    return parsed[0]
  if len(parsed) == 1 and n_targets > 1:
    return None
  if len(parsed) != n_targets:
    return None

  if n_targets == 1:
    return parsed[0]
  try:
    return qutip.tensor(*parsed)
  except Exception:
    return None


def _basis_state_from_targets(qutip: Any, n_targets: int) -> Any:
  if n_targets <= 0:
    return None
  if n_targets == 1:
    return qutip.basis(2, 0)
  try:
    return qutip.tensor(*([qutip.basis(2, 0)] * n_targets))
  except Exception:
    return qutip.basis(2 ** n_targets, 0)


def _embed_qubit_operator(qutip: Any, operator: Any, n_targets: int, target_index: int) -> Any:
  if n_targets <= 0 or target_index < 0 or target_index >= n_targets:
    return None
  operators = [qutip.qeye(2) for _ in range(n_targets)]
  operators[target_index] = operator
  try:
    return qutip.tensor(*operators)
  except Exception:
    return None


def _qutip_rate_from_probability(probability: float, duration: float) -> float:
  p = _effective_probability(probability, 0.0)
  if p <= 0.0:
    return 0.0
  if p >= 1.0:
    return 1e6
  effective_duration = duration if duration > 0.0 else 1.0
  return max(0.0, -math.log(max(1e-15, 1.0 - p)) / effective_duration)


def _coerce_expr_as_list(value: Any) -> list[str]:
  if isinstance(value, list):
    return [str(v).strip() for v in value if isinstance(v, str) and str(v).strip()]
  if isinstance(value, str) and value.strip():
    return [value.strip()]
  return []


def _calculate_qutip_noise_fidelity(
    qutip: Any,
    noise_kind: str,
    operation: dict,
    duration: float,
) -> tuple[bool, float, str, dict[str, Any]]:
  payload = operation.get("payload", {})
  params = operation.get("params", [])
  params_f = _float_list(params)
  p = _effective_probability(params_f[0] if params_f else payload.get("p", 0.0))
  if duration <= 0.0:
    duration = 1.0

  targets = operation.get("targets", []) if isinstance(operation.get("targets", []), list) else []
  if len(targets) != 1:
    return (
        False,
        1.0,
        _categorize_error("invalid_payload", f"qutip worker {noise_kind} requires exactly 1 target"),
        {},
    )

  try:
    rate = _as_float(payload.get("rate"), _qutip_rate_from_probability(p, duration))
    if rate < 0.0:
      rate = 0.0
    local_ops = {
        "amplitude_damping": [math.sqrt(rate) * qutip.sigmam()],
        "thermal_relaxation": [math.sqrt(rate) * qutip.sigmam()],
        "bitflip": [math.sqrt(rate) * qutip.sigmax()],
        "phaseflip": [math.sqrt(rate) * qutip.sigmaz()],
        "depolarizing": [
            math.sqrt(rate / 3.0) * qutip.sigmax(),
            math.sqrt(rate / 3.0) * qutip.sigmay(),
            math.sqrt(rate / 3.0) * qutip.sigmaz(),
        ],
        "dephasing": [math.sqrt(rate) * qutip.sigmaz()],
        "decoherence": [math.sqrt(rate) * qutip.sigmaz()],
        "loss": [math.sqrt(rate) * qutip.sigmam()],
    }
    if noise_kind not in local_ops:
      return (
          False,
          1.0,
          _categorize_error("unsupported_noise", f"qutip worker unsupported noise kind: {noise_kind}"),
          {},
      )

    collapse_ops = []
    for local_op in local_ops[noise_kind]:
      op = _embed_qubit_operator(qutip, local_op, len(targets), 0)
      if op is not None:
        collapse_ops.append(op)
    if not collapse_ops:
      return (
          False,
          1.0,
          _categorize_error("invalid_payload", f"qutip worker cannot build collapse operators for {noise_kind}"),
          {},
      )

    if rate <= 0.0:
      return True, 1.0, f"qutip worker applied {noise_kind} with zero rate", {"effective_probability": 0.0, "rate": rate}

    state = _basis_state_from_targets(qutip, len(targets))
    base = state * state.dag()
    tlist = [0.0, duration]
    result = qutip.mesolve(qutip.qeye(base.shape[0]), base, tlist, collapse_ops, [])
    final_state = result.states[-1] if result.states else base
    fidelity = float(qutip.metrics.fidelity(base, final_state))
    return True, fidelity, f"qutip worker applied {noise_kind} with duration={duration}", {"effective_probability": p, "rate": rate}
  except Exception as exc:
    return False, 1.0, _categorize_error("solver_error", f"qutip worker {noise_kind} evolution failed: {exc}"), {}




def _calculate_qutip_loss_fidelity(
    qutip: Any,
    operation: dict,
    duration: float,
) -> tuple[bool, float, str, dict[str, Any]]:
  payload = operation.get("payload", {})
  params = operation.get("params", [])
  params_f = _float_list(params)
  p = _effective_probability(params_f[0] if params_f else payload.get("p", payload.get("rate", 0.0)))
  targets = operation.get("targets", []) if isinstance(operation.get("targets", []), list) else []
  if len(targets) != 1:
    return (
        False,
        1.0,
        _categorize_error("invalid_payload", "qutip worker loss requires exactly 1 target"),
        {},
    )

  try:
    rate = _qutip_rate_from_probability(p, max(duration, 1.0))
    decay = _embed_qubit_operator(qutip, math.sqrt(rate) * qutip.sigmam(), len(targets), 0)
    if decay is None:
      return (
          False,
          1.0,
          _categorize_error("invalid_payload", "qutip worker cannot build loss collapse operator"),
          {},
      )

    if rate <= 0.0:
      return True, 1.0, f"qutip worker applied loss with zero rate", {"effective_probability": p, "rate": rate}

    state = _basis_state_from_targets(qutip, len(targets))
    tlist = [0.0, max(duration, 1.0)]
    result = qutip.mesolve(qutip.qeye(state.shape[0]), state, tlist, [decay], [])
    final_state = result.states[-1] if result.states else state
    fidelity = float(qutip.metrics.fidelity(state, final_state))
    return True, fidelity, f"qutip worker applied loss with duration={duration}", {"effective_probability": p, "rate": rate}
  except Exception as exc:
    return (
        False,
        1.0,
        _categorize_error("solver_error", f"qutip worker loss evolution failed: {exc}"),
        {},
    )


def _calculate_qutip_phase_fidelity(qutip: Any, operation: dict, duration: float, axis: str = "z") -> tuple[bool, float, str]:
  params = operation.get("params", [])
  payload = operation.get("payload", {})
  params_f = _float_list(params)
  angle = _as_float(
      params_f[0] if params_f else payload.get("phi", payload.get("angle", payload.get("theta", 0.0))),
      0.0,
  )
  targets = operation.get("targets", []) if isinstance(operation.get("targets", []), list) else []
  n_targets = len(targets)
  if n_targets < 1:
    return False, 1.0, _categorize_error("invalid_payload", "qutip worker phase-like kind requires at least one target")

  axis_normalized = str(axis).lower()
  if axis_normalized in {"x", "sx"}:
    local_op = qutip.sigmax()
  elif axis_normalized in {"y", "sy"}:
    local_op = qutip.sigmay()
  else:
    local_op = qutip.sigmaz()

  try:
    hamiltonian = (-1j * angle / 2.0) * local_op
    embed = _embed_qubit_operator(qutip, hamiltonian, n_targets, 0)
    if embed is None:
      return False, 1.0, _categorize_error("invalid_payload", "qutip worker cannot build phase operator")
    if duration <= 0.0:
      return True, 1.0, _categorize_error("invalid_payload", "qutip worker applied zero-duration phase evolution with identity effect")

    state = _basis_state_from_targets(qutip, n_targets)
    rho0 = state * state.dag()
    U = (embed * duration).expm()
    rho_t = U * rho0 * U.dag()
    fidelity = float(qutip.metrics.fidelity(rho0, rho_t))
    return True, fidelity, f"qutip worker applied phase evolution axis={axis_normalized} with angle={angle} for duration={duration}"
  except Exception as exc:
    return False, 1.0, _categorize_error("solver_error", f"qutip worker phase evolution failed: {exc}")


def _calculate_qutip_coupled_phase_fidelity(
    qutip: Any,
    operation: dict,
    duration: float,
    mode: str,
) -> tuple[bool, float, str]:
  params = operation.get("params", [])
  payload = operation.get("payload", {})
  params_f = _float_list(params)
  coeff = _as_float(params_f[0] if params_f else payload.get("chi", payload.get("coeff", payload.get("g", 0.0))), 0.0)
  mode_normalized = str(mode).lower()
  targets = operation.get("targets", []) if isinstance(operation.get("targets", []), list) else []
  n_targets = len(targets)
  if n_targets < 1:
    return False, 1.0, _categorize_error("invalid_payload", f"qutip worker {mode_normalized} requires at least one target")

  try:
    if n_targets == 1:
      local_op = (-1j * coeff / 2.0) * qutip.sigmaz()
      hamiltonian = _embed_qubit_operator(qutip, local_op, n_targets, 0)
    elif mode_normalized in {"cross_phase_modulation", "nonlinear"} and n_targets >= 2:
      left = _embed_qubit_operator(qutip, qutip.sigmaz(), n_targets, 0)
      right = _embed_qubit_operator(qutip, qutip.sigmaz(), n_targets, 1)
      if left is None or right is None:
        return False, 1.0, _categorize_error("invalid_payload", f"qutip worker cannot build {mode_normalized} operator")
      hamiltonian = coeff * left * right
    else:
      terms = []
      for index in range(n_targets):
        op = _embed_qubit_operator(qutip, qutip.sigmaz(), n_targets, index)
        if op is not None:
          terms.append(op)
      if not terms:
        return False, 1.0, _categorize_error("invalid_payload", f"qutip worker cannot build {mode_normalized} operator")
      hamiltonian = coeff * sum(terms) / max(1, len(terms))

    if hamiltonian is None:
      return False, 1.0, _categorize_error("invalid_payload", f"qutip worker cannot build {mode_normalized} operator")
    if duration <= 0.0:
      return True, 1.0, _categorize_error("invalid_payload", f"qutip worker applied zero-duration {mode_normalized} with identity effect")

    state = _basis_state_from_targets(qutip, n_targets)
    rho0 = state * state.dag()
    U = (hamiltonian * duration).expm()
    rho_t = U * rho0 * U.dag()
    fidelity = float(qutip.metrics.fidelity(rho0, rho_t))
    return True, fidelity, f"qutip worker applied {mode_normalized} with coeff={coeff} for duration={duration}"
  except Exception as exc:
    return False, 1.0, _categorize_error("solver_error", f"qutip worker {mode_normalized} evolution failed: {exc}")


def _calculate_qutip_hamiltonian_fidelity(qutip: Any, operation: dict, duration: float) -> tuple[bool, float, str]:
  params = operation.get("params", [])
  payload = operation.get("payload", {})
  expr = str(payload.get("expr", payload.get("hamiltonian", "")))
  if payload and expr.strip():
    expression = expr
  elif params:
    expression = _as_float(params[0], 0.0).__str__()
  else:
    expression = ""

  if not expression.strip():
    return False, 1.0, _categorize_error("invalid_payload", "qutip worker requires expr/hamiltonian")

  targets = operation.get("targets", []) if isinstance(operation.get("targets", []), list) else []
  n_targets = len(targets)
  op = _parse_operator_expr(expression, n_targets, qutip)
  if op is None:
    return False, 1.0, _categorize_error("invalid_payload", f"qutip worker cannot parse hamiltonian expr: {expression}")

  try:
    if n_targets <= 0:
      return False, 1.0, _categorize_error("invalid_payload", "qutip worker requires target(s) for hamiltonian")
    if duration <= 0.0:
      return True, 1.0, "qutip worker applied zero-duration hamiltonian with identity effect"

    U = (-1j * op * duration).expm()
    state = _basis_state_from_targets(qutip, n_targets)
    rho0 = state * state.dag()
    rho_t = U * rho0 * U.dag()
    fidelity = float(qutip.metrics.fidelity(rho0, rho_t))
    return True, fidelity, f"qutip worker applied hamiltonian with expr={expression} for duration={duration}"
  except Exception as exc:
    return False, 1.0, _categorize_error("solver_error", f"qutip worker hamiltonian evolution failed: {exc}")


def _calculate_qutip_lindblad_fidelity(qutip: Any, operation: dict, duration: float) -> tuple[bool, float, str]:
  payload = operation.get("payload", {})
  targets = operation.get("targets", []) if isinstance(operation.get("targets", []), list) else []
  n_targets = len(targets)
  if n_targets <= 0:
    return False, 1.0, _categorize_error("invalid_payload", "qutip worker requires target(s) for lindblad")

  collapse_payload = payload.get("collapse", "")
  expr = str(payload.get("expr", ""))
  collapse_specs = _coerce_expr_as_list(collapse_payload)
  if not collapse_specs and expr.strip():
    collapse_specs = [expr]
  if not collapse_specs:
    return False, 1.0, _categorize_error("invalid_payload", "qutip worker requires expr/collapse for lindblad")

  collapse_ops = []
  for item in collapse_specs:
    c_op = _parse_operator_expr(item, n_targets, qutip)
    if c_op is None:
      return False, 1.0, _categorize_error("invalid_payload", f"qutip worker cannot parse lindblad collapse expr: {item}")
    collapse_ops.append(c_op)

  try:
    if duration <= 0.0:
      return True, 1.0, _categorize_error("invalid_payload", "qutip worker applied zero-duration lindblad with identity effect")
    state = _basis_state_from_targets(qutip, n_targets)
    tlist = [0.0, duration]
    result = qutip.mesolve(qutip.qeye(state.shape[0]), state, tlist, collapse_ops, [])
    final_state = result.states[-1] if result.states else state
    fidelity = float(qutip.metrics.fidelity(state, final_state))
    return True, fidelity, f"qutip worker applied lindblad with {len(collapse_ops)} collapse operator(s) for duration={duration}"
  except Exception as exc:
    return False, 1.0, _categorize_error("solver_error", f"qutip worker lindblad evolution failed: {exc}")


def _calculate_qutip_kerr_fidelity(qutip: Any, operation: dict, duration: float) -> tuple[bool, float, str]:
  params = operation.get("params", [])
  payload = operation.get("payload", {})
  chi = _as_float(params[0] if params else payload.get("chi", 0.0))
  targets = operation.get("targets", []) if isinstance(operation.get("targets", []), list) else []
  if len(targets) != 1:
    return False, 1.0, _categorize_error("invalid_payload", "qutip worker kerr requires exactly one target")

  try:
    n_op = (qutip.qeye(2) - qutip.sigmaz()) * 0.5
    local_h = chi * (n_op * n_op)
    hamiltonian = _embed_qubit_operator(qutip, local_h, 1, 0)
    if hamiltonian is None:
      return False, 1.0, _categorize_error("invalid_payload", "qutip worker cannot build kerr operator")
    if duration <= 0.0:
      return True, 1.0, _categorize_error("invalid_payload", "qutip worker applied zero-duration kerr with identity effect")
    state = _basis_state_from_targets(qutip, 1)
    rho0 = state * state.dag()
    U = (-1j * hamiltonian * duration).expm()
    rho_t = U * rho0 * U.dag()
    fidelity = float(qutip.metrics.fidelity(rho0, rho_t))
    return True, fidelity, f"qutip worker applied kerr with chi={chi} for duration={duration}"
  except Exception as exc:
    return False, 1.0, _categorize_error("solver_error", f"qutip worker kerr evolution failed: {exc}")


def _calculate_qutip_cross_kerr_fidelity(qutip: Any, operation: dict, duration: float) -> tuple[bool, float, str]:
  params = operation.get("params", [])
  payload = operation.get("payload", {})
  chi = _as_float(params[0] if params else payload.get("chi", 0.0))
  targets = operation.get("targets", []) if isinstance(operation.get("targets", []), list) else []
  if len(targets) < 2:
    return False, 1.0, _categorize_error("invalid_payload", "qutip worker cross_kerr requires at least two targets")

  n_targets = len(targets)
  try:
    n_op_left = _embed_qubit_operator(qutip, (qutip.qeye(2) - qutip.sigmaz()) * 0.5, n_targets, 0)
    n_op_right = _embed_qubit_operator(qutip, (qutip.qeye(2) - qutip.sigmaz()) * 0.5, n_targets, 1)
    if n_op_left is None or n_op_right is None:
      return False, 1.0, _categorize_error("invalid_payload", "qutip worker cannot build cross_kerr operator")
    hamiltonian = chi * n_op_left * n_op_right
    if duration <= 0.0:
      return True, 1.0, _categorize_error("invalid_payload", "qutip worker applied zero-duration cross_kerr with identity effect")
    state = _basis_state_from_targets(qutip, n_targets)
    rho0 = state * state.dag()
    U = (-1j * hamiltonian * duration).expm()
    rho_t = U * rho0 * U.dag()
    fidelity = float(qutip.metrics.fidelity(rho0, rho_t))
    return True, fidelity, f"qutip worker applied cross_kerr with chi={chi} for duration={duration}"
  except Exception as exc:
    return False, 1.0, _categorize_error("solver_error", f"qutip worker cross_kerr evolution failed: {exc}")


def _calculate_qutip_unitary_fidelity(qutip: Any, operation: dict) -> tuple[bool, float, str]:
  gate = str(operation.get("payload", {}).get("gate", "")).upper()
  params = operation.get("params", [])
  payload = operation.get("payload", {})
  params_f = _float_list(params)
  targets = operation.get("targets", []) if isinstance(operation.get("targets", []), list) else []
  n_targets = len(targets)
  if n_targets <= 0:
    return False, 1.0, _categorize_error("invalid_payload", "qutip worker unitary requires at least one target")

  angle = _as_float(
      params_f[0] if params_f else payload.get("theta", payload.get("angle", payload.get("phi", 0.0))),
      0.0,
  )

  try:
    operator: Any
    if gate in {"CX", "CNOT"} and n_targets != 2:
      return False, 1.0, _categorize_error("unsupported_gate", "qutip worker unsupported CNOT/CX target arity")
    if gate in {"X", "Y", "Z", "H", "S", "SDG", "T", "I", "SQRT_X", "SQRTX"}:
      if gate == "X":
        operator = qutip.sigmax()
      elif gate == "Y":
        operator = qutip.sigmay()
      elif gate == "Z":
        operator = qutip.sigmaz()
      elif gate == "H":
        operator = qutip.Qobj([[1, 1], [1, -1]], dims=[[2], [2]]) / math.sqrt(2)
      elif gate == "S":
        operator = qutip.Qobj([[1, 0], [0, 1j]], dims=[[2], [2]])
      elif gate == "SDG":
        operator = qutip.Qobj([[1, 0], [0, -1j]], dims=[[2], [2]])
      elif gate == "T":
        operator = qutip.Qobj([[1, 0], [0, complex(math.cos(math.pi / 4), math.sin(math.pi / 4))]], dims=[[2], [2]])
      elif gate == "I":
        operator = qutip.qeye(2)
      else:
        operator = (-(1j * math.pi / 4) * qutip.sigmax()).expm()
    elif gate in {"RX", "RY", "RZ"}:
      if gate == "RX":
        operator = (-(1j * angle / 2.0) * qutip.sigmax()).expm()
      elif gate == "RY":
        operator = (-(1j * angle / 2.0) * qutip.sigmay()).expm()
      else:
        operator = (-(1j * angle / 2.0) * qutip.sigmaz()).expm()
    elif gate in {"CX", "CNOT"}:
      control_zero = _embed_qubit_operator(qutip, (qutip.qeye(2) + qutip.sigmaz()) / 2.0, n_targets, 0)
      control_one = _embed_qubit_operator(qutip, (qutip.qeye(2) - qutip.sigmaz()) / 2.0, n_targets, 0)
      x_on_target = _embed_qubit_operator(qutip, qutip.sigmax(), n_targets, 1)
      control_identity = _embed_qubit_operator(qutip, qutip.qeye(2), n_targets, 1)
      if control_zero is None or control_one is None or x_on_target is None or control_identity is None:
        return False, 1.0, _categorize_error("invalid_payload", "qutip worker cannot build CNOT operator")
      operator = control_zero * control_identity + control_one * x_on_target
    else:
      return False, 1.0, _categorize_error("unsupported_gate", f"qutip worker unsupported unitary: {gate}")

    if n_targets == 1:
      op = _embed_qubit_operator(qutip, operator, 1, 0)
      if op is None:
        return False, 1.0, _categorize_error("invalid_payload", "qutip worker cannot embed unitary operator")
    else:
      op = operator

    state = _basis_state_from_targets(qutip, n_targets)
    rho0 = state * state.dag()
    rho_t = op * rho0 * op.dag()
    fidelity = float(qutip.metrics.fidelity(rho0, rho_t))
    return True, fidelity, f"qutip worker applied unitary {gate} with qutip evolution"
  except Exception as exc:
    return False, 1.0, _categorize_error("solver_error", f"qutip worker unitary evolution failed: {exc}")


def _extract_error_category(message: str) -> Optional[str]:
  if not isinstance(message, str):
    return None
  marker = "[category="
  begin = message.find(marker)
  if begin < 0:
    return None
  begin += len(marker)
  end = message.find("]", begin)
  if end < 0:
    return None
  return message[begin:end]


def _calculate_qutip_beam_splitter_fidelity(qutip: Any, operation: dict, duration: float) -> tuple[bool, float, str]:
  params = operation.get("params", [])
  payload = operation.get("payload", {})
  theta = _as_float(params[0] if len(params) > 0 else payload.get("theta", 0.0))
  targets = operation.get("targets", []) if isinstance(operation.get("targets", []), list) else []
  if len(targets) < 2:
    return False, 1.0, _categorize_error("invalid_payload", "qutip worker beam_splitter requires at least two targets")

  n_targets = len(targets)
  try:
    sx = _embed_qubit_operator(qutip, qutip.sigmax(), n_targets, 0)
    sx2 = _embed_qubit_operator(qutip, qutip.sigmax(), n_targets, 1)
    sy = _embed_qubit_operator(qutip, qutip.sigmay(), n_targets, 0)
    sy2 = _embed_qubit_operator(qutip, qutip.sigmay(), n_targets, 1)
    if sx is None or sx2 is None or sy is None or sy2 is None:
      return False, 1.0, _categorize_error("invalid_payload", "qutip worker cannot build beam splitter operator")
    hamiltonian = 0.5 * theta * (sx * sx2 + sy * sy2)
    if duration <= 0.0:
      return True, 1.0, _categorize_error("invalid_payload", "qutip worker applied zero-duration beam_splitter with identity effect")
    state = _basis_state_from_targets(qutip, n_targets)
    rho0 = state * state.dag()
    U = (-1j * hamiltonian * duration).expm()
    rho_t = U * rho0 * U.dag()
    fidelity = float(qutip.metrics.fidelity(rho0, rho_t))
    return True, fidelity, f"qutip worker applied beam_splitter with theta={theta} for duration={duration}"
  except Exception as exc:
    return False, 1.0, _categorize_error("solver_error", f"qutip worker beam_splitter evolution failed: {exc}")


def _handle_unitary(operation: dict, seed: int) -> dict:
  gate = str(operation.get("payload", {}).get("gate", "")).upper()
  n_targets = len(operation.get("targets", []))
  mods = _coerce_qutip_modules()
  if mods is None:
    if gate in {"X", "Y", "Z", "H", "S", "SDG", "T", "I", "RX", "RY", "RZ", "SQRT_X", "SQRTX", "CX", "CNOT"} and n_targets >= 1:
      return _build_response(True, qutip_status="simulated", message=f"qutip worker simulated unitary {gate} (qutip unavailable)")
    return _build_response(False, qutip_status="unsupported", message=_categorize_error("unsupported_gate", f"qutip worker unsupported unitary: {gate}"), error_category="unsupported_gate")

  qutip, _ = mods
  success, fidelity, message = _calculate_qutip_unitary_fidelity(qutip=qutip, operation=operation)
  qutip_status = _normalize_status("implemented" if success else "unsupported")
  error_category = _extract_error_category(message) if not success else None
  if error_category is None and not success:
    error_category = "unsupported_gate"
  return _build_response(
      success,
      qutip_status=qutip_status,
      fidelity_estimate=fidelity,
      message=message,
      error_category=error_category,
  )


def _handle_measurement(operation: dict, seed: int) -> dict:
  basis = str(operation.get("basis", "")).upper()
  if basis not in {"X", "Y", "Z", "BELL"}:
    return _build_response(False, qutip_status="unsupported", message=_categorize_error("unsupported_measurement", f"qutip worker unsupported measurement basis: {basis}"), error_category="unsupported_measurement")
  random_value = _rng(seed, operation).getrandbits(1)
  measured_plus = bool(random_value)
  return _build_response(True, qutip_status="simulated", measured_plus=measured_plus, message=f"qutip worker simulated measurement in {basis} basis")


def _handle_noise(operation: dict, seed: int) -> dict:
  payload = operation.get("payload", {})
  noise_kind = _canonicalize_kind(payload.get("noise_kind", payload.get("kind", "dephasing")))
  params = operation.get("params", [])
  params_f = _float_list(params)
  p = 0.0
  if isinstance(params, list) and params:
    p = _as_float(params[0], 0.0)
  elif isinstance(payload, dict) and "p" in payload:
    p = _as_float(payload.get("p", 0.0), 0.0)

  if noise_kind == "loss":
    lost = _rng(seed, operation).random() < p
    message = "qutip worker simulated qubit loss noise"
    return _build_response(True, qutip_status="simulated", qubit_lost=lost, message=message)

  if noise_kind in {"dephasing", "dephase", "decoherence"}:
    duration = _as_float(operation.get("duration", 0.0))
    mods = _coerce_qutip_modules()
    if mods is None:
      return _build_response(True, qutip_status="simulated", fidelity_estimate=max(0.0, 1.0 - p), message="qutip worker simulated dephasing/decoherence noise")

    qutip, _ = mods
    normalized_noise_kind = "decoherence" if noise_kind == "decoherence" else "dephasing"
    success, fidelity, message, _ = _calculate_qutip_noise_fidelity(
        qutip=qutip,
        noise_kind=normalized_noise_kind,
        operation=operation,
        duration=duration,
    )
    return _build_response(
        success,
        qutip_status=_normalize_status("implemented" if success else "unsupported"),
        fidelity_estimate=fidelity,
        message=message,
    )

  if noise_kind == "reset":
    return _build_response(True, qutip_status="simulated", message="qutip worker simulated reset noise")

  if noise_kind in {"amplitude_damping", "thermal_relaxation", "bitflip", "phaseflip", "depolarizing", "polarization_decoherence"}:
    duration = _as_float(operation.get("duration", 0.0))
    mods = _coerce_qutip_modules()
    if mods is None:
      p = _effective_probability(params_f[0] if params_f else payload.get("p", 0.0))
      if noise_kind in {"amplitude_damping", "thermal_relaxation"}:
        relaxed = _rng(seed, operation).random() < p
        return _build_response(True, qutip_status="simulated", relaxed_to_ground=relaxed, fidelity_estimate=max(0.0, 1.0 - p), message=f"qutip worker simulated {noise_kind} noise")
      return _build_response(True, qutip_status="simulated", fidelity_estimate=max(0.0, 1.0 - p), message=f"qutip worker simulated {noise_kind} noise")

    qutip, _ = mods
    success, fidelity, message, _meta = _calculate_qutip_noise_fidelity(
        qutip=qutip,
        noise_kind=noise_kind,
        operation=operation,
        duration=duration,
    )
    return _build_response(success, qutip_status=_normalize_status("implemented" if success else "unsupported"), message=message, fidelity_estimate=fidelity)

  return _build_response(False, qutip_status="unsupported", message=_categorize_error("unsupported_noise", f"qutip worker unsupported noise kind: {noise_kind}"), error_category="unsupported_noise")


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
        qutip_status="unsupported",
        message=f"qutip worker unsupported backend class: {backend_class}",
        error_category="unsupported_backend_class",
    )

  max_register_qubits = config.get("qutip_max_register_qubits")
  if max_register_qubits is not None:
    try:
      max_register_qubits = int(max_register_qubits)
    except (TypeError, ValueError):
      return _build_response(
          False,
          qutip_status="unsupported",
          message=_categorize_error("invalid_payload", "invalid qutip_max_register_qubits payload value"),
          error_category="invalid_payload",
      )
    if max_register_qubits > 0:
      unique_qubits = _collect_unique_qubits(operation)
      if len(unique_qubits) > max_register_qubits:
        return _build_response(
            False,
            qutip_status="unsupported",
            message=f"qutip backend config limit exceeded: register_qubits={len(unique_qubits)} > {max_register_qubits}",
            error_category="exceeded_limit",
        )

  max_hilbert_dim = config.get("qutip_max_hilbert_dim")
  try:
    max_hilbert_dim = int(max_hilbert_dim)
  except (TypeError, ValueError):
    if max_hilbert_dim is not None:
      return _build_response(
          False,
          qutip_status="unsupported",
          message=_categorize_error("invalid_payload", "invalid qutip_max_hilbert_dim payload value"),
          error_category="invalid_payload",
      )
    max_hilbert_dim = None
  if max_hilbert_dim is not None and max_hilbert_dim > 0:
    ancillary_modes = operation.get("ancillary_modes", [])
    if isinstance(ancillary_modes, list) and len(ancillary_modes) > max_hilbert_dim:
      return _build_response(
          False,
          qutip_status="unsupported",
          message=f"qutip backend config limit exceeded: ancillary_modes={len(ancillary_modes)} > {max_hilbert_dim}",
          error_category="exceeded_limit",
      )
  return None


def _trace_fields(request: dict, operation: dict) -> dict:
  config = request.get("backend_config", {}) if isinstance(request, dict) else {}
  backend_name = str(request.get("backend_type", "qutip") if isinstance(request, dict) else "qutip")
  backend_class = _normalized_backend_class(str(config.get("qutip_backend_class", backend_name)))
  time = request.get("time", 0.0)
  return {
      "backend_name": backend_name,
      "backend_class": backend_class,
      "operation_kind": str(operation.get("kind", "")),
      "operation_id": int(_next_operation_id(request, operation)),
      "seed": _get_request_seed(request),
      "time": time,
      "targets": len(operation.get("targets", []) if isinstance(operation.get("targets", []), list) else []),
      "controls": len(operation.get("controls", []) if isinstance(operation.get("controls", []), list) else []),
      "ancillary_modes": len(operation.get("ancillary_modes", []) if isinstance(operation.get("ancillary_modes", []), list) else []),
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
      "measure": "measurement",
      "kerreffect": "kerr",
      "kerr_effect": "kerr",
      "cross_kerr_effect": "cross_kerr",
      "crosskerr": "cross_kerr",
      "cross_kerring": "cross_kerr",
      "kerr_effects": "kerr",
      "amplitude_damping": "amplitude_damping",
      "amplitudedamping": "amplitude_damping",
      "bit_flip": "bitflip",
      "bitflip": "bitflip",
      "phase_flip": "phaseflip",
      "phaseflip": "phaseflip",
      "depolarizing_channel": "depolarizing",
      "depolarizing": "depolarizing",
      "thermal_relaxation": "thermal_relaxation",
      "polarization_rotation": "polarization_rotation",
      "polarizationrotation": "polarization_rotation",
      "polarization_decoherence": "polarization_decoherence",
      "polarizationdecoherence": "polarization_decoherence",
      "mode_coupling": "mode_coupling",
      "loss_mode": "loss_mode",
      "two_mode_squeezing": "two_mode_squeezing",
      "two_modes_squeezing": "two_mode_squeezing",
      "fock_loss": "fock_loss",
      "photon_number_cutoff": "photon_number_cutoff",
      "beamsplitter": "beam_splitter",
      "beam_splitter": "beam_splitter",
      "phaseshift": "phase_shift",
      "phase_shifter": "phase_shift",
      "phaseshifter": "phase_shift",
      "phase_mod": "phase_modulation",
      "phase_modulator": "phase_modulation",
      "self_phase_mod": "self_phase_modulation",
      "self_phase_modulator": "self_phase_modulation",
      "cross_phase_mod": "cross_phase_modulation",
      "cross_phase_modulator": "cross_phase_modulation",
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
      "timingjitter": "timing_jitter",
      "time_jitter": "timing_jitter",
      "timejitter": "timing_jitter",
      "timing_jitter": "timing_jitter",
      "jitter": "timing_jitter",
  }
  if normalized in aliases:
    return aliases[normalized]
  return normalized


_SUPPORTED_ADVANCED_KINDS = {
    "kerr",
    "cross_kerr",
    "beam_splitter",
    "loss",
    "attenuation",
    "phase_shift",
    "phase_modulation",
    "self_phase_modulation",
    "cross_phase_modulation",
    "decoherence",
    "dephasing",
    "amplitude_damping",
    "thermal_relaxation",
    "bitflip",
    "phaseflip",
    "depolarizing",
    "nonlinear",
    "polarization_rotation",
    "polarization_decoherence",
    "mode_coupling",
    "loss_mode",
    "two_mode_squeezing",
    "fock_loss",
    "photon_number_cutoff",
    "detection",
    "delay",
    "hamiltonian",
    "lindblad",
    "heralded_entanglement",
    "timing_jitter",
    "jitter",
    "dispersion",
    "multiphoton",
    "source_multiphoton",
    "hom_interference",
    "squeezing",
    "reset",
}

_IMPLEMENTED_ADVANCED_KINDS = {
    "phase_shift",
    "phase_modulation",
    "self_phase_modulation",
    "cross_phase_modulation",
    "nonlinear",
    "kerr",
    "cross_kerr",
    "beam_splitter",
    "loss",
    "attenuation",
    "hamiltonian",
    "lindblad",
    "decoherence",
    "dephasing",
    "amplitude_damping",
    "thermal_relaxation",
    "bitflip",
    "phaseflip",
    "depolarizing",
    "detection",
    "polarization_rotation",
    "polarization_decoherence",
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
    return _build_response(
        False,
        qutip_status="unsupported",
        message=_categorize_error("timeout", f"qutip worker timed out after {int(timeout_seconds * 1000)} ms ({elapsed_ms} ms elapsed)"),
        error_category="timeout",
    )

  success, value = output.get_nowait()
  if success:
    return value
  return _build_response(
      False,
      qutip_status="unsupported",
      message=_categorize_error("solver_error", f"qutip worker internal error: {value}"),
      error_category="solver_error",
  )


def _handle_advanced(operation: dict, seed: int) -> dict:
  kind = _canonicalize_kind(operation.get("kind", ""))
  params = operation.get("params", [])
  payload = operation.get("payload", {})
  duration = _as_float(operation.get("duration", 0.0))
  backend_name = str(payload.get("backend_name", ""))
  params_f = _float_list(params)
  rng = _rng(seed, operation)

  def _qutip_required() -> tuple[bool, Any]:
    qutip_modules = _coerce_qutip_modules()
    if qutip_modules is None:
      return False, "qutip worker cannot execute qutip operation: missing qutip/qutip_qip"
    return True, qutip_modules

  if kind == "kerr":
    available, qutip_modules = _qutip_required()
    if not available:
      return _mark_operation_metrics(
          _build_response(False, qutip_status="unsupported", message=_categorize_error("qutip_import", qutip_modules)),
          backend_name=backend_name,
          kind=kind,
          duration=duration,
          qutip_status="unsupported",
      )
    qutip, _ = qutip_modules
    success, fidelity, detail = _calculate_qutip_kerr_fidelity(qutip=qutip, operation=operation, duration=duration)
    return _mark_operation_metrics(
        _build_response(success, qutip_status="implemented" if success else "unsupported", fidelity_estimate=fidelity, message=detail),
        backend_name=backend_name,
        kind=kind,
        duration=duration,
        qutip_status="implemented" if success else "unsupported",
    )
  if kind == "cross_kerr":
    available, qutip_modules = _qutip_required()
    if not available:
      return _mark_operation_metrics(
          _build_response(False, qutip_status="unsupported", message=_categorize_error("qutip_import", qutip_modules)),
          backend_name=backend_name,
          kind=kind,
          duration=duration,
          qutip_status="unsupported",
      )
    qutip, _ = qutip_modules
    success, fidelity, detail = _calculate_qutip_cross_kerr_fidelity(qutip=qutip, operation=operation, duration=duration)
    return _mark_operation_metrics(
        _build_response(success, qutip_status="implemented" if success else "unsupported", fidelity_estimate=fidelity, message=detail),
        backend_name=backend_name,
        kind=kind,
        duration=duration,
        qutip_status="implemented" if success else "unsupported",
    )
  if kind == "beam_splitter":
    available, qutip_modules = _qutip_required()
    if not available:
      return _mark_operation_metrics(
          _build_response(False, qutip_status="unsupported", message=_categorize_error("qutip_import", qutip_modules)),
          backend_name=backend_name,
          kind=kind,
          duration=duration,
          qutip_status="unsupported",
      )
    qutip, _ = qutip_modules
    success, fidelity, detail = _calculate_qutip_beam_splitter_fidelity(qutip=qutip, operation=operation, duration=duration)
    return _mark_operation_metrics(
        _build_response(success, qutip_status="implemented" if success else "unsupported", fidelity_estimate=fidelity, message=detail),
        backend_name=backend_name,
        kind=kind,
        duration=duration,
        qutip_status="implemented" if success else "unsupported",
    )
  if kind == "phase_shift":
    available, qutip_modules = _qutip_required()
    if not available:
      return _mark_operation_metrics(
          _build_response(False, qutip_status="unsupported", message=_categorize_error("qutip_import", qutip_modules)),
          backend_name=backend_name,
          kind=kind,
          duration=duration,
          qutip_status="unsupported",
      )
    qutip, _ = qutip_modules
    success, fidelity, detail = _calculate_qutip_phase_fidelity(qutip=qutip, operation=operation, duration=duration, axis="z")
    return _mark_operation_metrics(
        _build_response(success, qutip_status="implemented" if success else "unsupported", fidelity_estimate=fidelity, message=detail),
        backend_name=backend_name,
        kind=kind,
        duration=duration,
        qutip_status="implemented" if success else "unsupported",
    )
  if kind in {"phase_modulation", "self_phase_modulation", "cross_phase_modulation", "nonlinear"}:
    available, qutip_modules = _qutip_required()
    if not available:
      return _mark_operation_metrics(
          _build_response(False, qutip_status="unsupported", message=_categorize_error("qutip_import", qutip_modules)),
          backend_name=backend_name,
          kind=kind,
          duration=duration,
          qutip_status="unsupported",
      )
    qutip, _ = qutip_modules
    success, fidelity, detail = _calculate_qutip_coupled_phase_fidelity(qutip=qutip, operation=operation, duration=duration, mode=kind)
    return _mark_operation_metrics(
        _build_response(success, qutip_status="implemented" if success else "unsupported", fidelity_estimate=fidelity, message=detail),
        backend_name=backend_name,
        kind=kind,
        duration=duration,
        qutip_status="implemented" if success else "unsupported",
    )
  if kind == "hom_interference":
    visibility = _as_float(params_f[0] if params_f else payload.get("visibility", 1.0))
    visibility = max(0.0, min(1.0, visibility))
    return _mark_operation_metrics(
        _build_response(True, qutip_status="simulated", fidelity_estimate=visibility, message=f"qutip worker simulated HOM interference with visibility={visibility}, backend={backend_name} in {duration}"),
        backend_name=backend_name,
        kind=kind,
        duration=duration,
        qutip_status="simulated",
    )
  if kind in {"decoherence", "dephasing"}:
    available, qutip_modules = _qutip_required()
    if not available:
      return _mark_operation_metrics(
          _build_response(False, qutip_status="unsupported", message=_categorize_error("qutip_import", qutip_modules), error_category="qutip_import"),
          backend_name=backend_name,
          kind=kind,
          duration=duration,
          qutip_status="unsupported",
      )
    qutip, _ = qutip_modules
    success, fidelity, detail, _meta = _calculate_qutip_noise_fidelity(
        qutip=qutip,
        noise_kind="decoherence" if kind == "decoherence" else "dephasing",
        operation=operation,
        duration=duration,
    )
    return _mark_operation_metrics(
        _build_response(success, qutip_status="implemented" if success else "unsupported", fidelity_estimate=fidelity, message=detail),
        backend_name=backend_name,
        kind=kind,
        duration=duration,
        qutip_status="implemented" if success else "unsupported",
    )
  if kind in {"loss", "attenuation"}:
    available, qutip_modules = _qutip_required()
    p = _effective_probability(params_f[0] if params_f else payload.get("p", payload.get("rate", 0.0)))
    qubit_lost = rng.random() < p
    if not available:
      return _mark_operation_metrics(
          _build_response(
              True,
              qutip_status="simulated",
              qubit_lost=qubit_lost,
              fidelity_estimate=1.0 - p,
              message=f"qutip worker simulated channel loss/decoherence with p={p}, backend={backend_name} in {duration}",
          ),
          backend_name=backend_name,
          kind=kind,
          duration=duration,
          qutip_status="simulated",
      )
    qutip, _ = qutip_modules
    success, fidelity, detail, _meta = _calculate_qutip_loss_fidelity(qutip=qutip, operation=operation, duration=duration)
    return _mark_operation_metrics(
        _build_response(
            success,
            qutip_status=_normalize_status("implemented" if success else "unsupported"),
            fidelity_estimate=fidelity if success else 1.0 - p,
            qubit_lost=qubit_lost,
            message=detail,
        ),
        backend_name=backend_name,
        kind=kind,
        duration=duration,
        qutip_status=_normalize_status("implemented" if success else "unsupported"),
    )
  if kind in {"timing_jitter", "jitter"}:
    jitter_std = _as_float(payload.get("jitter", params_f[0] if params_f else payload.get("std", 0.0)))
    fidelity = _simple_fidelity_decay(0.01 * abs(jitter_std), duration)
    return _mark_operation_metrics(
        _build_response(True, qutip_status="simulated", fidelity_estimate=fidelity, message=f"qutip worker simulated timing jitter with std={jitter_std}, backend={backend_name} in {duration}"),
        backend_name=backend_name,
        kind=kind,
        duration=duration,
        qutip_status="simulated",
    )
  if kind == "reset":
    return _mark_operation_metrics(
        _build_response(True, qutip_status="simulated", message=f"qutip worker simulated reset in backend={backend_name} during {duration}"),
        backend_name=backend_name,
        kind=kind,
        duration=duration,
        qutip_status="simulated",
    )
  if kind == "detection":
    raw_dark_count = payload.get("dark_count", payload.get("detector", payload.get("p", params_f[0] if params_f else 0.0)))
    p = _effective_probability(raw_dark_count)
    available, qutip_modules = _qutip_required()
    if not available:
      detected = rng.random() > p
      return _mark_operation_metrics(
          _build_response(True, qutip_status="simulated", measured_plus=detected, fidelity_estimate=1.0 - p, message=f"qutip worker simulated detection p={p}, backend={backend_name}"),
          backend_name=backend_name,
          kind=kind,
          duration=duration,
          qutip_status="simulated",
      )
    qutip, _ = qutip_modules
    detected = rng.random() > p
    return _mark_operation_metrics(
        _build_response(True, qutip_status="implemented", measured_plus=detected, fidelity_estimate=1.0 - p, message=f"qutip worker applied detection with qutip path p={p}, backend={backend_name}"),
        backend_name=backend_name,
        kind=kind,
        duration=duration,
        qutip_status="implemented",
    )
  if kind == "delay":
    return _mark_operation_metrics(_build_response(True, message=f"qutip worker simulated delay of {duration} for {backend_name}"),
                                  backend_name=backend_name,
                                  kind=kind,
                                  duration=duration,
                                  qutip_status="simulated")
  if kind in {"lindblad", "hamiltonian"}:
    available, qutip_modules = _qutip_required()
    if not available:
      return _mark_operation_metrics(
          _build_response(False, qutip_status="unsupported", message=_categorize_error("qutip_import", qutip_modules)),
          backend_name=backend_name,
          kind=kind,
          duration=duration,
          qutip_status="unsupported",
      )
    qutip, _ = qutip_modules
    if kind == "hamiltonian":
      success, fidelity, detail = _calculate_qutip_hamiltonian_fidelity(qutip=qutip, operation=operation, duration=duration)
    else:
      success, fidelity, detail = _calculate_qutip_lindblad_fidelity(qutip=qutip, operation=operation, duration=duration)
    return _mark_operation_metrics(
        _build_response(success, qutip_status="implemented" if success else "unsupported", message=detail, fidelity_estimate=fidelity),
        backend_name=backend_name,
        kind=kind,
        duration=duration,
        qutip_status="implemented" if success else "unsupported",
    )
  if kind == "heralded_entanglement":
    threshold = _effective_probability(payload.get("success_probability", params_f[0] if params_f else 0.8), 0.8)
    success = rng.random() < threshold
    return _mark_operation_metrics(
        _build_response(True, qutip_status="simulated", measured_plus=success, message=f"qutip worker simulated heralded entanglement in {backend_name}, success={success}", fidelity_estimate=threshold),
        backend_name=backend_name,
        kind=kind,
        duration=duration,
        qutip_status="simulated",
    )
  if kind in {"dispersion", "multiphoton", "squeezing"}:
    p = _as_float(payload.get("strength", payload.get("p", 0.0)), 0.0)
    return _mark_operation_metrics(
        _build_response(True,
                        qutip_status="simulated",
                        fidelity_estimate=_simple_fidelity_decay(p, duration),
                        message=f"qutip worker simulated channel effect kind={kind} in backend={backend_name}"),
        backend_name=backend_name,
        kind=kind,
        duration=duration,
        qutip_status="simulated",
    )
  if kind in {"amplitude_damping", "thermal_relaxation"}:
    p = _effective_probability(params_f[0] if params_f else payload.get("p", payload.get("rate", 0.0)))
    relaxed = rng.random() < p
    return _mark_operation_metrics(
        _build_response(
            True,
            qutip_status="implemented",
            relaxed_to_ground=relaxed,
            fidelity_estimate=max(0.0, 1.0 - p),
            message=f"qutip worker simulated {kind} with p={p}, backend={backend_name}",
        ),
        backend_name=backend_name,
        kind=kind,
        duration=duration,
        qutip_status="implemented",
    )
  if kind in {"bitflip", "phaseflip", "depolarizing", "polarization_decoherence"}:
    p = _effective_probability(params_f[0] if params_f else payload.get("p", payload.get("rate", 0.0)))
    if kind == "polarization_decoherence":
      available, qutip_modules = _qutip_required()
      if not available:
        return _mark_operation_metrics(
            _build_response(True, qutip_status="simulated", fidelity_estimate=max(0.0, 1.0 - p), message=f"qutip worker simulated {kind} channel p={p}, backend={backend_name}"),
            backend_name=backend_name,
            kind=kind,
            duration=duration,
            qutip_status="simulated",
        )
      qutip, _ = qutip_modules
      decoherence_op = dict(operation)
      decoherence_op["kind"] = "decoherence"
      success, fidelity, message, _ = _calculate_qutip_noise_fidelity(
          qutip=qutip,
          noise_kind="decoherence",
          operation=decoherence_op,
          duration=duration,
      )
      return _mark_operation_metrics(
          _build_response(success, qutip_status="implemented" if success else "unsupported", fidelity_estimate=fidelity, message=message),
          backend_name=backend_name,
          kind=kind,
          duration=duration,
          qutip_status="implemented" if success else "unsupported",
      )

    return _mark_operation_metrics(
        _build_response(True, qutip_status="implemented", fidelity_estimate=max(0.0, 1.0 - p), message=f"qutip worker simulated {kind} channel p={p}, backend={backend_name}"),
        backend_name=backend_name,
        kind=kind,
        duration=duration,
        qutip_status="implemented",
    )
  if kind == "polarization_rotation":
    available, qutip_modules = _qutip_required()
    if not available:
      return _mark_operation_metrics(
          _build_response(False, qutip_status="unsupported", message=_categorize_error("qutip_import", qutip_modules)),
          backend_name=backend_name,
          kind=kind,
          duration=duration,
          qutip_status="unsupported",
      )
    qutip, _ = qutip_modules
    axis = str(payload.get("axis", payload.get("basis", "z")))
    success, fidelity, detail = _calculate_qutip_phase_fidelity(
        qutip=qutip,
        operation=operation,
        duration=duration,
        axis=axis,
    )
    return _mark_operation_metrics(
        _build_response(success, qutip_status="implemented" if success else "unsupported", fidelity_estimate=fidelity, message=detail),
        backend_name=backend_name,
        kind=kind,
        duration=duration,
        qutip_status="implemented" if success else "unsupported",
    )
  if kind in {"mode_coupling", "loss_mode", "fock_loss", "photon_number_cutoff", "two_mode_squeezing", "beam_splitter"}:
    coupling = _as_float(payload.get("coupling", params_f[0] if params_f else 0.0))
    return _mark_operation_metrics(
        _build_response(True, qutip_status="simulated", fidelity_estimate=_simple_fidelity_decay(abs(coupling), duration),
                       message=f"qutip worker simulated {kind} with coupling={coupling}, backend={backend_name}"),
        backend_name=backend_name,
        kind=kind,
        duration=duration,
        qutip_status="simulated",
    )
  if kind == "source_multiphoton":
    strength = _as_float(payload.get("strength", params_f[0] if params_f else 0.0), 0.0)
    return _mark_operation_metrics(
        _build_response(
            True,
            qutip_status="simulated",
            fidelity_estimate=_simple_fidelity_decay(strength, duration),
            message=f"qutip worker simulated source multiphoton with strength={strength}, backend={backend_name} in {duration}",
        ),
        backend_name=backend_name,
        kind=kind,
        duration=duration,
        qutip_status="simulated",
    )
  if kind == "measurement":
    measurement_status = _handle_measurement(operation, seed)
    # Keep the status returned by _handle_measurement so invalid/unsupported
    # measurement kinds remain classified correctly.
    return _mark_operation_metrics(
        measurement_status,
        backend_name=backend_name,
        kind=kind,
        duration=duration,
        qutip_status=measurement_status.get("qutip_status"),
    )

  supported = ", ".join(sorted(_SUPPORTED_ADVANCED_KINDS))
  return _mark_operation_metrics(
      _build_response(
          False,
          qutip_status="unsupported",
          message=_categorize_error("unsupported_kind", f"qutip worker advanced operation not supported yet: {kind}. supported_advanced={supported}"),
          error_category="unsupported_kind",
      ),
      backend_name=backend_name,
      kind=kind,
      duration=duration,
      qutip_status="unsupported",
  )


def _handle_noop() -> dict:
  return _build_response(True, qutip_status="simulated", message="qutip worker noop")


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
  strict = _strict_simulated_enabled(request)

  if kind == "unitary":
    response = _run_with_timeout(_handle_unitary, operation, seed, timeout_ms)
    response.update(trace)
    return _apply_strict_simulated_mode(response, strict, kind)
  if kind == "measurement":
    response = _run_with_timeout(_handle_measurement, operation, seed, timeout_ms)
    response.update(trace)
    return _apply_strict_simulated_mode(response, strict, kind)
  if kind == "noise":
    response = _run_with_timeout(_handle_noise, operation, seed, timeout_ms)
    response.update(trace)
    return _apply_strict_simulated_mode(response, strict, kind)
  if kind == "noop":
    response = _handle_noop()
    response.update(trace)
    return _apply_strict_simulated_mode(response, strict, kind)
  if _is_advanced_operation_kind(kind):
    response = _run_with_timeout(_handle_advanced, operation, seed, timeout_ms)
    response.update(trace)
    return _apply_strict_simulated_mode(response, strict, kind)

  return _apply_strict_simulated_mode(
      _build_response(False, qutip_status="unsupported", message=_categorize_error("unsupported_kind", f"qutip worker unknown operation kind: {kind}"), error_category="unsupported_kind"),
      strict,
      kind,
  )


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
    response = _build_response(False, qutip_status="unsupported", message=f"qutip worker request parse error: {exc}", error_category="invalid_payload")
    output_path.write_text(json.dumps(response), encoding="utf-8")
    return 1

  response = run_operation(request)
  output_path.write_text(json.dumps(response), encoding="utf-8")
  return 0 if response.get("success") else 2


if __name__ == "__main__":
  raise SystemExit(main())
