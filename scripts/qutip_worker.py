#!/usr/bin/env python3
"""Lightweight qutip command worker used by QuISP.

The worker receives a JSON request and emits a JSON response.
This worker is intentionally strict: if qutip/qutip_qip/qutip.qip cannot be
imported, operations are rejected with an explicit import-related error.
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
from dataclasses import dataclass
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


@dataclass(frozen=True)
class QutipProfile:
  name: str
  node_dim: int
  link_mode_dim: int
  mode: str
  leakage_enabled: bool = False
  truncation: int = 5


_QUTIP_PROFILE_PRESETS = {
    "standard_light": QutipProfile(name="standard_light", node_dim=2, link_mode_dim=2, mode="light"),
    "standard_qutrit": QutipProfile(name="standard_qutrit", node_dim=3, link_mode_dim=4, mode="qutrit"),
    "high_fidelity": QutipProfile(name="high_fidelity", node_dim=5, link_mode_dim=6, mode="high_fidelity"),
}


_QUTIP_IMPORT_CACHE: Optional[tuple[Any, Any]] = None
_QUTIP_IMPORT_CACHE_ERROR: Optional[str] = None
_OPERATION_SEQUENCE = 0


def _coerce_profile_int(value: Any, default: int, minimum: int = 1) -> tuple[int, Optional[str]]:
  if value is None:
    return default, None
  try:
    parsed = int(value)
  except (TypeError, ValueError):
    return default, f"invalid integer value: {value}"
  if parsed < minimum:
    return minimum, f"profile value below minimum ({minimum}): {value}"
  return parsed, None


def _coerce_profile_bool(value: Any, default: bool) -> tuple[bool, Optional[str]]:
  if value is None:
    return default, None
  if isinstance(value, bool):
    return value, None
  if isinstance(value, (int, float)):
    return bool(int(value)), None
  text = str(value).strip().lower()
  if text in {"1", "true", "yes", "on"}:
    return True, None
  if text in {"0", "false", "no", "off"}:
    return False, None
  return default, f"invalid boolean value: {value}"


def _resolve_profile_bool(profile_meta: Optional[dict[str, Any]], key: str, default: bool = False) -> bool:
  if not isinstance(profile_meta, dict):
    return default
  return bool(_as_bool(profile_meta.get(key), default))


def _effective_profile_dim(profile_meta: Optional[dict[str, Any]], fallback: int) -> int:
  base_dim, _ = _coerce_profile_int(fallback, max(2, int(fallback)), 2)
  if not isinstance(profile_meta, dict):
    return base_dim

  requested_dim, _ = _coerce_profile_int(profile_meta.get("dim"), base_dim, 2)
  return int(max(2, requested_dim))


def _parse_profile_overrides(raw: Any) -> tuple[dict[str, Any], Optional[str]]:
  if raw is None:
    return {}, None
  if isinstance(raw, dict):
    return raw, None
  if isinstance(raw, str):
    if not raw.strip():
      return {}, None
    try:
      loaded = json.loads(raw)
    except Exception as exc:
      return {}, f"cannot parse qutip_profile_overrides JSON: {exc}"
    if isinstance(loaded, dict):
      return loaded, None
    return {}, "qutip_profile_overrides must be a JSON object"
  return {}, "qutip_profile_overrides must be a JSON string/object"


def _normalize_profile_name(value: str) -> str:
  normalized = str(value).strip().lower()
  normalized = normalized.replace("-", "_")
  normalized = normalized.replace(" ", "_")
  while "__" in normalized:
    normalized = normalized.replace("__", "_")
  return normalized


_LINK_KIND_SET = {
    "heralded_entanglement",
    "attenuation",
    "loss",
    "hom_interference",
    "dispersion",
    "multiphoton",
    "source_multiphoton",
    "squeezing",
    "mode_coupling",
    "loss_mode",
    "fock_loss",
    "photon_number_cutoff",
    "two_mode_squeezing",
}


def _is_link_kind(kind: str, operation: dict) -> bool:
  normalized = _canonicalize_kind(kind)
  if not isinstance(operation, dict):
    return normalized in _LINK_KIND_SET
  return normalized in _LINK_KIND_SET


def _resolve_profile(request: dict, kind: str, operation: dict) -> tuple[str, dict[str, Any], str | None]:
  config = request.get("backend_config", {}) if isinstance(request, dict) else {}
  if not isinstance(config, dict):
    config = {}

  requested_node_profile = _normalize_profile_name(config.get("qutip_node_profile", "standard_light"))
  requested_link_profile = _normalize_profile_name(config.get("qutip_link_profile", "standard_light"))
  if not requested_node_profile:
    requested_node_profile = "standard_light"
  if not requested_link_profile:
    requested_link_profile = "standard_light"

  is_link_operation = _is_link_kind(kind, operation)
  requested_profile = requested_link_profile if is_link_operation else requested_node_profile
  if not requested_profile:
    requested_profile = "standard_light"

  if requested_profile == "custom":
    return _resolve_custom_profile(
      requested_profile=requested_profile,
      is_link_operation=is_link_operation,
      parse_profile=config.get("qutip_profile_overrides", None),
    )

  requested_profile_name = requested_profile
  preset_profile = _QUTIP_PROFILE_PRESETS.get(requested_profile)

  _, parse_error = _parse_profile_overrides(config.get("qutip_profile_overrides"))
  errors = []
  if parse_error is not None:
    errors.append(parse_error)

  profile_error: str | None = None
  if preset_profile is None:
    errors.append(f"unsupported profile '{requested_profile_name}', fallback to standard_light")
    preset_profile = _QUTIP_PROFILE_PRESETS["standard_light"]
    profile_error = "invalid_profile"
  elif parse_error is not None:
    profile_error = "invalid_profile"

  mode = "link" if is_link_operation else "node"
  chosen_dim = preset_profile.link_mode_dim if is_link_operation else preset_profile.node_dim

  profile_meta = {
      "profile": preset_profile.name,
      "requested_profile": requested_profile_name,
      "node_dim": int(preset_profile.node_dim),
      "link_dim": int(preset_profile.link_mode_dim),
      "mode": mode,
      "dim": int(chosen_dim),
      "leakage_enabled": bool(preset_profile.leakage_enabled),
      "truncation": int(preset_profile.truncation),
      "errors": " | ".join(errors) if errors else None,
  }

  return preset_profile.name, profile_meta, profile_error


def _resolve_custom_profile(
    requested_profile: str, is_link_operation: bool, parse_profile: Any
) -> tuple[str, dict[str, Any], str | None]:
  base_profile = _QUTIP_PROFILE_PRESETS["standard_light"]
  overrides, parse_error = _parse_profile_overrides(parse_profile)
  errors = []
  if parse_error is not None:
    errors.append(parse_error)
    profile_error = "invalid_profile"

  node_dim = overrides.get("node_dim")
  link_mode_dim = overrides.get("link_mode_dim")
  leakage_enabled = overrides.get("leakage_enabled")
  truncation = overrides.get("truncation")

  coerced_node_dim, node_err = _coerce_profile_int(node_dim, base_profile.node_dim, 2)
  coerced_link_mode_dim, link_err = _coerce_profile_int(link_mode_dim, base_profile.link_mode_dim, 2)
  coerced_leakage, leak_err = _coerce_profile_bool(leakage_enabled, base_profile.leakage_enabled)
  coerced_truncation, trunc_err = _coerce_profile_int(truncation, base_profile.truncation, 2)

  profile_error = "invalid_profile" if parse_error is not None else None
  for error in (node_err, link_err, leak_err, trunc_err):
    if error is not None:
      profile_error = "invalid_profile"
      errors.append(error)

  profile = QutipProfile(
    name="custom",
    node_dim=coerced_node_dim,
    link_mode_dim=coerced_link_mode_dim,
    mode="custom",
    leakage_enabled=coerced_leakage,
    truncation=coerced_truncation,
  )

  profile_name = profile.name
  profile_meta = {
      "profile": profile_name,
      "requested_profile": requested_profile,
      "node_dim": int(profile.node_dim),
      "link_dim": int(profile.link_mode_dim),
      "mode": "link" if is_link_operation else "node",
      "dim": int(profile.link_mode_dim if is_link_operation else profile.node_dim),
      "leakage_enabled": bool(profile.leakage_enabled),
      "truncation": int(profile.truncation),
      "errors": " | ".join(errors) if errors else None,
  }

  return profile_name, profile_meta, profile_error


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
    import qutip.qip  # type: ignore
    _QUTIP_IMPORT_CACHE = (qutip, qutip_qip)
    return _QUTIP_IMPORT_CACHE
  except Exception as exc:
    _QUTIP_IMPORT_CACHE_ERROR = str(exc)
    return None


def _qutip_unavailable_response(kind: str) -> dict:
  return _build_response(
      False,
      qutip_status="unsupported",
      error_category="qutip_import",
      message=_categorize_error("qutip_import", f"qutip backend unavailable for kind={kind}: {_QUTIP_IMPORT_CACHE_ERROR or 'qutip import failed'}"),
  )


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


def _build_response(
    success: bool,
    error_category: Optional[str] = None,
    qutip_status: Optional[str] = None,
    meta: Optional[dict[str, Any]] = None,
    **fields,
) -> dict:
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
  if meta is not None:
    response["meta"] = dict(meta)
  response.update(fields)
  return response


def _attach_profile_metadata(response: dict, profile_meta: Optional[dict[str, Any]]) -> dict:
  if profile_meta is None:
    return response
  meta = dict(profile_meta)
  current_meta = response.get("meta")
  if isinstance(current_meta, dict):
    meta.update(current_meta)
  response["meta"] = meta
  return response


def _measurement_plus_probability(basis: str, dim: int = 2) -> tuple[float, float]:
  normalized_dim = max(2, int(dim))
  if normalized_dim < 2:
    normalized_dim = 2
  if basis == "Z":
    return 1.0, 0.0
  if basis in {"X", "Y", "BELL"}:
    return 0.5, 0.5
  return 0.0, 0.0


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


def _identity_in_dim(qutip: Any, dim: int) -> Any:
  return qutip.qeye(max(2, int(dim)))


def _lift_2d_operator_to_dim(qutip: Any, operator: Any, dim: int) -> Optional[Any]:
  if operator is None:
    return None
  try:
    src_dim = operator.shape[0]
    if operator.shape[0] != operator.shape[1]:
      return None
  except Exception:
    return None

  src_dim = int(src_dim)
  normalized_dim = max(2, int(dim))
  if src_dim == normalized_dim:
    return operator
  if src_dim != 2:
    return None

  matrix = operator.full()
  basis = [qutip.basis(normalized_dim, i) for i in range(2)]
  zero = _identity_in_dim(qutip, normalized_dim) * 0
  embedded = zero
  for i in range(2):
    for j in range(2):
      coeff = matrix[i][j]
      if coeff != 0:
        embedded += coeff * (basis[i] * basis[j].dag())
  return embedded


def _qubit_subspace_projector(qutip: Any, dim: int, level: int) -> Optional[Any]:
  try:
    normalized_dim = max(2, int(dim))
    level_int = int(level)
    if level_int < 0 or level_int >= normalized_dim:
      return None
  except (TypeError, ValueError):
    return None
  basis_state = qutip.basis(normalized_dim, level_int)
  return basis_state * basis_state.dag()


def _logical_pauli_in_dim(qutip: Any, dim: int, token: str) -> Optional[Any]:
  normalized = token.strip().lower().replace(" ", "")
  normalized = re.sub(r"[^a-z0-9_]+", "", normalized)
  if normalized in {"i", "id", "identity", "eye"}:
    return _identity_in_dim(qutip, dim)

  source_map = {
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
  }
  factory = source_map.get(normalized)
  if factory is None:
    return None
  return _lift_2d_operator_to_dim(qutip, factory(), dim)


def _parse_single_pauli(expr: str, qutip: Any, dim: int) -> Optional[Any]:
  return _logical_pauli_in_dim(qutip, dim, expr)


def _parse_operator_expr(expr: str, n_targets: int, qutip: Any, dim: int) -> Optional[Any]:
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
    op = _parse_single_pauli(token, qutip, dim)
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


def _basis_state_from_targets(qutip: Any, n_targets: int, dim: int = 2) -> Any:
  if n_targets <= 0:
    return None
  normalized_dim = max(2, int(dim))
  if n_targets == 1:
    return qutip.basis(normalized_dim, 0)
  try:
    return qutip.tensor(*([qutip.basis(normalized_dim, 0)] * n_targets))
  except Exception:
    return qutip.basis(normalized_dim ** n_targets, 0)


def _embed_qubit_operator(qutip: Any, operator: Any, n_targets: int, target_index: int, dim: int = 2) -> Optional[Any]:
  if n_targets <= 0 or target_index < 0 or target_index >= n_targets:
    return None
  local_operator = _lift_2d_operator_to_dim(qutip, operator, dim)
  if local_operator is None:
    return None
  operators = [_identity_in_dim(qutip, dim) for _ in range(n_targets)]
  operators[target_index] = local_operator
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
    dim: int,
    leakage_enabled: bool = False,
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
    sigma_x = _logical_pauli_in_dim(qutip, dim, "sx")
    sigma_y = _logical_pauli_in_dim(qutip, dim, "sy")
    sigma_z = _logical_pauli_in_dim(qutip, dim, "sz")
    sigma_m = _logical_pauli_in_dim(qutip, dim, "sxm")
    local_ops = {
        "amplitude_damping": [math.sqrt(rate) * sigma_m] if sigma_m is not None else [],
        "thermal_relaxation": [math.sqrt(rate) * sigma_m] if sigma_m is not None else [],
        "bitflip": [math.sqrt(rate) * sigma_x] if sigma_x is not None else [],
        "phaseflip": [math.sqrt(rate) * sigma_z] if sigma_z is not None else [],
        "depolarizing": [
            math.sqrt(rate / 3.0) * sigma_x if sigma_x is not None else None,
            math.sqrt(rate / 3.0) * sigma_y if sigma_y is not None else None,
            math.sqrt(rate / 3.0) * sigma_z if sigma_z is not None else None,
        ],
        "dephasing": [math.sqrt(rate) * sigma_z] if sigma_z is not None else [],
        "decoherence": [math.sqrt(rate) * sigma_z] if sigma_z is not None else [],
        "loss": [math.sqrt(rate) * sigma_m] if sigma_m is not None else [],
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
      if local_op is None:
        continue
      op = _embed_qubit_operator(qutip, local_op, len(targets), 0, dim)
      if op is not None:
        collapse_ops.append(op)

    if leakage_enabled and int(dim) > 2 and noise_kind in {"amplitude_damping", "thermal_relaxation", "loss"}:
      leakage = qutip.basis(max(2, int(dim)), 2) * qutip.basis(max(2, int(dim)), 1).dag()
      leakage_op = _embed_qubit_operator(qutip, math.sqrt(rate) * leakage, len(targets), 0, dim)
      if leakage_op is not None:
        collapse_ops.append(leakage_op)

    if not collapse_ops:
      return (
          False,
          1.0,
          _categorize_error("invalid_payload", f"qutip worker cannot build collapse operators for {noise_kind}"),
          {},
      )

    if rate <= 0.0:
      return True, 1.0, f"qutip worker applied {noise_kind} with zero rate", {"effective_probability": 0.0, "rate": rate}

    state = _basis_state_from_targets(qutip, len(targets), dim)
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
    dim: int,
    leakage_enabled: bool = False,
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
    sigma_m = _logical_pauli_in_dim(qutip, dim, "sxm")
    if sigma_m is None:
      return (
          False,
          1.0,
          _categorize_error("unsupported_profile", "qutip worker cannot build sigma- for selected profile"),
          {},
      )
    decay = _embed_qubit_operator(qutip, math.sqrt(rate) * sigma_m, len(targets), 0, dim)
    if decay is None:
      return (
          False,
          1.0,
          _categorize_error("invalid_payload", "qutip worker cannot build loss collapse operator"),
          {},
      )

    if rate <= 0.0:
      return True, 1.0, f"qutip worker applied loss with zero rate", {"effective_probability": p, "rate": rate}

    collapse_ops = [decay]
    if leakage_enabled and int(dim) > 2:
      leakage = qutip.basis(max(2, int(dim)), 2) * qutip.basis(max(2, int(dim)), 1).dag()
      leakage_op = _embed_qubit_operator(qutip, math.sqrt(rate) * leakage, len(targets), 0, dim)
      if leakage_op is not None:
        collapse_ops.append(leakage_op)

    state = _basis_state_from_targets(qutip, len(targets), dim)
    tlist = [0.0, max(duration, 1.0)]
    result = qutip.mesolve(qutip.qeye(state.shape[0]), state, tlist, collapse_ops, [])
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


def _calculate_qutip_reset_fidelity(
    qutip: Any,
    operation: dict,
    dim: int,
    leakage_enabled: bool = False,
) -> tuple[bool, float, str]:
  targets = operation.get("targets", []) if isinstance(operation.get("targets", []), list) else []
  if len(targets) != 1:
    return (
        False,
        1.0,
        _categorize_error("invalid_payload", "qutip worker reset requires exactly one target"),
    )

  try:
    state = _basis_state_from_targets(qutip, len(targets), dim)
    if state is None:
      return (
          False,
          1.0,
          _categorize_error("invalid_payload", "qutip worker cannot build reset basis state"),
      )
    rho0 = state * state.dag()
    basis0 = qutip.basis(max(2, int(dim)), 0)
    basis1 = qutip.basis(max(2, int(dim)), 1)
    reset_k0 = _embed_qubit_operator(qutip, basis0 * basis0.dag(), 1, 0, dim)
    reset_k1 = _embed_qubit_operator(qutip, basis0 * basis1.dag(), 1, 0, dim)
    collapse_ops = [reset_k0, reset_k1]
    if leakage_enabled and int(dim) > 2:
      basis2 = qutip.basis(max(2, int(dim)), 2)
      reset_k2 = _embed_qubit_operator(qutip, basis0 * basis2.dag(), 1, 0, dim)
      if reset_k2 is not None:
        collapse_ops.append(reset_k2)
    collapse_ops = [op for op in collapse_ops if op is not None]
    if len(collapse_ops) < 2:
      return (
          False,
          1.0,
          _categorize_error("invalid_payload", "qutip worker cannot build reset Kraus operators"),
      )
    rho_t = collapse_ops[0] * rho0 * collapse_ops[0].dag()
    for op in collapse_ops[1:]:
      rho_t = rho_t + op * rho0 * op.dag()
    fidelity = float(qutip.metrics.fidelity(rho0, rho_t))
    return True, min(1.0, max(0.0, fidelity)), "qutip worker applied reset to ground using qutip Kraus map"
  except Exception as exc:
    return False, 1.0, _categorize_error("solver_error", f"qutip worker reset map failed: {exc}")


def _calculate_qutip_phase_fidelity(qutip: Any, operation: dict, duration: float, axis: str = "z", dim: int = 2) -> tuple[bool, float, str]:
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
    local_op = _logical_pauli_in_dim(qutip, dim, "sx")
  elif axis_normalized in {"y", "sy"}:
    local_op = _logical_pauli_in_dim(qutip, dim, "sy")
  else:
    local_op = _logical_pauli_in_dim(qutip, dim, "sz")
  if local_op is None:
    return False, 1.0, _categorize_error("unsupported_profile", f"qutip worker cannot build phase operator for dim={dim}")

  try:
    hamiltonian = (-1j * angle / 2.0) * local_op
    embed = _embed_qubit_operator(qutip, hamiltonian, n_targets, 0, dim=dim)
    if embed is None:
      return False, 1.0, _categorize_error("invalid_payload", "qutip worker cannot build phase operator")
    if duration <= 0.0:
      return True, 1.0, _categorize_error("invalid_payload", "qutip worker applied zero-duration phase evolution with identity effect")

    state = _basis_state_from_targets(qutip, n_targets, dim)
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
    dim: int = 2,
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
    sigma_z = _logical_pauli_in_dim(qutip, dim, "sz")
    if sigma_z is None:
      return False, 1.0, _categorize_error("unsupported_profile", f"qutip worker cannot build coupled phase operator for dim={dim}")
    if n_targets == 1:
      local_op = (-1j * coeff / 2.0) * sigma_z
      hamiltonian = _embed_qubit_operator(qutip, local_op, n_targets, 0, dim=dim)
    elif mode_normalized in {"cross_phase_modulation", "nonlinear"} and n_targets >= 2:
      left = _embed_qubit_operator(qutip, sigma_z, n_targets, 0, dim=dim)
      right = _embed_qubit_operator(qutip, sigma_z, n_targets, 1, dim=dim)
      if left is None or right is None:
        return False, 1.0, _categorize_error("invalid_payload", f"qutip worker cannot build {mode_normalized} operator")
      hamiltonian = coeff * left * right
    else:
      terms = []
      for index in range(n_targets):
        op = _embed_qubit_operator(qutip, sigma_z, n_targets, index, dim=dim)
        if op is not None:
          terms.append(op)
      if not terms:
        return False, 1.0, _categorize_error("invalid_payload", f"qutip worker cannot build {mode_normalized} operator")
      hamiltonian = coeff * sum(terms) / max(1, len(terms))

    if hamiltonian is None:
      return False, 1.0, _categorize_error("invalid_payload", f"qutip worker cannot build {mode_normalized} operator")
    if duration <= 0.0:
      return True, 1.0, _categorize_error("invalid_payload", f"qutip worker applied zero-duration {mode_normalized} with identity effect")

    state = _basis_state_from_targets(qutip, n_targets, dim)
    rho0 = state * state.dag()
    U = (hamiltonian * duration).expm()
    rho_t = U * rho0 * U.dag()
    fidelity = float(qutip.metrics.fidelity(rho0, rho_t))
    return True, fidelity, f"qutip worker applied {mode_normalized} with coeff={coeff} for duration={duration}"
  except Exception as exc:
    return False, 1.0, _categorize_error("solver_error", f"qutip worker {mode_normalized} evolution failed: {exc}")


def _calculate_qutip_hamiltonian_fidelity(qutip: Any, operation: dict, duration: float, dim: int = 2) -> tuple[bool, float, str]:
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
  op = _parse_operator_expr(expression, n_targets, qutip, dim)
  if op is None:
    return False, 1.0, _categorize_error("invalid_payload", f"qutip worker cannot parse hamiltonian expr: {expression}")

  try:
    if n_targets <= 0:
      return False, 1.0, _categorize_error("invalid_payload", "qutip worker requires target(s) for hamiltonian")
    if duration <= 0.0:
      return True, 1.0, "qutip worker applied zero-duration hamiltonian with identity effect"

    U = (-1j * op * duration).expm()
    state = _basis_state_from_targets(qutip, n_targets, dim)
    rho0 = state * state.dag()
    rho_t = U * rho0 * U.dag()
    fidelity = float(qutip.metrics.fidelity(rho0, rho_t))
    return True, fidelity, f"qutip worker applied hamiltonian with expr={expression} for duration={duration}"
  except Exception as exc:
    return False, 1.0, _categorize_error("solver_error", f"qutip worker hamiltonian evolution failed: {exc}")


def _calculate_qutip_lindblad_fidelity(qutip: Any, operation: dict, duration: float, dim: int = 2) -> tuple[bool, float, str]:
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
    c_op = _parse_operator_expr(item, n_targets, qutip, dim)
    if c_op is None:
      return False, 1.0, _categorize_error("invalid_payload", f"qutip worker cannot parse lindblad collapse expr: {item}")
    collapse_ops.append(c_op)

  try:
    if duration <= 0.0:
      return True, 1.0, _categorize_error("invalid_payload", "qutip worker applied zero-duration lindblad with identity effect")
    state = _basis_state_from_targets(qutip, n_targets, dim)
    tlist = [0.0, duration]
    result = qutip.mesolve(qutip.qeye(state.shape[0]), state, tlist, collapse_ops, [])
    final_state = result.states[-1] if result.states else state
    fidelity = float(qutip.metrics.fidelity(state, final_state))
    return True, fidelity, f"qutip worker applied lindblad with {len(collapse_ops)} collapse operator(s) for duration={duration}"
  except Exception as exc:
    return False, 1.0, _categorize_error("solver_error", f"qutip worker lindblad evolution failed: {exc}")


def _calculate_qutip_kerr_fidelity(qutip: Any, operation: dict, duration: float, dim: int = 2) -> tuple[bool, float, str]:
  params = operation.get("params", [])
  payload = operation.get("payload", {})
  chi = _as_float(params[0] if params else payload.get("chi", 0.0))
  targets = operation.get("targets", []) if isinstance(operation.get("targets", []), list) else []
  if len(targets) != 1:
    return False, 1.0, _categorize_error("invalid_payload", "qutip worker kerr requires exactly one target")

  try:
    sigma_z = _logical_pauli_in_dim(qutip, dim, "sz")
    if sigma_z is None:
      return False, 1.0, _categorize_error("unsupported_profile", f"qutip worker cannot build kerr operator for dim={dim}")
    n_op = (_identity_in_dim(qutip, dim) - sigma_z) * 0.5
    local_h = chi * (n_op * n_op)
    hamiltonian = _embed_qubit_operator(qutip, local_h, 1, 0, dim=dim)
    if hamiltonian is None:
      return False, 1.0, _categorize_error("invalid_payload", "qutip worker cannot build kerr operator")
    if duration <= 0.0:
      return True, 1.0, _categorize_error("invalid_payload", "qutip worker applied zero-duration kerr with identity effect")
    state = _basis_state_from_targets(qutip, 1, dim)
    rho0 = state * state.dag()
    U = (-1j * hamiltonian * duration).expm()
    rho_t = U * rho0 * U.dag()
    fidelity = float(qutip.metrics.fidelity(rho0, rho_t))
    return True, fidelity, f"qutip worker applied kerr with chi={chi} for duration={duration}"
  except Exception as exc:
    return False, 1.0, _categorize_error("solver_error", f"qutip worker kerr evolution failed: {exc}")


def _calculate_qutip_cross_kerr_fidelity(qutip: Any, operation: dict, duration: float, dim: int = 2) -> tuple[bool, float, str]:
  params = operation.get("params", [])
  payload = operation.get("payload", {})
  chi = _as_float(params[0] if params else payload.get("chi", 0.0))
  targets = operation.get("targets", []) if isinstance(operation.get("targets", []), list) else []
  if len(targets) < 2:
    return False, 1.0, _categorize_error("invalid_payload", "qutip worker cross_kerr requires at least two targets")

  n_targets = len(targets)
  try:
    sigma_z = _logical_pauli_in_dim(qutip, dim, "sz")
    if sigma_z is None:
      return False, 1.0, _categorize_error("unsupported_profile", f"qutip worker cannot build cross_kerr operator for dim={dim}")
    n_op_left = _embed_qubit_operator(qutip, (_identity_in_dim(qutip, dim) - sigma_z) * 0.5, n_targets, 0, dim=dim)
    n_op_right = _embed_qubit_operator(qutip, (_identity_in_dim(qutip, dim) - sigma_z) * 0.5, n_targets, 1, dim=dim)
    if n_op_left is None or n_op_right is None:
      return False, 1.0, _categorize_error("invalid_payload", "qutip worker cannot build cross_kerr operator")
    hamiltonian = chi * n_op_left * n_op_right
    if duration <= 0.0:
      return True, 1.0, _categorize_error("invalid_payload", "qutip worker applied zero-duration cross_kerr with identity effect")
    state = _basis_state_from_targets(qutip, n_targets, dim)
    rho0 = state * state.dag()
    U = (-1j * hamiltonian * duration).expm()
    rho_t = U * rho0 * U.dag()
    fidelity = float(qutip.metrics.fidelity(rho0, rho_t))
    return True, fidelity, f"qutip worker applied cross_kerr with chi={chi} for duration={duration}"
  except Exception as exc:
    return False, 1.0, _categorize_error("solver_error", f"qutip worker cross_kerr evolution failed: {exc}")


def _calculate_qutip_unitary_fidelity(qutip: Any, operation: dict, dim: int = 2) -> tuple[bool, float, str]:
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
    normalized_dim = max(2, int(dim))
    sx = _logical_pauli_in_dim(qutip, normalized_dim, "sx")
    sy = _logical_pauli_in_dim(qutip, normalized_dim, "sy")
    sz = _logical_pauli_in_dim(qutip, normalized_dim, "sz")
    ident = _identity_in_dim(qutip, normalized_dim)
    operator_2d: Any = None
    operator: Any = None
    if gate in {"RX", "RY", "RZ"}:
      if gate == "RX":
        if sx is None:
          return False, 1.0, _categorize_error("invalid_profile", f"qutip worker cannot build RX for dim={dim}")
        operator = (-(1j * angle / 2.0) * sx).expm()
      elif gate == "RY":
        if sy is None:
          return False, 1.0, _categorize_error("invalid_profile", f"qutip worker cannot build RY for dim={dim}")
        operator = (-(1j * angle / 2.0) * sy).expm()
      else:
        if sz is None:
          return False, 1.0, _categorize_error("invalid_profile", f"qutip worker cannot build RZ for dim={dim}")
        operator = (-(1j * angle / 2.0) * sz).expm()
    elif gate in {"CX", "CNOT"}:
      if n_targets != 2:
        return False, 1.0, _categorize_error("unsupported_gate", "qutip worker unsupported CNOT/CX target arity")
      projected_zero = _qubit_subspace_projector(qutip, normalized_dim, 0)
      projected_one = _qubit_subspace_projector(qutip, normalized_dim, 1)
      if projected_zero is None or projected_one is None:
        return False, 1.0, _categorize_error("invalid_payload", "qutip worker cannot build CNOT projectors")
      x_local = _logical_pauli_in_dim(qutip, normalized_dim, "sx")
      if x_local is None:
        return False, 1.0, _categorize_error("invalid_profile", f"qutip worker cannot build CNOT X for dim={dim}")
      control_zero = _embed_qubit_operator(qutip, projected_zero, n_targets, 0, dim=normalized_dim)
      control_one = _embed_qubit_operator(qutip, projected_one, n_targets, 0, dim=normalized_dim)
      x_on_target = _embed_qubit_operator(qutip, x_local, n_targets, 1, dim=normalized_dim)
      control_identity = _embed_qubit_operator(qutip, _identity_in_dim(qutip, normalized_dim), n_targets, 1, dim=normalized_dim)
      if control_zero is None or control_one is None or x_on_target is None or control_identity is None:
        return False, 1.0, _categorize_error("invalid_payload", "qutip worker cannot build CNOT operator")
      operator = control_zero * control_identity + control_one * x_on_target
    elif gate in {"X", "Y", "Z", "H", "S", "SDG", "T", "I", "SQRT_X", "SQRTX"}:
      if gate == "X":
        operator_2d = sx
      elif gate == "Y":
        operator_2d = sy
      elif gate == "Z":
        operator_2d = sz
      elif gate == "H":
        operator_2d = qutip.Qobj([[1, 1], [1, -1]]) / math.sqrt(2)
      elif gate == "S":
        operator_2d = qutip.Qobj([[1, 0], [0, 1j]])
      elif gate == "SDG":
        operator_2d = qutip.Qobj([[1, 0], [0, -1j]])
      elif gate == "T":
        operator_2d = qutip.Qobj([[1, 0], [0, complex(math.cos(math.pi / 4), math.sin(math.pi / 4))]])
      elif gate == "I":
        operator_2d = ident
      elif gate == "SQRT_X":
        if sx is None or ident is None:
          return False, 1.0, _categorize_error("invalid_profile", f"qutip worker cannot build SQRT_X for dim={dim}")
        operator_2d = (sx + ident) / 2 * (1 + 1j)
      else:  # SQRTX
        if sx is None or ident is None:
          return False, 1.0, _categorize_error("invalid_profile", f"qutip worker cannot build SQRT_X† for dim={dim}")
        operator_2d = (sx + ident) / 2 * (1 - 1j)

      if operator_2d is None:
        return False, 1.0, _categorize_error("invalid_profile", f"qutip worker cannot build gate operator for dim={dim}")
      operator = _lift_2d_operator_to_dim(qutip, operator_2d, normalized_dim)
      if operator is None:
        return False, 1.0, _categorize_error("invalid_profile", f"qutip worker cannot lift gate operator for dim={dim}")
    else:
      return False, 1.0, _categorize_error("unsupported_gate", f"qutip worker unsupported unitary: {gate}")

    if n_targets == 1:
      op = _embed_qubit_operator(qutip, operator, 1, 0, dim=normalized_dim)
      if op is None:
        return False, 1.0, _categorize_error("invalid_payload", "qutip worker cannot embed unitary operator")
    else:
      op = operator

    state = _basis_state_from_targets(qutip, n_targets, dim=normalized_dim)
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


def _calculate_qutip_beam_splitter_fidelity(qutip: Any, operation: dict, duration: float, dim: int = 2) -> tuple[bool, float, str]:
  params = operation.get("params", [])
  payload = operation.get("payload", {})
  theta = _as_float(params[0] if len(params) > 0 else payload.get("theta", 0.0))
  targets = operation.get("targets", []) if isinstance(operation.get("targets", []), list) else []
  if len(targets) < 2:
    return False, 1.0, _categorize_error("invalid_payload", "qutip worker beam_splitter requires at least two targets")

  n_targets = len(targets)
  try:
    normalized_dim = max(2, int(dim))
    sx = _embed_qubit_operator(qutip, _logical_pauli_in_dim(qutip, dim, "sx"), n_targets, 0, dim=normalized_dim)
    sx2 = _embed_qubit_operator(qutip, _logical_pauli_in_dim(qutip, dim, "sx"), n_targets, 1, dim=normalized_dim)
    sy = _embed_qubit_operator(qutip, _logical_pauli_in_dim(qutip, dim, "sy"), n_targets, 0, dim=normalized_dim)
    sy2 = _embed_qubit_operator(qutip, _logical_pauli_in_dim(qutip, dim, "sy"), n_targets, 1, dim=normalized_dim)
    if sx is None or sx2 is None or sy is None or sy2 is None:
      return False, 1.0, _categorize_error("invalid_payload", "qutip worker cannot build beam splitter operator")
    hamiltonian = 0.5 * theta * (sx * sx2 + sy * sy2)
    if duration <= 0.0:
      return True, 1.0, _categorize_error("invalid_payload", "qutip worker applied zero-duration beam_splitter with identity effect")
    state = _basis_state_from_targets(qutip, n_targets, dim=normalized_dim)
    rho0 = state * state.dag()
    U = (-1j * hamiltonian * duration).expm()
    rho_t = U * rho0 * U.dag()
    fidelity = float(qutip.metrics.fidelity(rho0, rho_t))
    return True, fidelity, f"qutip worker applied beam_splitter with theta={theta} for duration={duration}"
  except Exception as exc:
    return False, 1.0, _categorize_error("solver_error", f"qutip worker beam_splitter evolution failed: {exc}")


def _handle_unitary(operation: dict, seed: int, dim: int = 2, profile_meta: Optional[dict[str, Any]] = None) -> dict:
  gate = str(operation.get("payload", {}).get("gate", "")).upper()
  n_targets = len(operation.get("targets", []))
  mods = _coerce_qutip_modules()
  if mods is None:
    return _qutip_unavailable_response(f"unitary:{gate}")

  qutip, _ = mods
  success, fidelity, message = _calculate_qutip_unitary_fidelity(qutip=qutip, operation=operation, dim=max(2, int(dim)))
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


def _handle_measurement(operation: dict, seed: int, dim: int = 2, profile_meta: Optional[dict[str, Any]] = None) -> dict:
  basis = str(operation.get("basis", "")).upper()
  if basis not in {"X", "Y", "Z", "BELL"}:
    return _build_response(False, qutip_status="unsupported", message=_categorize_error("unsupported_measurement", f"qutip worker unsupported measurement basis: {basis}"), error_category="unsupported_measurement")
  normalized_dim = max(2, int(dim))
  probability_plus, probability_minus = _measurement_plus_probability(basis, dim=normalized_dim)
  if probability_plus == 0.0 and probability_minus == 0.0:
    return _build_response(False, qutip_status="unsupported", message=_categorize_error("unsupported_measurement", f"qutip worker unsupported measurement basis: {basis}"), error_category="unsupported_measurement")
  rng = _rng(seed, {"kind": "measurement_rng", "basis": basis, "dim": normalized_dim, "probability_plus": probability_plus, "probability_minus": probability_minus})

  measured_plus = rng.random() < probability_plus
  meta = {"measurement_plus_probability": probability_plus, "measurement_minus_probability": probability_minus}
  return _build_response(
    True,
    qutip_status="simulated",
    meta=meta,
    measured_plus=measured_plus,
    message=f"qutip worker simulated measurement in {basis} basis (dim={normalized_dim})",
  )


def _handle_noise(operation: dict, seed: int, dim: int = 2, profile_meta: Optional[dict[str, Any]] = None) -> dict:
  payload = operation.get("payload", {})
  noise_kind = _canonicalize_kind(payload.get("noise_kind", payload.get("kind", "dephasing")))
  leakage_enabled = _resolve_profile_bool(profile_meta, "leakage_enabled", False)
  params = operation.get("params", [])
  params_f = _float_list(params)
  p = 0.0
  if isinstance(params, list) and params:
    p = _as_float(params[0], 0.0)
  elif isinstance(payload, dict) and "p" in payload:
    p = _as_float(payload.get("p", 0.0), 0.0)

  if noise_kind == "loss":
    qubit_lost = _rng(seed, operation).random() < _effective_probability(p, 0.0)
    modules = _coerce_qutip_modules()
    if modules is None:
      return _qutip_unavailable_response("loss")
    qutip, _ = modules
    loss_operation = dict(operation)
    loss_operation["kind"] = "loss"
    success, fidelity, message, _ = _calculate_qutip_loss_fidelity(
        qutip=qutip,
        operation=loss_operation,
        duration=_as_float(operation.get("duration", 0.0)),
        dim=dim,
        leakage_enabled=leakage_enabled,
    )
    if success:
      return _build_response(
          True,
          qutip_status="implemented",
          qubit_lost=qubit_lost,
          fidelity_estimate=fidelity,
          message=message,
      )
    return _build_response(
        False,
        qutip_status="unsupported",
        qubit_lost=qubit_lost,
        fidelity_estimate=_effective_probability(1.0 - p, 1.0),
        message=message if isinstance(message, str) else "qutip worker loss evolution failed",
        error_category="solver_error",
    )

  if noise_kind in {"dephasing", "dephase", "decoherence"}:
    duration = _as_float(operation.get("duration", 0.0))
    mods = _coerce_qutip_modules()
    if mods is None:
      return _qutip_unavailable_response("dephasing/decoherence")

    qutip, _ = mods
    normalized_noise_kind = "decoherence" if noise_kind == "decoherence" else "dephasing"
    success, fidelity, message, _ = _calculate_qutip_noise_fidelity(
        qutip=qutip,
        noise_kind=normalized_noise_kind,
        operation=operation,
        duration=duration,
        dim=dim,
        leakage_enabled=leakage_enabled,
    )
    return _build_response(
        success,
        qutip_status=_normalize_status("implemented" if success else "unsupported"),
        fidelity_estimate=fidelity,
        message=message,
    )

  if noise_kind == "reset":
    modules = _coerce_qutip_modules()
    if modules is None:
      return _qutip_unavailable_response("reset")
    qutip, _ = modules
    success, fidelity, detail = _calculate_qutip_reset_fidelity(
        qutip=qutip,
        operation=operation,
        dim=dim,
        leakage_enabled=leakage_enabled,
    )
    return _build_response(
        success,
        qutip_status="implemented" if success else "unsupported",
        fidelity_estimate=fidelity,
        message=detail,
        error_category=None if success else "solver_error",
    )

  if noise_kind in {"amplitude_damping", "thermal_relaxation", "bitflip", "phaseflip", "depolarizing", "polarization_decoherence"}:
    duration = _as_float(operation.get("duration", 0.0))
    mods = _coerce_qutip_modules()
    if mods is None:
      p = _effective_probability(params_f[0] if params_f else payload.get("p", 0.0))
      return _qutip_unavailable_response(noise_kind)

    qutip, _ = mods
    success, fidelity, message, _meta = _calculate_qutip_noise_fidelity(
        qutip=qutip,
        noise_kind=noise_kind,
        operation=operation,
        duration=duration,
        dim=dim,
        leakage_enabled=leakage_enabled,
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
    "hom_interference",
    "detection",
    "polarization_rotation",
    "polarization_decoherence",
    "delay",
    "timing_jitter",
    "jitter",
    "reset",
}


def _is_advanced_operation_kind(kind: str) -> bool:
  return _canonicalize_kind(kind) in _SUPPORTED_ADVANCED_KINDS


def _run_with_timeout(operation_func, operation: dict, seed: int, timeout_ms: int, profile_meta: Optional[dict[str, Any]] = None, dim: int = 2) -> dict:
  timeout_seconds = timeout_ms / 1000.0
  if timeout_seconds <= 0:
    response = operation_func(operation, seed, dim=dim, profile_meta=profile_meta)
    return _attach_profile_metadata(response, profile_meta)

  output = queue.Queue(maxsize=1)
  start = perf_counter()

  def _worker() -> None:
    try:
      output.put((True, operation_func(operation, seed, dim=dim, profile_meta=profile_meta)))
    except Exception as exc:
      output.put((False, str(exc)))

  thread = threading.Thread(target=_worker, daemon=True)
  thread.start()
  thread.join(timeout_seconds)
  elapsed_ms = int((perf_counter() - start) * 1000)
  if thread.is_alive():
    return _attach_profile_metadata(
      _build_response(
        False,
        qutip_status="unsupported",
        message=_categorize_error("timeout", f"qutip worker timed out after {int(timeout_seconds * 1000)} ms ({elapsed_ms} ms elapsed)"),
        error_category="timeout",
      ),
      profile_meta,
    )

  success, value = output.get_nowait()
  if success:
    return _attach_profile_metadata(value, profile_meta)
  return _attach_profile_metadata(
    _build_response(
      False,
      qutip_status="unsupported",
      message=_categorize_error("solver_error", f"qutip worker internal error: {value}"),
      error_category="solver_error",
    ),
    profile_meta,
  )


def _handle_advanced(operation: dict, seed: int, dim: int = 2, profile_meta: Optional[dict[str, Any]] = None) -> dict:
  kind = _canonicalize_kind(operation.get("kind", ""))
  params = operation.get("params", [])
  payload = operation.get("payload", {})
  duration = _as_float(operation.get("duration", 0.0))
  backend_name = str(payload.get("backend_name", ""))
  params_f = _float_list(params)
  rng = _rng(seed, operation)
  leakage_enabled = _resolve_profile_bool(profile_meta, "leakage_enabled", False)

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
    success, fidelity, detail = _calculate_qutip_kerr_fidelity(qutip=qutip, operation=operation, duration=duration, dim=dim)
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
    success, fidelity, detail = _calculate_qutip_cross_kerr_fidelity(qutip=qutip, operation=operation, duration=duration, dim=dim)
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
    success, fidelity, detail = _calculate_qutip_beam_splitter_fidelity(qutip=qutip, operation=operation, duration=duration, dim=dim)
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
    success, fidelity, detail = _calculate_qutip_phase_fidelity(qutip=qutip, operation=operation, duration=duration, axis="z", dim=dim)
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
    success, fidelity, detail = _calculate_qutip_coupled_phase_fidelity(qutip=qutip, operation=operation, duration=duration, mode=kind, dim=dim)
    return _mark_operation_metrics(
        _build_response(success, qutip_status="implemented" if success else "unsupported", fidelity_estimate=fidelity, message=detail),
        backend_name=backend_name,
        kind=kind,
        duration=duration,
        qutip_status="implemented" if success else "unsupported",
    )
  if kind == "hom_interference":
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
    visibility = _as_float(params_f[0] if params_f else payload.get("visibility", 1.0))
    visibility = max(0.0, min(1.0, visibility))
    theta = math.acos(visibility)
    hom_op = dict(operation)
    hom_op["params"] = [theta]
    success, fidelity, detail = _calculate_qutip_beam_splitter_fidelity(qutip=qutip, operation=hom_op, duration=duration, dim=dim)
    return _mark_operation_metrics(
        _build_response(success, qutip_status="implemented" if success else "unsupported", fidelity_estimate=fidelity, message=f"qutip worker applied hom interference with visibility={visibility}: {detail}"),
        backend_name=backend_name,
        kind=kind,
        duration=duration,
        qutip_status="implemented" if success else "unsupported",
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
        dim=dim,
        leakage_enabled=leakage_enabled,
    )
    return _mark_operation_metrics(
        _build_response(success, qutip_status="implemented" if success else "unsupported", fidelity_estimate=fidelity, message=detail),
        backend_name=backend_name,
        kind=kind,
        duration=duration,
        qutip_status="implemented" if success else "unsupported",
    )
  if kind in {"loss", "attenuation"}:
    p = _effective_probability(params_f[0] if params_f else payload.get("p", payload.get("rate", 0.0)))
    qubit_lost = rng.random() < p
    available, qutip_modules = _qutip_required()
    if not available:
      return _mark_operation_metrics(
          _build_response(True, qutip_status="simulated", qubit_lost=qubit_lost, fidelity_estimate=1.0 - p, message=f"qutip worker simulated channel loss/decoherence with p={p}, backend={backend_name} in {duration}"),
          backend_name=backend_name,
          kind=kind,
          duration=duration,
          qutip_status="simulated",
      )
    qutip, _ = qutip_modules
    success, fidelity, detail, _meta = _calculate_qutip_loss_fidelity(qutip=qutip, operation=operation, duration=duration, dim=dim, leakage_enabled=leakage_enabled)
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
    jitter_std = abs(jitter_std)
    p = _effective_probability(payload.get("p", 0.01 * jitter_std * max(duration, 1.0)))
    jitter_payload = dict(payload)
    jitter_payload.setdefault("noise_kind", "decoherence")
    jitter_payload["p"] = p
    available, qutip_modules = _qutip_required()
    if not available:
      fidelity = _simple_fidelity_decay(0.01 * jitter_std, duration)
      return _mark_operation_metrics(
          _build_response(True, qutip_status="simulated", fidelity_estimate=fidelity, message=f"qutip worker simulated timing jitter with std={jitter_std}, backend={backend_name} in {duration}"),
          backend_name=backend_name,
          kind=kind,
          duration=duration,
          qutip_status="simulated",
      )
    qutip, _ = qutip_modules
    jitter_op = dict(operation)
    jitter_op["kind"] = "decoherence"
    jitter_op["payload"] = jitter_payload
    jitter_op["params"] = [p]
    success, fidelity, detail, _meta = _calculate_qutip_noise_fidelity(
        qutip=qutip,
        noise_kind="decoherence",
        operation=jitter_op,
        duration=duration,
        dim=dim,
        leakage_enabled=leakage_enabled,
    )
    return _mark_operation_metrics(
        _build_response(success, qutip_status="implemented" if success else "unsupported", fidelity_estimate=fidelity, message=f"qutip worker applied timing jitter with p={p}, backend={backend_name}: {detail}"),
        backend_name=backend_name,
        kind=kind,
        duration=duration,
        qutip_status="implemented" if success else "unsupported",
    )
  if kind == "reset":
    available, qutip_modules = _qutip_required()
    if not available:
      return _mark_operation_metrics(
          _build_response(True, qutip_status="simulated", message=f"qutip worker simulated reset in backend={backend_name} during {duration}"),
          backend_name=backend_name,
          kind=kind,
          duration=duration,
          qutip_status="simulated",
      )
    qutip, _ = qutip_modules
    success, fidelity, detail = _calculate_qutip_reset_fidelity(
        qutip=qutip,
        operation=operation,
        dim=dim,
        leakage_enabled=leakage_enabled,
    )
    return _mark_operation_metrics(
        _build_response(
            success,
            qutip_status=_normalize_status("implemented" if success else "unsupported"),
            fidelity_estimate=fidelity if success else 1.0,
            message=detail,
            error_category=None if success else "solver_error",
        ),
        backend_name=backend_name,
        kind=kind,
        duration=duration,
        qutip_status=_normalize_status("implemented" if success else "unsupported"),
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
    available, qutip_modules = _qutip_required()
    if not available:
      p = _effective_probability(payload.get("p", 0.0))
      return _mark_operation_metrics(
          _build_response(True, qutip_status="simulated", fidelity_estimate=1.0 - p, message=f"qutip worker simulated delay of {duration} for {backend_name}"),
          backend_name=backend_name,
          kind=kind,
          duration=duration,
          qutip_status="simulated",
      )
    qutip, _ = qutip_modules
    delay_payload = dict(payload)
    delay_payload.setdefault("noise_kind", "decoherence")
    if "rate" in delay_payload:
      rate = _as_float(delay_payload.get("rate"), 0.0)
      if rate > 0.0:
        delay_payload["p"] = 1.0 - math.exp(-rate * max(duration, 1e-12))
    p = _effective_probability(delay_payload.get("p", 0.0))
    delay_op = dict(operation)
    delay_op["kind"] = "decoherence"
    delay_op["payload"] = delay_payload
    delay_op["params"] = [p]
    success, fidelity, detail, _meta = _calculate_qutip_noise_fidelity(
        qutip=qutip,
        noise_kind="decoherence",
        operation=delay_op,
        duration=duration,
        dim=dim,
        leakage_enabled=leakage_enabled,
    )
    return _mark_operation_metrics(
        _build_response(success, qutip_status="implemented" if success else "unsupported", fidelity_estimate=fidelity, message=detail),
        backend_name=backend_name,
        kind=kind,
        duration=duration,
        qutip_status="implemented" if success else "unsupported",
    )
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
      success, fidelity, detail = _calculate_qutip_hamiltonian_fidelity(qutip=qutip, operation=operation, duration=duration, dim=dim)
    else:
      success, fidelity, detail = _calculate_qutip_lindblad_fidelity(qutip=qutip, operation=operation, duration=duration, dim=dim)
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
  if kind in {"amplitude_damping", "thermal_relaxation", "bitflip", "phaseflip", "depolarizing"}:
    p = _effective_probability(params_f[0] if params_f else payload.get("p", payload.get("rate", 0.0)))
    relaxed = rng.random() < p
    available, qutip_modules = _qutip_required()
    if not available:
      return _mark_operation_metrics(
          _build_response(
              True,
              qutip_status="simulated",
              relaxed_to_ground=relaxed if kind in {"amplitude_damping", "thermal_relaxation"} else False,
              fidelity_estimate=max(0.0, 1.0 - p),
              message=f"qutip worker simulated {kind} with p={p}, backend={backend_name}",
          ),
          backend_name=backend_name,
          kind=kind,
          duration=duration,
          qutip_status="simulated",
      )

    qutip, _ = qutip_modules
    success, fidelity, detail, _meta = _calculate_qutip_noise_fidelity(
        qutip=qutip,
        noise_kind=kind,
        operation=operation,
        duration=duration,
        dim=dim,
        leakage_enabled=leakage_enabled,
    )
    return _mark_operation_metrics(
        _build_response(
            success,
            qutip_status="implemented" if success else "unsupported",
            relaxed_to_ground=relaxed if kind in {"amplitude_damping", "thermal_relaxation"} else False,
            fidelity_estimate=fidelity if success else max(0.0, 1.0 - p),
            message=detail,
        ),
        backend_name=backend_name,
        kind=kind,
        duration=duration,
        qutip_status="implemented" if success else "unsupported",
    )
  if kind == "polarization_decoherence":
    p = _effective_probability(params_f[0] if params_f else payload.get("p", payload.get("rate", 0.0)))
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
        dim=dim,
        leakage_enabled=leakage_enabled,
    )
    return _mark_operation_metrics(
        _build_response(success, qutip_status="implemented" if success else "unsupported", fidelity_estimate=fidelity, message=message),
        backend_name=backend_name,
        kind=kind,
        duration=duration,
        qutip_status="implemented" if success else "unsupported",
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
        dim=dim,
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
    measurement_status = _handle_measurement(operation, seed, dim=dim, profile_meta=profile_meta)
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


def _finalize_response(
    response: dict,
    trace: dict,
    strict: bool,
    kind: str,
    profile_error: Optional[str],
    profile_meta: Optional[dict[str, Any]],
) -> dict:
  response = _attach_profile_metadata(response, profile_meta)
  if profile_error is not None and not response.get("error_category"):
    response["error_category"] = profile_error
  response.update(trace)
  return _apply_strict_simulated_mode(response, strict, kind)


def run_operation(request: dict) -> dict:
  operation = _get_payload(request)
  kind = _canonicalize_kind(operation.get("kind", ""))
  seed = _get_request_seed(request)
  _, profile_meta, profile_error = _resolve_profile(request, kind, operation)
  trace = _trace_fields(request, operation)
  backend_config = request.get("backend_config", {})
  profile_dim = _effective_profile_dim(profile_meta, int((profile_meta or {}).get("dim", 2)))
  # Initialize qutip import cache here so first-time heavy import does not
  # accidentally hit operation-level timeout.
  if _coerce_qutip_modules() is None:
    return _finalize_response(_qutip_unavailable_response(kind), trace, strict=_strict_simulated_enabled(request), kind=kind, profile_error=profile_error, profile_meta=profile_meta)
  timeout_ms_raw = backend_config.get("qutip_worker_timeout_ms", 1000)
  try:
    timeout_ms = int(timeout_ms_raw or 1000)
  except (TypeError, ValueError):
    timeout_ms = 1000
  strict = _strict_simulated_enabled(request)

  limit_error = _validate_backend_limits(request, operation)
  if limit_error is not None:
    return _finalize_response(limit_error, trace, strict, kind, profile_error, profile_meta)

  if kind == "unitary":
    return _finalize_response(
      _run_with_timeout(_handle_unitary, operation, seed, timeout_ms, profile_meta=profile_meta, dim=profile_dim),
      trace,
      strict,
      kind,
      profile_error,
      profile_meta,
    )
  if kind == "measurement":
    return _finalize_response(
      _run_with_timeout(_handle_measurement, operation, seed, timeout_ms, profile_meta=profile_meta, dim=profile_dim),
      trace,
      strict,
      kind,
      profile_error,
      profile_meta,
    )
  if kind == "noise":
    return _finalize_response(
      _run_with_timeout(_handle_noise, operation, seed, timeout_ms, profile_meta=profile_meta, dim=profile_dim),
      trace,
      strict,
      kind,
      profile_error,
      profile_meta,
    )
  if kind == "noop":
    return _finalize_response(_handle_noop(), trace, strict, kind, profile_error, profile_meta)
  if _is_advanced_operation_kind(kind):
    return _finalize_response(
      _run_with_timeout(_handle_advanced, operation, seed, timeout_ms, profile_meta=profile_meta, dim=profile_dim),
      trace,
      strict,
      kind,
      profile_error,
      profile_meta,
    )

  response = _build_response(False, qutip_status="unsupported", message=_categorize_error("unsupported_kind", f"qutip worker unknown operation kind: {kind}"), error_category="unsupported_kind")
  return _finalize_response(response, trace, strict, kind, profile_error, profile_meta)


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
