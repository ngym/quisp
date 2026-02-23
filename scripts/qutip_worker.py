#!/usr/bin/env python3
"""Lightweight qutip command worker used by QuISP.

The worker receives a JSON request and emits a JSON response.
If qutip/qutip_qip/qutip.qip cannot be imported, operations are rejected
with an explicit import-related error.
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


@dataclass
class _ClusterState:
  cluster_id: int
  mode: str
  representation: str
  dim: int
  qubits: list[tuple[int, int, int, int]]
  density_matrix: Any


_QUTIP_CLUSTER_STATES: dict[tuple[int, str], _ClusterState] = {}
_QUTIP_CLUSTER_ID_SIGNATURES: dict[tuple[str, tuple[tuple[int, int, int, int], ...]], int] = {}
_QUTIP_NEXT_CLUSTER_ID = 10_000


_NODE_REPRESENTATION = "node"
_LINK_REPRESENTATION = "link"
_EMISSION_REPRESENTATION = "emission"
_COLLECT_REPRESENTATION = "collect"
_PROPAGATION_REPRESENTATION = "propagation"
_HOM_REPRESENTATION = "hom_interference"


def _canonical_representation(mode: str) -> str:
  if mode == "link":
    return _LINK_REPRESENTATION
  return _NODE_REPRESENTATION


def _advanced_representation(kind: str) -> str:
  normalized = _canonicalize_kind(kind)
  if normalized in {"photon_emission", "emission", "emit", "photon_emit", "photon_emit_event"}:
    return _EMISSION_REPRESENTATION
  if normalized in {"photon_collect", "collect", "fiber_collect", "collect_in_fiber"}:
    return _COLLECT_REPRESENTATION
  if normalized in {"photon_propagation", "propagation", "fiber_propagation", "propagate", "propagate_fiber"}:
    return _PROPAGATION_REPRESENTATION
  if normalized == "hom_interference":
    return _HOM_REPRESENTATION
  return _canonical_representation(normalized)


def _cluster_id_from_signature(mode: str, qubits: list[tuple[int, int, int, int]]) -> int:
  global _QUTIP_NEXT_CLUSTER_ID
  signature = (mode, tuple(qubits))
  cluster_id = _QUTIP_CLUSTER_ID_SIGNATURES.get(signature)
  if cluster_id is None:
    cluster_id = _QUTIP_NEXT_CLUSTER_ID
    _QUTIP_NEXT_CLUSTER_ID += 1
    _QUTIP_CLUSTER_ID_SIGNATURES[signature] = cluster_id
  return cluster_id


def _normalize_cluster_id(value: Any) -> Optional[int]:
  if value is None:
    return None
  if isinstance(value, bool):
    return None
  try:
    candidate = int(value)
  except (TypeError, ValueError):
    return None
  if candidate < 0:
    return None
  return candidate


def _coerce_qubit_key(qubit: Any) -> Optional[tuple[int, int, int, int]]:
  if isinstance(qubit, dict):
    try:
      node_id = int(qubit.get("node_id"))
      qnic_index = int(qubit.get("qnic_index"))
      qnic_type = int(qubit.get("qnic_type"))
      qubit_index = int(qubit.get("qubit_index"))
    except (TypeError, ValueError):
      return None
    return (node_id, qnic_index, qnic_type, qubit_index)

  if isinstance(qubit, (list, tuple)) and len(qubit) == 4:
    try:
      node_id = int(qubit[0])
      qnic_index = int(qubit[1])
      qnic_type = int(qubit[2])
      qubit_index = int(qubit[3])
    except (TypeError, ValueError):
      return None
    return (node_id, qnic_index, qnic_type, qubit_index)

  return None


def _operation_qubit_keys(operation: dict) -> list[tuple[int, int, int, int]]:
  ordered: list[tuple[int, int, int, int]] = []
  seen: set[tuple[int, int, int, int]] = set()

  for key in ("targets", "controls"):
    entries = operation.get(key, [])
    if not isinstance(entries, list):
      continue
    for entry in entries:
      qubit_key = _coerce_qubit_key(entry)
      if qubit_key is None:
        continue
      if qubit_key in seen:
        continue
      seen.add(qubit_key)
      ordered.append(qubit_key)
  return ordered


def _cluster_mode_from_profile(profile_meta: Optional[dict[str, Any]]) -> str:
  if not isinstance(profile_meta, dict):
    return "node"
  mode = profile_meta.get("mode")
  if mode == "link":
    return "link"
  return "node"


def _cluster_key(operation: dict, profile_meta: Optional[dict[str, Any]]) -> Optional[tuple[int, str]]:
  cluster_id = _normalize_cluster_id(operation.get("cluster_id"))
  mode = _cluster_mode_from_profile(profile_meta)
  if cluster_id is None:
    required_qubits = _operation_qubit_keys(operation)
    if not required_qubits:
      return None
    cluster_id = _cluster_id_from_signature(mode, required_qubits)
  return (cluster_id, mode)


def _cluster_keys_for_cluster_id(cluster_id: int) -> list[tuple[int, str]]:
  return [key for key in _QUTIP_CLUSTER_STATES if key[0] == cluster_id]


def _identity_map_from_dim(qutip: Any, source_dim: int, target_dim: int) -> Optional[Any]:
  normalized_source = max(2, int(source_dim))
  normalized_target = max(2, int(target_dim))
  if normalized_source <= 0 or normalized_target <= 0:
    return None
  if normalized_source == normalized_target:
    return qutip.qeye(normalized_source)

  min_dim = min(normalized_source, normalized_target)
  terms = []
  for index in range(min_dim):
    ket_target = qutip.basis(normalized_target, index)
    bra_source = qutip.basis(normalized_source, index).dag()
    terms.append(ket_target * bra_source)
  if not terms:
    return None
  mapped = terms[0]
  for term in terms[1:]:
    mapped += term
  return mapped


def _convert_cluster_state_representation(
    state: _ClusterState,
    target_dim: int,
    target_representation: str,
    qutip: Any,
) -> str:
  target_dim_int = max(2, int(target_dim))
  source_dim = max(2, int(state.dim))
  if state.dim != target_dim_int or state.representation != target_representation:
    if not state.qubits:
      return "cluster state has no qubits"

  if state.dim != target_dim_int:
    mapping_op = _identity_map_from_dim(qutip, source_dim, target_dim_int)
    if mapping_op is None:
      return "cannot create representation map"
    if len(state.qubits) == 1:
      full_mapping = mapping_op
    else:
      full_mapping = qutip.tensor(*([mapping_op] * len(state.qubits)))
    converted = full_mapping * state.density_matrix * full_mapping.dag()
    norm = float(converted.tr())
    if norm <= 0.0:
      return "cluster conversion produced zero trace"
    if abs(norm - 1.0) > 1e-12:
      converted = converted / norm
    state.density_matrix = converted
    state.dim = target_dim_int

  state.representation = target_representation
  return ""


def _ensure_cluster_state(
    operation: dict,
    dim: int,
    profile_meta: Optional[dict[str, Any]],
    qutip: Any,
    *,
    target_representation: Optional[str] = None,
) -> tuple[Optional[_ClusterState], bool, str]:
  key = _cluster_key(operation, profile_meta)
  if key is None:
    return None, False, ""

  normalized_dim = max(2, int(dim))
  cluster_id, mode = key
  requested_representation = target_representation or _canonical_representation(mode)
  state = _QUTIP_CLUSTER_STATES.get(key)
  required_qubits = _operation_qubit_keys(operation)
  if not required_qubits:
    return None, False, ""

  if state is None:
    fallback_state = None
    for candidate_key in _cluster_keys_for_cluster_id(cluster_id):
      if candidate_key == key:
        continue
      if candidate_key[1] != mode:
        continue
      fallback_state = _QUTIP_CLUSTER_STATES.get(candidate_key)
      if fallback_state is not None:
        del _QUTIP_CLUSTER_STATES[candidate_key]
        break

    if fallback_state is not None:
      convert_error = _convert_cluster_state_representation(
          fallback_state,
          target_dim=normalized_dim,
          target_representation=requested_representation,
          qutip=qutip,
      )
      if convert_error:
        return fallback_state, False, convert_error
      fallback_state.cluster_id = cluster_id
      fallback_state.mode = mode
      state = fallback_state
      _QUTIP_CLUSTER_STATES[key] = state

    else:
      base = qutip.basis(normalized_dim, 0)
      rho0 = base * base.dag()
      if len(required_qubits) == 1:
        rho = rho0
      else:
        rho = qutip.tensor(*([rho0] * len(required_qubits)))
      state = _ClusterState(
          cluster_id=cluster_id,
          mode=mode,
          representation=requested_representation,
          dim=normalized_dim,
          qubits=list(required_qubits),
          density_matrix=rho,
      )
      _QUTIP_CLUSTER_STATES[key] = state
      return state, True, ""

  if state is None:
    return None, False, ""

  if state.mode != mode:
    state.mode = mode

  if state.dim != normalized_dim or state.representation != requested_representation:
    convert_error = _convert_cluster_state_representation(
        state,
        target_dim=normalized_dim,
        target_representation=requested_representation,
        qutip=qutip,
    )
    if convert_error:
      return state, True, convert_error

  if state.dim != normalized_dim:
    base = qutip.basis(normalized_dim, 0)
    return state, True, f"cluster dimension mismatch (stored={state.dim}, requested={normalized_dim})"

  base = qutip.basis(normalized_dim, 0) * qutip.basis(normalized_dim, 0).dag()
  for qubit_key in required_qubits:
    if qubit_key in state.qubits:
      continue
    state.qubits.append(qubit_key)
    state.density_matrix = qutip.tensor(state.density_matrix, base)

  return state, False, ""


def _cluster_state_meta(state: Optional[_ClusterState], key: Optional[tuple[int, str]]) -> dict[str, Any]:
  if state is None:
    return {}
  meta = {"cluster_id": state.cluster_id, "cluster_mode": state.mode, "cluster_size": len(state.qubits)}
  meta["cluster_representation"] = state.representation
  if key is not None:
    meta["cluster_key"] = f"{key[0]}:{key[1]}"
  return meta


def _cluster_target_positions(state: _ClusterState, targets: list[tuple[int, int, int, int]]) -> Optional[list[int]]:
  if state is None:
    return None
  positions: list[int] = []
  for target in targets:
    try:
      positions.append(state.qubits.index(target))
    except ValueError:
      return None
  return positions


def _apply_local_operator_to_cluster(state: _ClusterState, local_operator: Any, target_positions: list[int], qutip: Any) -> tuple[bool, Optional[Any]]:
  if state.density_matrix is None:
    return False, None
  if not target_positions:
    return True, qutip.qeye(state.density_matrix.shape[0])

  cluster_size = len(state.qubits)
  if local_operator is None:
    return False, None
  if cluster_size <= 0:
    return False, None
  if any(position < 0 or position >= cluster_size for position in target_positions):
    return False, None

  if len(set(target_positions)) != len(target_positions):
    return False, None

  if cluster_size == len(set(target_positions)):
    full_operator = local_operator
  else:
    ordered_indices = [int(position) for position in target_positions]
    other_indices = [index for index in range(cluster_size) if index not in ordered_indices]
    permutation = ordered_indices + other_indices
    inverse_permutation = [0] * cluster_size
    for new_index, old_index in enumerate(permutation):
      inverse_permutation[old_index] = new_index

    other_dim_count = max(0, cluster_size - len(target_positions))
    if other_dim_count > 0:
      lifted_operator = qutip.tensor(local_operator, *([qutip.qeye(state.dim)] * other_dim_count))
    else:
      lifted_operator = local_operator
    full_operator = lifted_operator.permute(inverse_permutation)
  
  return True, full_operator

  


def _apply_unitary_to_cluster(state: _ClusterState, unitary: Any, targets: list[Any], qutip: Any) -> tuple[bool, Optional[Any]]:
  if unitary is None or state is None:
    return False, None
  target_positions = _cluster_target_positions(state, [_coerce_qubit_key(target) for target in targets] if isinstance(targets, list) else [])
  if target_positions is None:
    return False, None

  success, operator = _apply_local_operator_to_cluster(state, unitary, target_positions, qutip)
  if not success or operator is None:
    return False, None

  evolved = operator * state.density_matrix * operator.dag()
  return True, evolved


def _apply_kraus_to_cluster(
    state: _ClusterState,
    ops: list[Any],
    target_positions: list[int],
    qutip: Any,
) -> tuple[bool, Optional[Any]]:
  if state is None or state.density_matrix is None:
    return False, None
  if not ops:
    return True, state.density_matrix

  embedded: list[Any] = []
  for op in ops:
    success, full_op = _apply_local_operator_to_cluster(state, op, target_positions, qutip)
    if not success or full_op is None:
      return False, None
    embedded.append(full_op)

  rho0 = state.density_matrix
  rho1 = None
  for op in embedded:
    term = op * rho0 * op.dag()
    rho1 = term if rho1 is None else rho1 + term
  if rho1 is None:
    rho1 = rho0
  norm = float(rho1.tr())
  if norm <= 0.0:
    return False, None
  if abs(norm - 1.0) > 1e-12:
    rho1 = rho1 / norm
  return True, rho1


def _build_cluster_noise_ops(
    qutip: Any,
    noise_kind: str,
    operation: dict,
    duration: float,
    dim: int,
    leakage_enabled: bool,
) -> tuple[list[Any], dict[str, Any], Optional[str]]:
  payload = operation.get("payload", {})
  params = operation.get("params", [])
  params_f = _float_list(params)
  p = _effective_probability(params_f[0] if params_f else payload.get("p", payload.get("rate", 0.0)))
  effective_duration = duration if duration > 0.0 else 1.0
  rate = _as_float(payload.get("rate"), _qutip_rate_from_probability(p, effective_duration))
  if rate < 0.0:
    rate = 0.0
  metadata: dict[str, Any] = {"effective_probability": p, "rate": rate}

  normalized_dim = max(2, int(dim))
  sigma_x = _logical_pauli_in_dim(qutip, dim, "sx")
  sigma_y = _logical_pauli_in_dim(qutip, dim, "sy")
  sigma_z = _logical_pauli_in_dim(qutip, dim, "sz")
  sigma_m = _logical_pauli_in_dim(qutip, dim, "sxm")
  sigma_p = _logical_pauli_in_dim(qutip, dim, "sxp")
  identity = qutip.qeye(normalized_dim)
  survival_amp = math.sqrt(max(0.0, 1.0 - max(0.0, min(1.0, p))))

  if noise_kind in {"loss", "amplitude_damping", "thermal_relaxation"}:
    if sigma_m is None or sigma_p is None:
      return [], metadata, _categorize_error("unsupported_profile", "qutip worker cannot build sigma+/sigma- for selected profile")
    local_ops = [survival_amp * identity]
    jump_amp = math.sqrt(max(0.0, min(1.0, p)) / 2.0)
    local_ops.extend([jump_amp * sigma_m, jump_amp * sigma_p])
    if leakage_enabled and normalized_dim > 2 and noise_kind in {"amplitude_damping", "thermal_relaxation", "loss"}:
      leakage = qutip.basis(normalized_dim, 2) * qutip.basis(normalized_dim, 1).dag()
      local_ops.append(jump_amp * math.sqrt(2.0) * leakage)
    return [op for op in local_ops if op is not None], metadata, None

  if noise_kind in {"dephasing", "decoherence", "phaseflip"}:
    if sigma_z is None:
      return [], metadata, _categorize_error("unsupported_profile", "qutip worker cannot build sigma-z for selected profile")
    return [math.sqrt(rate) * sigma_z], metadata, None

  if noise_kind == "bitflip":
    if sigma_x is None:
      return [], metadata, _categorize_error("unsupported_profile", "qutip worker cannot build sigma-x for selected profile")
    return [math.sqrt(rate) * sigma_x], metadata, None

  if noise_kind == "depolarizing":
    if sigma_x is None or sigma_y is None or sigma_z is None:
      return [], metadata, _categorize_error("unsupported_profile", "qutip worker cannot build depolarizing operators for selected profile")
    return [
        math.sqrt(rate / 3.0) * sigma_x if rate else None,
        math.sqrt(rate / 3.0) * sigma_y if rate else None,
        math.sqrt(rate / 3.0) * sigma_z if rate else None,
    ], metadata, None

  if noise_kind == "reset":
    if normalized_dim < 2:
      return [], metadata, _categorize_error("unsupported_profile", f"qutip worker invalid dim for reset: {normalized_dim}")
    basis0 = qutip.basis(normalized_dim, 0)
    basis1 = qutip.basis(normalized_dim, 1)
    local_ops = [basis0 * basis0.dag(), basis0 * basis1.dag()]
    if leakage_enabled and normalized_dim > 2:
      basis2 = qutip.basis(normalized_dim, 2)
      local_ops.append(basis0 * basis2.dag())
    return local_ops, metadata, None

  return [], metadata, _categorize_error("unsupported_noise", f"qutip worker unsupported noise kind: {noise_kind}")


def _remove_cluster_key(cluster_key: tuple[int, str]) -> None:
  if cluster_key in _QUTIP_CLUSTER_STATES:
    del _QUTIP_CLUSTER_STATES[cluster_key]


def _remove_qubit_from_cluster(operation: dict, cluster_key: tuple[int, str]) -> Optional[_ClusterState]:
  state = _QUTIP_CLUSTER_STATES.get(cluster_key)
  if state is None:
    return None

  target_keys = _operation_qubit_keys(operation)
  if not target_keys:
    return state

  target_key = target_keys[0]
  try:
    index = state.qubits.index(target_key)
  except ValueError:
    return state

  if len(state.qubits) <= 1:
    _remove_cluster_key(cluster_key)
    return None

  remaining_indices = [i for i in range(len(state.qubits)) if i != index]
  state.density_matrix = state.density_matrix.ptrace(remaining_indices)
  state.qubits.pop(index)
  return state


def _coerce_profile_int(value: Any, default: int, minimum: int = 1) -> tuple[int, Optional[str]]:
  if value is None:
    return default, None
  if isinstance(value, bool):
    return default, f"invalid integer value: {value}"
  if isinstance(value, int):
    parsed = value
  elif isinstance(value, str):
    stripped = value.strip()
    if not re.fullmatch(r"[+-]?\d+", stripped):
      return default, f"invalid integer value: {value}"
    try:
      parsed = int(stripped)
    except ValueError:
      return default, f"invalid integer value: {value}"
  elif isinstance(value, float):
    if not value.is_integer():
      return default, f"invalid integer value: {value}"
    parsed = int(value)
  else:
    return default, f"invalid integer value: {value}"
  if parsed < minimum:
    return default, f"profile value below minimum ({minimum}): {value}"
  return parsed, None


def _coerce_profile_bool(value: Any, default: bool) -> tuple[bool, Optional[str]]:
  if value is None:
    return default, None
  if isinstance(value, bool):
    return value, None
  if isinstance(value, (int, float)):
    if not float(value).is_integer():
      return default, f"invalid boolean value: {value}"
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
    "photon_emission",
    "emission",
    "photon_collect",
    "collect",
    "photon_propagation",
    "propagation",
    "fiber_propagation",
    "beam_splitter",
    "cross_kerr",
    "decoherence",
    "dephasing",
    "delay",
    "dispersion",
    "attenuation",
    "detection",
    "fock_loss",
    "hamiltonian",
    "hom_interference",
    "jitter",
    "kerr",
    "lindblad",
    "loss",
    "loss_mode",
    "mode_coupling",
    "nonlinear",
    "multiphoton",
    "phase_shift",
    "phase_modulation",
    "self_phase_modulation",
    "cross_phase_modulation",
    "polarization_decoherence",
    "polarization_rotation",
    "photon_number_cutoff",
    "reset",
    "squeezing",
    "source_multiphoton",
    "timing_jitter",
    "two_mode_squeezing",
    "amplitude_damping",
    "thermal_relaxation",
    "bitflip",
    "phaseflip",
    "depolarizing",
}

_SUPPORTED_OPERATION_MODELS = {"unitary", "kraus", "sampled_kraus", "formula", "unsupported"}

_KIND_OPERATION_MODEL: dict[str, str] = {
    "unitary": "unitary",
    "measurement": "sampled_kraus",
    "noise": "kraus",
    "noop": "formula",
    "kerr": "unitary",
    "cross_kerr": "unitary",
    "beam_splitter": "unitary",
    "loss": "kraus",
    "attenuation": "kraus",
    "phase_shift": "unitary",
    "phase_modulation": "unitary",
    "self_phase_modulation": "unitary",
    "cross_phase_modulation": "unitary",
    "decoherence": "kraus",
    "dephasing": "kraus",
    "amplitude_damping": "kraus",
    "thermal_relaxation": "kraus",
    "bitflip": "kraus",
    "phaseflip": "kraus",
    "depolarizing": "kraus",
    "nonlinear": "unitary",
    "polarization_rotation": "unitary",
    "polarization_decoherence": "kraus",
    "mode_coupling": "unitary",
    "loss_mode": "unitary",
    "two_mode_squeezing": "unitary",
    "fock_loss": "formula",
    "photon_number_cutoff": "formula",
    "photon_emission": "formula",
    "photon_collect": "formula",
    "photon_propagation": "formula",
    "emission": "formula",
    "collect": "formula",
    "propagation": "formula",
    "fiber_propagation": "formula",
    "detection": "sampled_kraus",
    "error_channel": "sampled_kraus",
    "delay": "formula",
    "hamiltonian": "unitary",
    "lindblad": "kraus",
    "timing_jitter": "formula",
    "jitter": "formula",
    "dispersion": "formula",
    "multiphoton": "formula",
    "source_multiphoton": "formula",
    "hom_interference": "unitary",
    "squeezing": "formula",
    "reset": "kraus",
}


def _normalize_operation_model(model: Optional[str]) -> str:
  if model is None:
    return "unsupported"
  normalized = str(model).strip().lower()
  if normalized in _SUPPORTED_OPERATION_MODELS:
    return normalized
  return "unsupported"


def _operation_model_for_kind(kind: str) -> str:
  return _normalize_operation_model(_KIND_OPERATION_MODEL.get(_canonicalize_kind(kind), "unsupported"))


def _is_link_kind(kind: str, operation: dict) -> bool:
  normalized = _canonicalize_kind(kind)
  if normalized == "detection":
    targets = operation.get("targets", [])
    if isinstance(targets, list) and len(targets) >= 2:
      return True
  if not isinstance(operation, dict):
    return normalized in _LINK_KIND_SET
  return normalized in _LINK_KIND_SET


def _resolve_cluster_targets(
    operation: dict,
    cluster_state: _ClusterState,
    *,
    exact_targets: Optional[int] = None,
    min_targets: Optional[int] = None,
) -> tuple[list[tuple[int, int, int, int]], list[int], Optional[str]]:
  targets = operation.get("targets", [])
  if not isinstance(targets, list):
    return [], [], _categorize_error("invalid_payload", "qutip worker advanced targets must be a list")

  if exact_targets is not None and len(targets) != exact_targets:
    return [], [], _categorize_error("invalid_payload", f"qutip worker {operation.get('kind', '')} requires exactly {exact_targets} target(s)")

  if min_targets is not None and len(targets) < min_targets:
    return [], [], _categorize_error("invalid_payload", f"qutip worker {operation.get('kind', '')} requires at least {min_targets} target(s)")

  target_keys: list[tuple[int, int, int, int]] = []
  for target in targets:
    target_key = _coerce_qubit_key(target)
    if target_key is None:
      return [], [], _categorize_error("invalid_payload", f"qutip worker invalid target for advanced kind {operation.get('kind', '')}")
    target_keys.append(target_key)

  target_positions = _cluster_target_positions(cluster_state, target_keys)
  if target_positions is None:
    return [], [], _categorize_error("invalid_payload", f"qutip worker cannot resolve advanced target in cluster state for kind {operation.get('kind', '')}")

  return target_keys, target_positions, None


def _resolve_profile(request: dict, kind: str, operation: dict) -> tuple[str, dict[str, Any], str | None]:
  config = request.get("backend_config", {}) if isinstance(request, dict) else {}
  if not isinstance(config, dict):
    config = {}

  has_node_profile = isinstance(config, dict) and "qutip_node_profile" in config
  has_link_profile = isinstance(config, dict) and "qutip_link_profile" in config
  requested_node_profile = _normalize_profile_name(config.get("qutip_node_profile", "standard_light")) if has_node_profile else "standard_light"
  requested_link_profile = _normalize_profile_name(config.get("qutip_link_profile", "standard_light")) if has_link_profile else "standard_light"

  is_link_operation = _is_link_kind(kind, operation)
  requested_profile = requested_link_profile if is_link_operation else requested_node_profile

  if requested_profile == "custom":
    return _resolve_custom_profile(
      requested_profile=requested_profile,
      is_link_operation=is_link_operation,
      parse_profile=config.get("qutip_profile_overrides", None),
    )

  requested_profile_name = requested_profile
  requested_profile_meta = _QUTIP_PROFILE_PRESETS.get(requested_profile)
  default_profile = _QUTIP_PROFILE_PRESETS["standard_light"]
  effective_profile = requested_profile_meta if requested_profile_meta is not None else default_profile

  _, parse_error = _parse_profile_overrides(config.get("qutip_profile_overrides"))
  errors = []
  if parse_error is not None:
    errors.append(parse_error)

  profile_error: str | None = None
  if requested_profile_meta is None:
    errors.append(f"unsupported profile '{requested_profile_name}'")
    profile_error = "invalid_profile"
  elif parse_error is not None:
    profile_error = "invalid_profile"

  mode = "link" if is_link_operation else "node"
  chosen_dim = effective_profile.link_mode_dim if is_link_operation else effective_profile.node_dim

  profile_meta = {
      "profile": requested_profile_name,
      "requested_profile": requested_profile_name,
      "node_dim": int(effective_profile.node_dim),
      "link_dim": int(effective_profile.link_mode_dim),
      "mode": mode,
      "dim": int(chosen_dim),
      "leakage_enabled": bool(effective_profile.leakage_enabled),
      "truncation": int(effective_profile.truncation),
      "errors": " | ".join(errors) if errors else None,
  }

  return requested_profile_name, profile_meta, profile_error


def _resolve_custom_profile(
    requested_profile: str, is_link_operation: bool, parse_profile: Any
) -> tuple[str, dict[str, Any], str | None]:
  base_profile = _QUTIP_PROFILE_PRESETS["standard_light"]
  overrides, parse_error = _parse_profile_overrides(parse_profile)
  errors = []
  profile_error: str | None = None
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
    operation_model: Optional[str] = None,
    meta: Optional[dict[str, Any]] = None,
    **fields,
) -> dict:
  discarded = _as_bool(fields.pop("discarded", False), False)
  photon_lost = _as_bool(fields.pop("photon_lost", False), False)
  discard_reason = fields.pop("discard_reason", "")
  if not discard_reason and discarded:
    discard_reason = "expired"
  response = {
      "success": success,
      "fidelity_estimate": 1.0,
      "discarded": discarded,
      "photon_lost": photon_lost,
      "discard_reason": discard_reason,
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
  response["operation_model"] = _normalize_operation_model(operation_model)
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


def _measurement_projectors_for_basis(qutip: Any, basis: str, dim: int) -> tuple[Any, Any]:
  normalized_dim = max(2, int(dim))
  basis_state_zero = qutip.basis(normalized_dim, 0)
  basis_state_one = qutip.basis(normalized_dim, 1)
  if normalized_dim < 2:
    normalized_dim = 2
    basis_state_zero = qutip.basis(normalized_dim, 0)
    basis_state_one = qutip.basis(normalized_dim, 1)

  normalized_basis = str(basis or "").upper()
  if normalized_basis == "Z":
    plus = basis_state_zero * basis_state_zero.dag()
    minus = basis_state_one * basis_state_one.dag()
    return plus, minus

  if normalized_basis == "X":
    plus = ((basis_state_zero + basis_state_one) / math.sqrt(2))
    minus = ((basis_state_zero - basis_state_one) / math.sqrt(2))
  elif normalized_basis == "Y":
    minus = (basis_state_zero - 1j * basis_state_one) / math.sqrt(2)
    plus = (basis_state_zero + 1j * basis_state_one) / math.sqrt(2)
  else:
    plus = ((basis_state_zero + basis_state_one) / math.sqrt(2))
    minus = ((basis_state_zero - basis_state_one) / math.sqrt(2))
  return plus * plus.dag(), minus * minus.dag()


def _bell_detection_projectors_for_two_targets(qutip: Any, dim: int) -> tuple[Any, Any]:
  normalized_dim = max(2, int(dim))
  basis0 = qutip.basis(normalized_dim, 0)
  basis1 = qutip.basis(normalized_dim, 1)
  psi_plus = (qutip.tensor(basis0, basis1) + qutip.tensor(basis1, basis0)) / math.sqrt(2)
  psi_minus = (qutip.tensor(basis0, basis1) - qutip.tensor(basis1, basis0)) / math.sqrt(2)
  success = (psi_plus * psi_plus.dag()) + (psi_minus * psi_minus.dag())
  identity = qutip.tensor(qutip.qeye(normalized_dim), qutip.qeye(normalized_dim))
  failure = identity - success
  return success, failure


def _onoff_detection_projectors_for_one_target(qutip: Any, dim: int) -> tuple[Any, Any]:
  normalized_dim = max(2, int(dim))
  basis1 = qutip.basis(normalized_dim, 1)
  click = basis1 * basis1.dag()
  no_click = qutip.qeye(normalized_dim) - click
  return click, no_click


def _embed_local_operator(
    state: Any,
    local_operator: Any,
    cluster_state: _ClusterState,
    target_positions: list[int],
    qutip: Any,
) -> tuple[bool, Optional[Any]]:
  if local_operator is None:
    return False, None
  success, operator = _apply_local_operator_to_cluster(cluster_state, local_operator, target_positions, qutip)
  if not success:
    return False, None
  if operator is None:
    return False, None
  return True, operator


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


def _as_int(value: Any, default: int = 0) -> int:
  if isinstance(value, bool):
    return 1 if value else 0
  try:
    return int(value)
  except (TypeError, ValueError):
    pass
  try:
    return int(float(value))
  except (TypeError, ValueError):
    return default


def _resolve_error_profile(value: Any) -> str:
  raw = str(value).strip().lower().replace("-", "_").replace(" ", "_")
  while "__" in raw:
    raw = raw.replace("__", "_")
  aliases = {
      "loss": "loss_channel",
      "losschannel": "loss_channel",
      "flip_channel": "flip_channel",
      "flipchannel": "flip_channel",
      "xerror_channel": "flip_channel",
      "xerror": "flip_channel",
      "bitflip": "flip_channel",
      "phaseflip_channel": "phaseflip_channel",
      "phasechannel": "phaseflip_channel",
      "phase_error_channel": "phaseflip_channel",
      "phase_error": "phaseflip_channel",
      "phaseflip": "phaseflip_channel",
      "z_error_channel": "phaseflip_channel",
      "zerror": "phaseflip_channel",
      "depolarizingchannel": "depolarizing_channel",
      "depolarizing_channel": "depolarizing_channel",
      "depolarize_channel": "depolarizing_channel",
      "errorchannel": "loss_channel",
      "error": "loss_channel",
      "none": "loss_channel",
      "": "loss_channel",
  }
  return aliases.get(raw, raw if raw else "loss_channel")


def _extract_probability(payload: dict[str, Any], keys: tuple[str, ...], fallback: float = 0.0) -> float:
  for key in keys:
    if key in payload:
      return _effective_probability(payload.get(key), fallback)
  return _effective_probability(fallback)


def _compute_channel_loss_probability(payload: dict[str, Any]) -> float:
  channel_loss_rate = _extract_probability(payload, ("legacy_channel_loss_rate", "channel_loss_rate"), 0.0)
  attenuation_db_per_km = _extract_probability(payload, ("attenuation_db_per_km", "channel_attenuation_rate_db_per_km"), 0.0)
  length_km = _as_float(
      payload.get(
          "length_km",
          payload.get("channel_length_km", payload.get("distance_km", payload.get("distance", 0.0))),
      ),
      0.0,
  )
  node_overhead_db = _extract_probability(payload, ("node_io_overhead_db", "channel_node_io_overhead_db"), 0.0)
  node_count = max(0, _as_int(payload.get("node_count", payload.get("channel_node_count", 0)))

  if length_km < 0.0:
    length_km = 0.0

  has_distance_model = (
      attenuation_db_per_km > 0.0 or
      length_km > 0.0 or
      node_overhead_db > 0.0 or
      node_count > 0
  )
  if has_distance_model:
    eta_fiber = (
        10 ** (-(attenuation_db_per_km * max(0.0, length_km)) / 10.0)
        if attenuation_db_per_km > 0.0 and length_km > 0.0 else 1.0
    )
    eta_node = (
        10 ** (-(node_overhead_db * float(node_count)) / 10.0)
        if node_overhead_db > 0.0 and node_count > 0 else 1.0
    )
    eta = _effective_probability(eta_fiber * eta_node, 1.0)
  elif channel_loss_rate > 0.0:
    eta = _effective_probability(1.0 - channel_loss_rate, 1.0)
  else:
    eta = 1.0

  return _effective_probability(1.0 - eta, 0.0)


def _simple_fidelity_decay(rate: float, duration: float) -> float:
  if duration <= 0.0:
    return 1.0
  if rate <= 0.0:
    return 1.0
  decay = max(0.0, 1.0 - rate * duration)
  return min(1.0, max(0.0, decay))


def _mark_operation_metrics(
    response: dict,
    backend_name: str,
    kind: str,
    duration: float,
    operation_model: Optional[str] = None,
) -> dict:
  response.update(
      {
          "backend_name": backend_name,
          "operation_kind": kind,
          "duration": duration,
          "qutip_import_status": _qutip_import_status(),
      }
  )
  if operation_model is None:
    operation_model = _operation_model_for_kind(kind)
  response["operation_model"] = _normalize_operation_model(operation_model or response.get("operation_model"))
  if response["operation_model"] == "unsupported":
    response["operation_model"] = _operation_model_for_kind(kind)
  return response


def _effective_profile_dim(profile_meta: Optional[dict[str, Any]], fallback: int = 2) -> int:
  if not isinstance(profile_meta, dict):
    return fallback
  try:
    dim = int(profile_meta.get("dim", fallback))
  except (TypeError, ValueError):
    return fallback
  if dim < 2:
    return fallback
  return dim


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


def _build_unitary_operator(qutip: Any, operation: dict, dim: int = 2) -> tuple[bool, Optional[Any], str]:
  gate = str(operation.get("payload", {}).get("gate", "")).upper()
  params = operation.get("params", [])
  payload = operation.get("payload", {})
  params_f = _float_list(params)
  targets = operation.get("targets", []) if isinstance(operation.get("targets", []), list) else []
  n_targets = len(targets)
  if n_targets <= 0:
    return False, None, _categorize_error("invalid_payload", "qutip worker unitary requires at least one target")

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
          return False, None, _categorize_error("invalid_profile", f"qutip worker cannot build RX for dim={dim}")
        operator = (-(1j * angle / 2.0) * sx).expm()
      elif gate == "RY":
        if sy is None:
          return False, None, _categorize_error("invalid_profile", f"qutip worker cannot build RY for dim={dim}")
        operator = (-(1j * angle / 2.0) * sy).expm()
      else:
        if sz is None:
          return False, None, _categorize_error("invalid_profile", f"qutip worker cannot build RZ for dim={dim}")
        operator = (-(1j * angle / 2.0) * sz).expm()
    elif gate in {"CX", "CNOT"}:
      if n_targets != 2:
        return False, None, _categorize_error("unsupported_gate", "qutip worker unsupported CNOT/CX target arity")
      projected_zero = _qubit_subspace_projector(qutip, normalized_dim, 0)
      projected_one = _qubit_subspace_projector(qutip, normalized_dim, 1)
      if projected_zero is None or projected_one is None:
        return False, None, _categorize_error("invalid_payload", "qutip worker cannot build CNOT projectors")
      x_local = _logical_pauli_in_dim(qutip, normalized_dim, "sx")
      if x_local is None:
        return False, None, _categorize_error("invalid_profile", f"qutip worker cannot build CNOT X for dim={dim}")
      control_zero = _embed_qubit_operator(qutip, projected_zero, n_targets, 0, dim=normalized_dim)
      control_one = _embed_qubit_operator(qutip, projected_one, n_targets, 0, dim=normalized_dim)
      x_on_target = _embed_qubit_operator(qutip, x_local, n_targets, 1, dim=normalized_dim)
      control_identity = _embed_qubit_operator(qutip, _identity_in_dim(qutip, normalized_dim), n_targets, 1, dim=normalized_dim)
      if control_zero is None or control_one is None or x_on_target is None or control_identity is None:
        return False, None, _categorize_error("invalid_payload", "qutip worker cannot build CNOT operator")
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
          return False, None, _categorize_error("invalid_profile", f"qutip worker cannot build SQRT_X for dim={dim}")
        operator_2d = (sx + ident) / 2 * (1 + 1j)
      else:  # SQRTX
        if sx is None or ident is None:
          return False, None, _categorize_error("invalid_profile", f"qutip worker cannot build SQRT_X† for dim={dim}")
        operator_2d = (sx + ident) / 2 * (1 - 1j)

      if operator_2d is None:
        return False, None, _categorize_error("invalid_profile", f"qutip worker cannot build gate operator for dim={dim}")
      operator = _lift_2d_operator_to_dim(qutip, operator_2d, normalized_dim)
      if operator is None:
        return False, None, _categorize_error("invalid_profile", f"qutip worker cannot lift gate operator for dim={dim}")
    else:
      return False, None, _categorize_error("unsupported_gate", f"qutip worker unsupported unitary: {gate}")

    if n_targets == 1:
      op = _embed_qubit_operator(qutip, operator, 1, 0, dim=normalized_dim)
      if op is None:
        return False, None, _categorize_error("invalid_payload", "qutip worker cannot embed unitary operator")
    else:
      op = operator
    return True, op, f"qutip worker applied unitary {gate} with qutip evolution"
  except Exception as exc:
    return False, None, _categorize_error("solver_error", f"qutip worker unitary evolution failed: {exc}")


def _calculate_qutip_unitary_fidelity(qutip: Any, operation: dict, dim: int = 2) -> tuple[bool, float, str]:
  success, op, message = _build_unitary_operator(qutip=qutip, operation=operation, dim=dim)
  if not success or op is None:
    return False, 1.0, message

  try:
    n_targets = len(operation.get("targets", []) if isinstance(operation.get("targets", []), list) else [])
    if n_targets <= 0:
      return False, 1.0, _categorize_error("invalid_payload", "qutip worker unitary requires at least one target")
    state = _basis_state_from_targets(qutip, n_targets, dim=max(2, int(dim)))
    rho0 = state * state.dag()
    rho_t = op * rho0 * op.dag()
    fidelity = float(qutip.metrics.fidelity(rho0, rho_t))
    return True, fidelity, message
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
  normalized_dim = max(2, int(dim))
  cluster_key = _cluster_key(operation, profile_meta)
  if cluster_key is None:
    return _build_response(False, message=_categorize_error("invalid_cluster", "missing cluster id"), error_category="invalid_cluster")
  cluster_state, _, cluster_error = _ensure_cluster_state(operation, normalized_dim, profile_meta, qutip)
  if cluster_state is None:
    return _build_response(False, message=_categorize_error("invalid_cluster", "missing cluster qubits"), error_category="invalid_cluster")
  if cluster_error:
    return _build_response(False, message=_categorize_error("invalid_profile", cluster_error), error_category="invalid_profile", meta=_cluster_state_meta(cluster_state, cluster_key))

  op_success, op, message = _build_unitary_operator(qutip=qutip, operation=operation, dim=normalized_dim)
  if not op_success or op is None:
    return _build_response(False, message=message, error_category=_extract_error_category(message) or "unsupported_gate", meta=_cluster_state_meta(cluster_state, cluster_key))

  previous_state = cluster_state.density_matrix
  apply_success, evolved_state = _apply_unitary_to_cluster(cluster_state, op, operation.get("targets", []), qutip)
  if not apply_success or evolved_state is None:
    return _build_response(False, message=_categorize_error("invalid_payload", "qutip worker failed to apply unitary on cluster"), error_category="invalid_payload", meta=_cluster_state_meta(cluster_state, cluster_key))
  cluster_state.density_matrix = evolved_state
  fidelity = float(qutip.metrics.fidelity(previous_state, evolved_state)) if previous_state is not None else 1.0
  response = _build_response(
      True,
      fidelity_estimate=fidelity,
      message=message,
      meta=_cluster_state_meta(cluster_state, cluster_key),
  )
  return response


def _handle_measurement(operation: dict, seed: int, dim: int = 2, profile_meta: Optional[dict[str, Any]] = None) -> dict:
  basis = str(operation.get("basis", "")).upper()
  if basis not in {"X", "Y", "Z", "BELL"}:
    return _build_response(False, message=_categorize_error("unsupported_measurement", f"qutip worker unsupported measurement basis: {basis}"), error_category="unsupported_measurement")
  normalized_dim = max(2, int(dim))
  mods = _coerce_qutip_modules()
  if mods is None:
    return _qutip_unavailable_response("measurement")

  qutip, _ = mods
  cluster_key = _cluster_key(operation, profile_meta)
  if cluster_key is None:
    return _build_response(False, message=_categorize_error("invalid_cluster", "missing cluster id"), error_category="invalid_cluster")

  cluster_state, _, cluster_error = _ensure_cluster_state(operation, normalized_dim, profile_meta, qutip)
  if cluster_state is None:
    return _build_response(False, message=_categorize_error("invalid_cluster", "missing cluster qubits"), error_category="invalid_cluster")
  if cluster_error:
    return _build_response(False, message=_categorize_error("invalid_profile", cluster_error), error_category="invalid_profile", meta=_cluster_state_meta(cluster_state, cluster_key))

  operation_targets = operation.get("targets", [])
  if len(operation_targets) != 1:
    return _build_response(False, message=_categorize_error("invalid_payload", "qutip worker measurement requires exactly one target in cluster mode"), error_category="invalid_payload", meta=_cluster_state_meta(cluster_state, cluster_key))
  target = _coerce_qubit_key(operation_targets[0])
  if target is None:
    return _build_response(False, message=_categorize_error("invalid_payload", "qutip worker invalid measurement target"), error_category="invalid_payload", meta=_cluster_state_meta(cluster_state, cluster_key))

  target_positions = _cluster_target_positions(cluster_state, [target])
  if target_positions is None:
    return _build_response(False, message=_categorize_error("invalid_payload", "qutip worker cannot resolve measurement target in cluster state"), error_category="invalid_payload", meta=_cluster_state_meta(cluster_state, cluster_key))

  plus_projector_local, minus_projector_local = _measurement_projectors_for_basis(qutip, basis, normalized_dim)
  plus_success, plus_full = _embed_local_operator(cluster_state.density_matrix, plus_projector_local, cluster_state, target_positions, qutip)
  minus_success, minus_full = _embed_local_operator(cluster_state.density_matrix, minus_projector_local, cluster_state, target_positions, qutip)
  if not plus_success or not minus_success or plus_full is None or minus_full is None:
    return _build_response(False, message=_categorize_error("invalid_payload", "qutip worker failed to build measurement projector"), error_category="invalid_payload", meta=_cluster_state_meta(cluster_state, cluster_key))

  rho = cluster_state.density_matrix
  probability_plus = float((plus_full * rho * plus_full.dag()).tr())
  probability_minus = float((minus_full * rho * minus_full.dag()).tr())
  total_probability = max(0.0, probability_plus + probability_minus)
  if total_probability <= 0.0:
    return _build_response(False, message=_categorize_error("invalid_payload", "qutip worker measured zero total probability"), error_category="invalid_payload", meta=_cluster_state_meta(cluster_state, cluster_key))

  probability_plus = max(0.0, min(1.0, probability_plus / total_probability))
  probability_minus = 1.0 - probability_plus
  rng = _rng(seed, {"kind": "measurement_rng", "basis": basis, "dim": normalized_dim, "probability_plus": probability_plus})
  measured_plus = rng.random() < probability_plus
  collapsed = plus_full * rho * plus_full.dag() if measured_plus else minus_full * rho * minus_full.dag()
  collapsed_norm = float((collapsed * collapsed.dag()).tr())
  if collapsed_norm <= 0.0:
    return _build_response(False, message=_categorize_error("invalid_payload", "qutip worker collapsed measurement state has zero norm"), error_category="invalid_payload", meta=_cluster_state_meta(cluster_state, cluster_key))
  cluster_state.density_matrix = collapsed / collapsed_norm
  branch_probability = probability_plus if measured_plus else probability_minus
  remaining_state = _remove_qubit_from_cluster(operation, cluster_key)
  meta = {
      "measurement_plus_probability": probability_plus,
      "measurement_minus_probability": probability_minus,
  }
  meta.update(_cluster_state_meta(cluster_state if remaining_state is not None else None, cluster_key))
  return _build_response(
      True,
      measured_plus=measured_plus,
      branch_probability=branch_probability,
      fidelity_estimate=collapsed_norm,
      meta=meta,
      message=f"qutip worker measured {basis} in cluster {cluster_key}",
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
  normalized_dim = max(2, int(dim))
  cluster_key = _cluster_key(operation, profile_meta)
  if cluster_key is None:
    return _build_response(False, message=_categorize_error("invalid_cluster", "missing cluster id"), error_category="invalid_cluster")
  mods = _coerce_qutip_modules()
  if mods is None:
    return _qutip_unavailable_response(f"noise:{noise_kind}")
  qutip, _ = mods
  cluster_state, _, cluster_error = _ensure_cluster_state(operation, normalized_dim, profile_meta, qutip)
  if cluster_state is None:
    return _build_response(False, message=_categorize_error("invalid_cluster", "missing cluster qubits"), error_category="invalid_cluster")
  if cluster_error:
    return _build_response(False, message=_categorize_error("invalid_profile", cluster_error), error_category="invalid_profile", meta=_cluster_state_meta(cluster_state, cluster_key))

  operation_targets = operation.get("targets", [])
  if len(operation_targets) != 1:
    return _build_response(False, message=_categorize_error("invalid_payload", "qutip worker noise requires exactly one target in cluster mode"), error_category="invalid_payload", meta=_cluster_state_meta(cluster_state, cluster_key))

  target = _coerce_qubit_key(operation_targets[0])
  if target is None:
    return _build_response(False, message=_categorize_error("invalid_payload", "qutip worker invalid noise target"), error_category="invalid_payload", meta=_cluster_state_meta(cluster_state, cluster_key))

  target_positions = _cluster_target_positions(cluster_state, [target])
  if target_positions is None:
    return _build_response(False, message=_categorize_error("invalid_payload", "qutip worker cannot resolve noise target in cluster state"), error_category="invalid_payload", meta=_cluster_state_meta(cluster_state, cluster_key))

  photon_lost = _rng(seed, operation).random() < _effective_probability(p, 0.0)
  if noise_kind == "loss":
    ops, meta, build_error = _build_cluster_noise_ops(
        qutip=qutip,
        noise_kind=noise_kind,
        operation=operation,
        duration=_as_float(operation.get("duration", 0.0)),
        dim=normalized_dim,
        leakage_enabled=leakage_enabled,
    )
    if build_error is not None:
      return _build_response(False, message=build_error, error_category=_extract_error_category(build_error) or "unsupported_noise", meta=_cluster_state_meta(cluster_state, cluster_key))
    success_apply, evolved_state = _apply_kraus_to_cluster(cluster_state, ops, target_positions, qutip)
    if not success_apply or evolved_state is None:
      return _build_response(False, message=_categorize_error("invalid_payload", "qutip worker failed to apply loss in cluster"), error_category="invalid_payload", meta=_cluster_state_meta(cluster_state, cluster_key))
    previous_state = cluster_state.density_matrix
    cluster_state.density_matrix = evolved_state
    try:
      fidelity = float(qutip.metrics.fidelity(previous_state, evolved_state))
    except Exception:
      fidelity = _effective_probability(1.0 - _effective_probability(p, 0.0), 1.0)
    response = _build_response(
        True,
        discarded=False,
        photon_lost=photon_lost,
        discard_reason="photon_loss" if photon_lost else "",
        fidelity_estimate=fidelity,
        message=f"qutip worker applied loss in cluster with p={_effective_probability(p, 0.0)}, mode=cluster",
        meta=meta,
    )
    response = _attach_profile_metadata(response, profile_meta)
    response_meta = response.get("meta")
    if isinstance(response_meta, dict):
      response_meta.update(_cluster_state_meta(cluster_state, cluster_key))
    return response

  if noise_kind in {"dephasing", "dephase", "decoherence", "amplitude_damping", "thermal_relaxation", "bitflip", "phaseflip", "depolarizing", "reset", "polarization_decoherence"}:
    canonical_noise_kind = "decoherence" if noise_kind == "decoherence" else noise_kind
    if canonical_noise_kind == "dephase":
      canonical_noise_kind = "dephasing"
    ops, meta, build_error = _build_cluster_noise_ops(
      qutip=qutip,
      noise_kind=canonical_noise_kind if canonical_noise_kind in {"decoherence", "dephasing", "amplitude_damping", "thermal_relaxation", "bitflip", "phaseflip", "depolarizing", "reset", "loss"} else noise_kind,
      operation=operation,
      duration=_as_float(operation.get("duration", 0.0)),
      dim=normalized_dim,
      leakage_enabled=leakage_enabled,
    )
    if build_error is not None:
      return _build_response(False, message=build_error, error_category=_extract_error_category(build_error) or "unsupported_noise", meta=_cluster_state_meta(cluster_state, cluster_key))
    success_apply, evolved_state = _apply_kraus_to_cluster(cluster_state, ops, target_positions, qutip)
    if not success_apply or evolved_state is None:
      return _build_response(False, message=_categorize_error("invalid_payload", "qutip worker failed to apply noise in cluster"), error_category="invalid_payload", meta=_cluster_state_meta(cluster_state, cluster_key))
    previous_state = cluster_state.density_matrix
    cluster_state.density_matrix = evolved_state
    try:
      fidelity = float(qutip.metrics.fidelity(previous_state, evolved_state))
    except Exception:
      fidelity = 1.0
    response = _build_response(
      True,
      fidelity_estimate=fidelity,
      message=f"qutip worker applied {canonical_noise_kind} in cluster mode",
    )
    response = _attach_profile_metadata(response, profile_meta)
    response_meta = response.get("meta")
    if isinstance(response_meta, dict):
      response_meta.update(meta)
      response_meta.update(_cluster_state_meta(cluster_state, cluster_key))
    return response

  if noise_kind in {"timing_jitter", "jitter", "delay"}:
    return _build_response(False, message=_categorize_error("unsupported_noise", f"qutip worker unsupported noise kind in cluster mode: {noise_kind}"), error_category="unsupported_noise", meta=_cluster_state_meta(cluster_state, cluster_key))

  return _build_response(False, message=_categorize_error("unsupported_noise", f"qutip worker unsupported noise kind in cluster mode: {noise_kind}"), error_category="unsupported_noise", meta=_cluster_state_meta(cluster_state, cluster_key))


def _handle_error_channel(operation: dict, seed: int, dim: int = 2, profile_meta: Optional[dict[str, Any]] = None) -> dict:
  payload = operation.get("payload", {})
  profile = _resolve_error_profile(payload.get("channel_profile", operation.get("kind", "")))
  normalized_dim = max(2, int(dim))
  cluster_key = _cluster_key(operation, profile_meta)
  if cluster_key is None:
    return _build_response(False, message=_categorize_error("invalid_cluster", "missing cluster id"), error_category="invalid_cluster")

  qutip_modules = _coerce_qutip_modules()
  if qutip_modules is None:
    return _qutip_unavailable_response("error_channel")
  qutip, _ = qutip_modules
  cluster_state, _, cluster_error = _ensure_cluster_state(operation, normalized_dim, profile_meta, qutip)
  if cluster_state is None:
    return _build_response(False, message=_categorize_error("invalid_cluster", "missing cluster qubits"), error_category="invalid_cluster")
  if cluster_error:
    return _build_response(False, message=_categorize_error("invalid_profile", cluster_error), error_category="invalid_profile", meta=_cluster_state_meta(cluster_state, cluster_key))

  operation_targets, target_positions, resolution_error = _resolve_cluster_targets(operation, cluster_state, min_targets=1)
  if resolution_error is not None:
    return _build_response(False, message=_categorize_error("invalid_payload", resolution_error), error_category="invalid_payload", meta=_cluster_state_meta(cluster_state, cluster_key))
  if not operation_targets or not target_positions:
    return _build_response(False, message=_categorize_error("invalid_payload", "qutip worker error_channel requires at least one target"), error_category="invalid_payload", meta=_cluster_state_meta(cluster_state, cluster_key))

  if len(operation_targets) != len(target_positions):
    return _build_response(False, message=_categorize_error("invalid_payload", "qutip worker error_channel target mismatch"), error_category="invalid_payload", meta=_cluster_state_meta(cluster_state, cluster_key))

  def _apply_ops_to_targets(noise_kind: str, operation_probability: float, seed_probability_key: str, discard_reason: str = "") -> dict:
    temp_payload = dict(payload)
    temp_payload["p"] = operation_probability
    temp_operation = {
        "payload": temp_payload,
        "params": [operation_probability],
    }
    if len(target_positions) == 0:
      return _build_response(True, message="qutip worker error_channel skipped because no active target", classical_payload={"channel_profile": profile, "probability": operation_probability})

    previous_state = cluster_state.density_matrix
    loss_events = None
    if seed_probability_key == "loss":
      loss_events = []
      for target_index, target_position in enumerate(target_positions):
        target_rng = _rng(seed, {"kind": "error_channel_loss", "target": target_position, "index": target_index, "p": operation_probability})
        loss_events.append(target_rng.random() < _effective_probability(operation_probability, 0.0))

    has_photon_lost = False
    for target_index, target_position in enumerate(target_positions):
      if seed_probability_key == "loss":
        if not loss_events[target_index]:
          continue
        has_photon_lost = True

      ops, _, build_error = _build_cluster_noise_ops(
        qutip=qutip,
        noise_kind=noise_kind,
        operation=temp_operation,
        duration=0.0,
        dim=normalized_dim,
        leakage_enabled=False,
      )
      if build_error is not None:
        return _build_response(False, message=build_error, error_category=_extract_error_category(build_error) or "unsupported_noise", meta=_cluster_state_meta(cluster_state, cluster_key))
      success_apply, evolved_state = _apply_kraus_to_cluster(cluster_state, ops, [target_position], qutip)
      if not success_apply or evolved_state is None:
        return _build_response(False, message=_categorize_error("invalid_payload", "qutip worker failed to apply error_channel noise"), error_category="invalid_payload", meta=_cluster_state_meta(cluster_state, cluster_key))
      cluster_state.density_matrix = evolved_state

    try:
      fidelity = float(qutip.metrics.fidelity(previous_state, cluster_state.density_matrix))
    except Exception:
      fidelity = 1.0
    return _build_response(
      True,
      fidelity_estimate=fidelity,
      discarded=False,
      photon_lost=has_photon_lost,
      discard_reason=discard_reason if has_photon_lost else "",
      outcome_pattern="none" if has_photon_lost else "pass",
      detection_click_count=0,
      detector_histogram=[0, 0, 0, 0],
      classical_payload={"channel_profile": profile, "probability": operation_probability},
      message=f"qutip worker applied error_channel {noise_kind} with p={_effective_probability(operation_probability, 0.0)}",
      meta=_cluster_state_meta(cluster_state, cluster_key),
    )

  if profile in {"loss_channel", "loss", "losschannel"}:
    loss_probability = _compute_channel_loss_probability(payload)
    loss_probability = _effective_probability(loss_probability, 0.0)
    return _apply_ops_to_targets("loss", loss_probability, "loss", "photon_loss")

  if profile in {"flip_channel", "bitflip", "xerror", "x_error_channel"}:
    flip_probability = _extract_probability(payload, ("channel_x_error_rate", "legacy_channel_x_error_rate", "x_error_rate", "flip_probability", "p"), 0.0)
    return _apply_ops_to_targets("bitflip", flip_probability, "bitflip")

  if profile in {"phaseflip_channel", "phaseflip", "z_error_channel", "zerror"}:
    phase_probability = _extract_probability(payload, ("channel_z_error_rate", "legacy_channel_z_error_rate", "z_error_rate", "phase_probability", "p"), 0.0)
    return _apply_ops_to_targets("phaseflip", phase_probability, "phaseflip")

  if profile in {"depolarizing_channel", "depolarizing"}:
    depolarizing_probability = _extract_probability(payload, ("channel_depolarizing_rate", "channel_error_rate", "depolarizing_probability", "p"), 0.0)
    return _apply_ops_to_targets("depolarizing", depolarizing_probability, "depolarizing")

  return _build_response(
    False,
    message=_categorize_error("unsupported_profile", f"qutip worker unsupported error_channel profile: {profile}"),
    error_category="unsupported_profile",
    meta=_cluster_state_meta(cluster_state, cluster_key),
  )


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
        error_category="unsupported_backend_class",
    )

  max_register_qubits = config.get("qutip_max_register_qubits")
  if max_register_qubits is not None:
    try:
      max_register_qubits = int(max_register_qubits)
    except (TypeError, ValueError):
      return _build_response(
          False,
          message=_categorize_error("invalid_payload", "invalid qutip_max_register_qubits payload value"),
          error_category="invalid_payload",
      )
    if max_register_qubits > 0:
      unique_qubits = _collect_unique_qubits(operation)
      if len(unique_qubits) > max_register_qubits:
        return _build_response(
            False,
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
          message=_categorize_error("invalid_payload", "invalid qutip_max_hilbert_dim payload value"),
          error_category="invalid_payload",
      )
    max_hilbert_dim = None
  if max_hilbert_dim is not None and max_hilbert_dim > 0:
    ancillary_modes = operation.get("ancillary_modes", [])
    if isinstance(ancillary_modes, list) and len(ancillary_modes) > max_hilbert_dim:
      return _build_response(
          False,
          message=f"qutip backend config limit exceeded: ancillary_modes={len(ancillary_modes)} > {max_hilbert_dim}",
          error_category="exceeded_limit",
      )
  return None


def _trace_fields(request: dict, operation: dict) -> dict:
  config = request.get("backend_config", {}) if isinstance(request, dict) else {}
  backend_name = str(request.get("backend_type", "qutip") if isinstance(request, dict) else "qutip")
  backend_class = _normalized_backend_class(str(config.get("qutip_backend_class", backend_name)))
  time = request.get("time", 0.0)
  cluster_id = operation.get("cluster_id", -1)
  cluster_event = operation.get("cluster_event", "")
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
      "cluster_id": int(cluster_id) if isinstance(cluster_id, int) else -1,
      "cluster_event": str(cluster_event) if cluster_event is not None else "",
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
      "error_channel": "error_channel",
      "errorchannel": "error_channel",
      "error": "error_channel",
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
      "emit": "photon_emission",
      "photonemission": "photon_emission",
      "photon_emission": "photon_emission",
      "collect": "photon_collect",
      "photoncollect": "photon_collect",
      "photon_collect": "photon_collect",
      "collect_in_fiber": "photon_collect",
      "fiber_collect": "photon_collect",
      "propagation": "photon_propagation",
      "photonpropagation": "photon_propagation",
      "photon_propagation": "photon_propagation",
      "fiber_propagation": "photon_propagation",
      "propagate": "photon_propagation",
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
    "photon_emission",
    "emission",
    "photon_collect",
    "collect",
    "photon_propagation",
    "propagation",
    "fiber_propagation",
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
    "timing_jitter",
    "jitter",
    "dispersion",
    "multiphoton",
    "source_multiphoton",
    "hom_interference",
    "squeezing",
    "reset",
}

SUPPORTED_ADVANCED_CLUSTER_HANDLERS = {kind: "cluster" for kind in sorted(_SUPPORTED_ADVANCED_KINDS)}


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
      message=_categorize_error("solver_error", f"qutip worker internal error: {value}"),
      error_category="solver_error",
    ),
    profile_meta,
  )


def _handle_advanced(operation: dict, seed: int, dim: int = 2, profile_meta: Optional[dict[str, Any]] = None) -> dict:
  kind = _canonicalize_kind(operation.get("kind", ""))
  params = operation.get("params", [])
  params_f = _float_list(params)
  payload = operation.get("payload", {})
  duration = _as_float(operation.get("duration", 0.0))
  backend_name = str(payload.get("backend_name", ""))
  requested_representation = _advanced_representation(kind)
  transition_from = None

  cluster_key = _cluster_key(operation, profile_meta)
  if cluster_key is None:
    return _build_response(
      False,
      message=_categorize_error("invalid_cluster", "missing cluster id"),
      error_category="invalid_cluster",
    )

  qutip_modules = _coerce_qutip_modules()
  if qutip_modules is None:
    return _qutip_unavailable_response(f"advanced:{kind}")
  qutip, _ = qutip_modules

  normalized_dim = max(2, int(dim))
  if cluster_key in _QUTIP_CLUSTER_STATES:
    existing_state = _QUTIP_CLUSTER_STATES.get(cluster_key)
    if existing_state is not None:
      transition_from = f"{existing_state.mode}/{existing_state.representation}"
  cluster_state, _, cluster_error = _ensure_cluster_state(
      operation,
      normalized_dim,
      profile_meta,
      qutip,
      target_representation=requested_representation,
  )
  if cluster_state is None:
    return _build_response(False, message=_categorize_error("invalid_cluster", "missing cluster qubits"), error_category="invalid_cluster")
  if cluster_error:
    return _build_response(False, message=_categorize_error("invalid_profile", cluster_error), error_category="invalid_profile", meta=_cluster_state_meta(cluster_state, cluster_key))
  transition_to = f"{cluster_state.mode}/{cluster_state.representation}"

  leakage_enabled = _resolve_profile_bool(profile_meta, "leakage_enabled", False)

  def _finalize(response: dict) -> dict:
    response = _attach_profile_metadata(response, profile_meta)
    response_meta = response.get("meta")
    if not isinstance(response_meta, dict):
      response_meta = {}
    response_meta.update(_cluster_state_meta(cluster_state, cluster_key))
    if transition_from is not None and transition_from != transition_to:
      response_meta["cluster_representation_transition"] = f"{transition_from}->{transition_to}"
    response["meta"] = response_meta
    return _mark_operation_metrics(response, backend_name=backend_name, kind=kind, duration=duration)

  def _invalid_payload(message: str) -> dict:
    return _finalize(
      _build_response(
        False,
        message=_categorize_error("invalid_payload", message),
        error_category="invalid_payload",
        meta=_cluster_state_meta(cluster_state, cluster_key),
      ),
    )

  def _resolve_targets(*, exact_targets: Optional[int] = None, min_targets: Optional[int] = None) -> tuple[list[tuple[int, int, int, int]], list[int], Optional[str]]:
    return _resolve_cluster_targets(
      operation,
      cluster_state,
      exact_targets=exact_targets,
      min_targets=min_targets,
    )

  def _apply_cluster_unitary(operation_targets: list[tuple[int, int, int, int]], unitary: Any, message: str) -> dict:
    previous_state = cluster_state.density_matrix
    success, evolved = _apply_unitary_to_cluster(cluster_state, unitary, operation_targets, qutip)
    if not success or evolved is None:
      return _finalize(
        _build_response(
          False,
          message=_categorize_error("invalid_payload", "qutip worker failed to apply advanced operation on cluster"),
          error_category="invalid_payload",
          meta=_cluster_state_meta(cluster_state, cluster_key),
        ),
      )
    cluster_state.density_matrix = evolved
    try:
      fidelity = float(qutip.metrics.fidelity(previous_state, evolved))
    except Exception:
      fidelity = 1.0
    return _finalize(_build_response(True, fidelity_estimate=fidelity, message=message))

  def _apply_cluster_kraus(
    noise_kind_for_ops: str,
    operation_for_ops: dict,
    operation_targets: list[tuple[int, int, int, int]],
    target_positions: list[int],
    message: Optional[str] = None,
  ) -> dict:
    ops, meta, build_error = _build_cluster_noise_ops(
      qutip=qutip,
      noise_kind=noise_kind_for_ops,
      operation=operation_for_ops,
      duration=duration,
      dim=normalized_dim,
      leakage_enabled=leakage_enabled,
    )
    if build_error is not None:
      return _finalize(
        _build_response(
          False,
          message=build_error,
          error_category=_extract_error_category(build_error) or "unsupported_noise",
          meta=_cluster_state_meta(cluster_state, cluster_key),
        ),
      )

    previous_state = cluster_state.density_matrix
    success_apply, evolved_state = _apply_kraus_to_cluster(cluster_state, ops, target_positions, qutip)
    if not success_apply or evolved_state is None:
      return _invalid_payload("qutip worker failed to apply advanced operation on cluster")
    cluster_state.density_matrix = evolved_state
    try:
      fidelity = float(qutip.metrics.fidelity(previous_state, evolved_state))
    except Exception:
      fidelity = 1.0

    response = _build_response(True, fidelity_estimate=fidelity, message=message or f"qutip worker applied {kind} in cluster mode")
    if isinstance(meta, dict):
      response_meta = dict(response.get("meta") or {})
      response_meta.update(meta)
      response["meta"] = response_meta
    return _finalize(response)

  def _handle_unitary_kind(kind_for_handler: str) -> Optional[dict]:
    min_targets = 1
    if kind_for_handler in {
        "cross_kerr",
        "beam_splitter",
        "hom_interference",
        "cross_phase_modulation",
        "mode_coupling",
        "two_mode_squeezing",
    }:
      min_targets = 2

    if min_targets > 1:
      operation_targets, target_positions, error = _resolve_targets(min_targets=min_targets)
    else:
      operation_targets, target_positions, error = _resolve_targets(exact_targets=1)

    if error is not None:
      return _invalid_payload(error)

    n_targets = len(operation_targets)
    def _cluster_identity_for_targets() -> Any:
      if n_targets <= 1:
        return _identity_in_dim(qutip, normalized_dim)
      return qutip.tensor(*([_identity_in_dim(qutip, normalized_dim)] * n_targets))

    if kind_for_handler == "kerr":
      params_value = _as_float(params_f[0] if params_f else payload.get("chi", payload.get("theta", 0.0)))
      sigma_z = _logical_pauli_in_dim(qutip, normalized_dim, "sz")
      if sigma_z is None:
        return _invalid_payload(f"qutip worker cannot build kerr operator for dim={normalized_dim}")
      n_op = (_identity_in_dim(qutip, normalized_dim) - sigma_z) * 0.5
      local_h = n_op * n_op * params_value
      unitary = (-1j * local_h * duration).expm() if duration > 0.0 else _identity_in_dim(qutip, normalized_dim ** n_targets)
      return _apply_cluster_unitary(operation_targets, unitary, f"qutip worker applied {kind_for_handler} with chi={params_value} for duration={duration}")

    if kind_for_handler == "cross_kerr":
      if n_targets < 2:
        return _invalid_payload("qutip worker cross_kerr requires at least two targets")
      params_value = _as_float(params_f[0] if params_f else payload.get("chi", payload.get("theta", 0.0)))
      sigma_z = _logical_pauli_in_dim(qutip, normalized_dim, "sz")
      if sigma_z is None:
        return _invalid_payload(f"qutip worker cannot build cross_kerr operator for dim={normalized_dim}")
      n_op_left = _embed_qubit_operator(qutip, (_identity_in_dim(qutip, normalized_dim) - sigma_z) * 0.5, n_targets, 0, dim=normalized_dim)
      n_op_right = _embed_qubit_operator(qutip, (_identity_in_dim(qutip, normalized_dim) - sigma_z) * 0.5, n_targets, 1, dim=normalized_dim)
      if n_op_left is None or n_op_right is None:
        return _invalid_payload("qutip worker cannot build cross_kerr operator")
      local_h = params_value * n_op_left * n_op_right
      unitary = (-1j * local_h * duration).expm() if duration > 0.0 else _cluster_identity_for_targets()
      return _apply_cluster_unitary(operation_targets, unitary, f"qutip worker applied cross_kerr with chi={params_value} for duration={duration}")

    if kind_for_handler in {"beam_splitter", "hom_interference", "mode_coupling", "two_mode_squeezing"}:
      coupling_raw = payload.get("theta", payload.get("coupling", payload.get("strength", 0.0)))
      coupling_or_angle = _as_float(params_f[0] if params_f else coupling_raw)
      if kind_for_handler in {"hom_interference", "mode_coupling"} and kind_for_handler != "beam_splitter":
        if kind_for_handler == "hom_interference":
          visibility = _as_float(payload.get("visibility", coupling_or_angle), coupling_or_angle)
          visibility = max(0.0, min(1.0, visibility))
          coupling_or_angle = math.acos(visibility)

      sx = _logical_pauli_in_dim(qutip, normalized_dim, "sx")
      sy = _logical_pauli_in_dim(qutip, normalized_dim, "sy")
      if sx is None or sy is None:
        return _invalid_payload(f"qutip worker cannot build {kind_for_handler} operator")

      if kind_for_handler == "two_mode_squeezing":
        if n_targets < 2:
          return _invalid_payload("qutip worker two_mode_squeezing requires at least two targets")
        sx_l = _embed_qubit_operator(qutip, sx, n_targets, 0, dim=normalized_dim)
        sx_r = _embed_qubit_operator(qutip, sx, n_targets, 1, dim=normalized_dim)
        local_h = coupling_or_angle * (sx_l * sx_r)
      else:
        sx_l = _embed_qubit_operator(qutip, sx, n_targets, 0, dim=normalized_dim)
        sy_l = _embed_qubit_operator(qutip, sy, n_targets, 0, dim=normalized_dim)
        sx_r = _embed_qubit_operator(qutip, sx, n_targets, 1, dim=normalized_dim) if n_targets > 1 else None
        sy_r = _embed_qubit_operator(qutip, sy, n_targets, 1, dim=normalized_dim) if n_targets > 1 else None
        if sx_l is None or sy_l is None or sx_r is None or sy_r is None:
          return _invalid_payload(f"qutip worker cannot build {kind_for_handler} operator")

        if kind_for_handler in {"hom_interference", "beam_splitter", "mode_coupling"}:
          local_h = 0.5 * coupling_or_angle * (sx_l * sx_r + sy_l * sy_r)
        else:
          return _invalid_payload(f"qutip worker unsupported configuration for {kind_for_handler}")

      unitary = (-1j * local_h * duration).expm() if duration > 0.0 else _cluster_identity_for_targets()
      return _apply_cluster_unitary(operation_targets, unitary, f"qutip worker applied {kind_for_handler} with angle={coupling_or_angle}")

    if kind_for_handler in {"phase_shift", "phase_modulation", "self_phase_modulation", "cross_phase_modulation", "nonlinear"}:
      phase_raw = payload.get("angle", payload.get("phi", payload.get("theta", 0.0)))
      params_value = _as_float(params_f[0] if params_f else phase_raw)
      sigma_z = _logical_pauli_in_dim(qutip, normalized_dim, "sz")
      if sigma_z is None:
        return _invalid_payload(f"qutip worker cannot build phase operator for {kind_for_handler}")
      if kind_for_handler in {"cross_phase_modulation", "nonlinear"} and n_targets >= 2:
        left = _embed_qubit_operator(qutip, sigma_z, n_targets, 0, dim=normalized_dim)
        right = _embed_qubit_operator(qutip, sigma_z, n_targets, 1, dim=normalized_dim)
        if left is None or right is None:
          return _invalid_payload(f"qutip worker cannot build coupled phase operator for {kind_for_handler}")
        local_h = params_value * left * right
      else:
        embedded = _embed_qubit_operator(qutip, params_value * sigma_z, n_targets, 0, dim=normalized_dim)
        if embedded is None:
          return _invalid_payload(f"qutip worker cannot build phase operator for {kind_for_handler}")
        local_h = -0.5 * embedded

      unitary = (-1j * local_h * duration).expm() if duration > 0.0 else _cluster_identity_for_targets()
      return _apply_cluster_unitary(operation_targets, unitary, f"qutip worker applied {kind_for_handler} with coeff={params_value}")

    if kind_for_handler == "polarization_rotation":
      axis = str(payload.get("axis", payload.get("basis", "z"))).lower()
      sigma_map = {"x": "sx", "y": "sy", "z": "sz"}
      local_op = _logical_pauli_in_dim(qutip, normalized_dim, sigma_map.get(axis, "sz"))
      if local_op is None:
        return _invalid_payload(f"qutip worker cannot build polarization rotation operator axis={axis}")
      local_h = local_op
      embedded = _embed_qubit_operator(qutip, local_h, n_targets, 0, dim=normalized_dim)
      if embedded is None:
        return _invalid_payload("qutip worker cannot build polarization rotation operator")
      unitary = (-1j * embedded * duration).expm() if duration > 0.0 else _cluster_identity_for_targets()
      return _apply_cluster_unitary(operation_targets, unitary, f"qutip worker applied polarization_rotation axis={axis} for duration={duration}")

    return None

  def _handle_representation_transition(
      kind_for_handler: str,
      *,
      success_message: str,
      extra_meta: Optional[dict[str, Any]] = None,
  ) -> dict:
    operation_targets, _, error = _resolve_targets(exact_targets=1)
    if error is not None:
      return _invalid_payload(error)
    if not operation_targets:
      return _invalid_payload("qutip worker missing required target for advanced representation transition")

    response = _build_response(
      True,
      fidelity_estimate=1.0,
      message=success_message,
    )
    response_meta = response.get("meta")
    if not isinstance(response_meta, dict):
      response_meta = {}
    response_meta["representation_mode"] = _advanced_representation(kind_for_handler)
    response_meta["representation_targets"] = len(operation_targets)
    if extra_meta:
      response_meta.update(extra_meta)
    response["meta"] = response_meta
    return _finalize(response)

  def _handle_photon_emission() -> dict:
    operation_targets, target_positions, error = _resolve_targets(exact_targets=1)
    if error is not None:
      return _invalid_payload(error)
    efficiency = _effective_probability(
      payload.get("efficiency", payload.get("eta", payload.get("p", 1.0))),
      1.0,
    )
    loss_probability = max(0.0, min(1.0, 1.0 - efficiency))
    if loss_probability > 0.0:
      temp_payload = dict(payload)
      temp_payload["noise_kind"] = "loss"
      temp_payload["p"] = _effective_probability(loss_probability)
      temp_operation = dict(operation)
      temp_operation["payload"] = temp_payload
      loss_response = _apply_cluster_kraus(
        "loss",
        temp_operation,
        operation_targets,
        target_positions,
        message=f"qutip worker simulated emission loss with p={loss_probability}",
      )
      if not loss_response.get("success"):
        return loss_response

    return _handle_representation_transition(
      "photon_emission",
      success_message=f"qutip worker applied photon emission with efficiency={efficiency}",
      extra_meta={"emission_efficiency": efficiency},
    )

  def _handle_photon_collect() -> dict:
    return _handle_representation_transition(
      "photon_collect",
      success_message="qutip worker applied photon collect coupling",
      extra_meta={"collect_coupling": _effective_probability(payload.get("coupling", payload.get("eta", 1.0)))},
    )

  def _handle_photon_propagation() -> dict:
    operation_targets, target_positions, error = _resolve_targets(exact_targets=1)
    if error is not None:
      return _invalid_payload(error)

    attenuation_raw = payload.get("attenuation", payload.get("loss", payload.get("eta", 0.0)))
    attenuation = _effective_probability(attenuation_raw)
    response: Optional[dict] = None
    if attenuation > 0.0:
      temp_payload = dict(payload)
      temp_payload["noise_kind"] = "loss"
      temp_payload["p"] = _effective_probability(attenuation)
      temp_operation = dict(operation)
      temp_operation["payload"] = temp_payload
      response = _apply_cluster_kraus(
        "loss",
        temp_operation,
        operation_targets,
        target_positions,
        message=f"qutip worker simulated photon propagation loss with p={attenuation}",
      )
      if not response.get("success"):
        return response

    dispersion = _as_float(payload.get("phase_dispersion", payload.get("dispersion", 0.0)))
    if dispersion != 0.0:
      sigma_z = _logical_pauli_in_dim(qutip, normalized_dim, "sz")
      if sigma_z is None:
        return _invalid_payload("qutip worker cannot build phase operator for propagation")
      if _embed_qubit_operator(qutip, sigma_z, 1, 0, dim=normalized_dim) is None:
        return _invalid_payload("qutip worker cannot build propagation phase operator")
      local_h = (-0.5 * dispersion) * sigma_z
      unitary = (-1j * local_h * duration).expm() if duration > 0.0 else _identity_in_dim(qutip, normalized_dim)
      response = _apply_cluster_unitary(
        operation_targets,
        unitary,
        f"qutip worker applied photon propagation with phase_dispersion={dispersion}",
      )

    if response is None:
      return _handle_representation_transition(
        "photon_propagation",
        success_message="qutip worker applied photon propagation channel",
        extra_meta={"propagation_attenuation": attenuation, "propagation_dispersion": dispersion},
      )

    response_meta = dict(response.get("meta") or {})
    response_meta["propagation_attenuation"] = attenuation
    response_meta["propagation_dispersion"] = dispersion
    response["meta"] = response_meta
    return _finalize(response)

  def _handle_advanced_noise(kind_for_handler: str) -> Optional[dict]:
    if kind_for_handler in {"reset"}:
      operation_targets, target_positions, error = _resolve_targets(exact_targets=1)
    elif kind_for_handler in {"timing_jitter", "jitter", "delay"}:
      operation_targets, target_positions, error = _resolve_targets(exact_targets=1)
    else:
      operation_targets, target_positions, error = _resolve_targets(exact_targets=1)
    if error is not None:
      return _invalid_payload(error)

    if kind_for_handler in {"timing_jitter", "jitter"}:
      jitter_raw = payload.get("jitter", params_f[0] if params_f else payload.get("std", 0.0))
      jitter_std = abs(_as_float(jitter_raw))
      p = _effective_probability(payload.get("p", 0.01 * jitter_std * max(duration, 1.0)))
      temp_payload = dict(payload)
      temp_payload["noise_kind"] = "decoherence"
      temp_payload["p"] = p
      temp_operation = dict(operation)
      temp_operation["payload"] = temp_payload
      return _apply_cluster_kraus("decoherence", temp_operation, operation_targets, target_positions, f"qutip worker applied timing_jitter with p={p}")

    if kind_for_handler == "delay":
      p = _effective_probability(payload.get("p", 0.0))
      temp_payload = dict(payload)
      if "rate" in temp_payload:
        rate = _as_float(temp_payload.get("rate"), 0.0)
        if rate > 0.0:
          p = 1.0 - math.exp(-rate * max(duration, 1e-12))
      temp_payload["noise_kind"] = "decoherence"
      temp_payload["p"] = p
      temp_operation = dict(operation)
      temp_operation["payload"] = temp_payload
      return _apply_cluster_kraus("decoherence", temp_operation, operation_targets, target_positions, f"qutip worker applied delay with p={p}")

    noise_kind = kind_for_handler
    if kind_for_handler in {"dephasing", "polarization_decoherence", "decoherence"}:
      noise_kind = "decoherence"
    if kind_for_handler in {"attenuation", "loss"}:
      noise_kind = "loss"
    return _apply_cluster_kraus(noise_kind, operation, operation_targets, target_positions, f"qutip worker applied {kind_for_handler} in cluster mode")

  def _handle_hamiltonian_lindblad() -> dict:
    operation_targets, _, error = _resolve_targets(min_targets=1)
    if error is not None:
      return _invalid_payload(error)
    n_targets = len(operation_targets)

    if kind == "hamiltonian":
      expression = str(payload.get("expr", payload.get("hamilbertian", "")))
      if (not expression or expression == "") and params_f:
        expression = str(params_f[0])
      if not expression.strip():
        return _invalid_payload("qutip worker requires expr/hamiltonian")
      h_op = _parse_operator_expr(expression, n_targets, qutip, normalized_dim)
      if h_op is None:
        return _invalid_payload(f"qutip worker cannot parse hamiltonian expr: {expression}")
      if duration <= 0.0:
        unitary = _identity_in_dim(qutip, h_op.shape[0])
      else:
        unitary = (-1j * h_op * duration).expm()
      return _apply_cluster_unitary(operation_targets, unitary, f"qutip worker applied hamiltonian with expr={expression} for duration={duration}")

    expression = payload.get("collapse", payload.get("expr", []))
    collapse_specs = _coerce_expr_as_list(expression)
    if not collapse_specs:
      return _invalid_payload("qutip worker requires expr/collapse for lindblad")
    collapse_ops = []
    for item in collapse_specs:
      c_op = _parse_operator_expr(str(item), n_targets, qutip, normalized_dim)
      if c_op is None:
        return _invalid_payload(f"qutip worker cannot parse lindblad collapse expr: {item}")
      collapse_ops.append(c_op)

    if duration <= 0.0:
      return _finalize(
        _build_response(
          True,
          fidelity_estimate=1.0,
          message="qutip worker applied zero-duration lindblad with identity effect",
        ),
      )

    state = cluster_state.density_matrix
    rho_t = None
    target_positions = [cluster_state.qubits.index(target) for target in operation_targets]
    for c_op in collapse_ops:
      embedded = _embed_local_operator(state, c_op, cluster_state, target_positions, qutip)
      if not isinstance(embedded, tuple) or len(embedded) != 2:
        return _invalid_payload("qutip worker failed to build lindblad collapse operator")
      success_embed, full_op = embedded
      if not success_embed or full_op is None:
        return _invalid_payload("qutip worker failed to build lindblad collapse operator")
      term = full_op * state * full_op.dag()
      rho_t = term if rho_t is None else rho_t + term

    if rho_t is None:
      return _invalid_payload("qutip worker failed to apply advanced operation on cluster")
    norm = float(rho_t.tr())
    if norm <= 0.0:
      return _invalid_payload("qutip worker failed to apply advanced operation on cluster")
    if abs(norm - 1.0) > 1e-12:
      rho_t = rho_t / norm

    previous_state = cluster_state.density_matrix
    cluster_state.density_matrix = rho_t
    try:
      fidelity = float(qutip.metrics.fidelity(previous_state, rho_t))
    except Exception:
      fidelity = 1.0

    return _finalize(
      _build_response(True, fidelity_estimate=fidelity, message=f"qutip worker applied lindblad with {len(collapse_ops)} collapse operator(s) for duration={duration}"),
    )

  def _handle_event_kind(kind_for_handler: str) -> dict:
    params_raw = params_f[0] if params_f else payload.get(
      "p",
      payload.get(
        "success_probability",
        payload.get("visibility", payload.get("strength", 0.0)),
      ),
    )
    params_like = _as_float(params_raw)
    if kind_for_handler == "detection":
      operation_targets, target_positions, error = _resolve_targets(min_targets=1)
      if error is not None:
        return _invalid_payload(error)

      n_targets = len(operation_targets)
      if n_targets not in {1, 2}:
        return _invalid_payload(f"qutip worker detection supports one or two targets, target_count={n_targets}")

      if n_targets == 1:
        plus_projector_local, minus_projector_local = _onoff_detection_projectors_for_one_target(qutip, normalized_dim)
        success_event = "d0"
        failure_event = "none"
      else:
        plus_projector_local, minus_projector_local = _bell_detection_projectors_for_two_targets(qutip, normalized_dim)
        success_event = "d1,d3"
        failure_event = "d0,d2"

      raw_efficiency = payload.get("efficiency", payload.get("eta", 1.0))
      efficiency = _effective_probability(_as_float(raw_efficiency), 1.0)
      raw_dark_count = payload.get("dark_count", payload.get("detector", params_like))
      dark_count = _effective_probability(_as_float(raw_dark_count), 0.0)
      sqrt_efficiency = math.sqrt(max(0.0, efficiency))
      sqrt_dark = math.sqrt(max(0.0, dark_count))
      sqrt_no_dark = math.sqrt(max(0.0, 1.0 - dark_count))
      sqrt_miss = math.sqrt(max(0.0, 1.0 - efficiency))

      success_operator_local = sqrt_efficiency * plus_projector_local + sqrt_dark * minus_projector_local
      failure_operator_local = sqrt_miss * plus_projector_local + sqrt_no_dark * minus_projector_local

      success_ok, success_operator = _apply_local_operator_to_cluster(cluster_state, success_operator_local, target_positions, qutip)
      failure_ok, failure_operator = _apply_local_operator_to_cluster(cluster_state, failure_operator_local, target_positions, qutip)
      if not success_ok or not failure_ok or success_operator is None or failure_operator is None:
        return _invalid_payload("qutip worker failed to build detection operator")

      rho = cluster_state.density_matrix
      probability_success = float((success_operator * rho * success_operator.dag()).tr())
      probability_failure = float((failure_operator * rho * failure_operator.dag()).tr())
      total_probability = probability_success + probability_failure
      if total_probability <= 0.0:
        return _build_response(False, message=_categorize_error("invalid_payload", "qutip worker detection has zero branch norm"), error_category="invalid_payload", meta=_cluster_state_meta(cluster_state, cluster_key))

      probability_success = max(0.0, min(1.0, probability_success / total_probability))
      probability_failure = max(0.0, 1.0 - probability_success)
      rng = _rng(seed, {"kind": "detection_rng", "targets": n_targets, "success_probability": probability_success, "efficiency": efficiency, "dark_count": dark_count})
      measured_plus = rng.random() < probability_success
      selected_operator = success_operator if measured_plus else failure_operator
      selected_event = success_event if measured_plus else failure_event
      branch_probability = probability_success if measured_plus else probability_failure

      collapsed = selected_operator * rho * selected_operator.dag()
      collapsed_norm = float((collapsed * collapsed.dag()).tr())
      if collapsed_norm <= 0.0:
        return _build_response(False, message=_categorize_error("invalid_payload", "qutip worker collapsed detection state has zero norm"), error_category="invalid_payload", meta=_cluster_state_meta(cluster_state, cluster_key))
      cluster_state.density_matrix = collapsed / collapsed_norm

      response_meta = _cluster_state_meta(cluster_state, cluster_key)
      response_meta.update(
        {
          "detection_success_probability": probability_success,
          "detection_failure_probability": probability_failure,
          "detection_efficiency": efficiency,
          "detection_dark_count": dark_count,
        },
      )
      detection_pattern = selected_event
      detection_histogram = [0, 0, 0, 0]
      if detection_pattern == "d0":
        detection_histogram[0] = 1
      elif detection_pattern == "d1,d3":
        detection_histogram[1] = 1
        detection_histogram[3] = 1
      elif detection_pattern == "d0,d2":
        detection_histogram[0] = 1
        detection_histogram[2] = 1
      return _finalize(
        _build_response(
          True,
          outcome_pattern=detection_pattern,
          detection_click_count=1 if n_targets == 1 and detection_pattern != "none" else (2 if n_targets == 2 else 0),
          detector_histogram=detection_histogram,
          outcome=selected_event,
          branch_probability=branch_probability,
          measured_plus=measured_plus,
          fidelity_estimate=branch_probability,
          meta=response_meta,
          message=f"qutip worker simulated detection ({selected_event}) with efficiency={efficiency}, dark_count={dark_count}",
        ),
      )

    if kind_for_handler in {"dispersion", "squeezing", "fock_loss", "photon_number_cutoff", "loss_mode", "multiphoton", "source_multiphoton", "mode_coupling", "two_mode_squeezing"}:
      strength = abs(_effective_probability(params_like))
      return _finalize(
        _build_response(
          True,
          fidelity_estimate=_simple_fidelity_decay(strength, duration),
          message=f"qutip worker simulated {kind_for_handler} with strength={strength}",
        ),
      )

    return _invalid_payload(f"qutip worker unsupported cluster event kind {kind_for_handler}")

  handlers: dict[str, Any] = {
      "kerr": lambda: _handle_unitary_kind("kerr"),
      "cross_kerr": lambda: _handle_unitary_kind("cross_kerr"),
      "beam_splitter": lambda: _handle_unitary_kind("beam_splitter"),
      "hom_interference": lambda: _handle_unitary_kind("hom_interference"),
      "mode_coupling": lambda: _handle_unitary_kind("mode_coupling"),
      "two_mode_squeezing": lambda: _handle_unitary_kind("two_mode_squeezing"),
      "photon_emission": lambda: _handle_photon_emission(),
      "photon_collect": lambda: _handle_photon_collect(),
      "photon_propagation": lambda: _handle_photon_propagation(),
      "emission": lambda: _handle_photon_emission(),
      "collect": lambda: _handle_photon_collect(),
      "propagation": lambda: _handle_photon_propagation(),
      "fiber_propagation": lambda: _handle_photon_propagation(),
      "phase_shift": lambda: _handle_unitary_kind("phase_shift"),
      "phase_modulation": lambda: _handle_unitary_kind("phase_modulation"),
      "self_phase_modulation": lambda: _handle_unitary_kind("self_phase_modulation"),
      "cross_phase_modulation": lambda: _handle_unitary_kind("cross_phase_modulation"),
      "nonlinear": lambda: _handle_unitary_kind("nonlinear"),
      "polarization_rotation": lambda: _handle_unitary_kind("polarization_rotation"),
      "decoherence": lambda: _handle_advanced_noise("decoherence"),
      "dephasing": lambda: _handle_advanced_noise("dephasing"),
      "loss": lambda: _handle_advanced_noise("loss"),
      "attenuation": lambda: _handle_advanced_noise("attenuation"),
      "amplitude_damping": lambda: _handle_advanced_noise("amplitude_damping"),
      "thermal_relaxation": lambda: _handle_advanced_noise("thermal_relaxation"),
      "bitflip": lambda: _handle_advanced_noise("bitflip"),
      "phaseflip": lambda: _handle_advanced_noise("phaseflip"),
      "depolarizing": lambda: _handle_advanced_noise("depolarizing"),
      "polarization_decoherence": lambda: _handle_advanced_noise("polarization_decoherence"),
      "timing_jitter": lambda: _handle_advanced_noise("timing_jitter"),
      "jitter": lambda: _handle_advanced_noise("jitter"),
      "delay": lambda: _handle_advanced_noise("delay"),
      "reset": lambda: _handle_advanced_noise("reset"),
      "hamiltonian": _handle_hamiltonian_lindblad,
      "lindblad": _handle_hamiltonian_lindblad,
      "detection": lambda: _handle_event_kind("detection"),
      "dispersion": lambda: _handle_event_kind("dispersion"),
      "squeezing": lambda: _handle_event_kind("squeezing"),
      "fock_loss": lambda: _handle_event_kind("fock_loss"),
      "photon_number_cutoff": lambda: _handle_event_kind("photon_number_cutoff"),
      "loss_mode": lambda: _handle_event_kind("loss_mode"),
      "multiphoton": lambda: _handle_event_kind("multiphoton"),
      "source_multiphoton": lambda: _handle_event_kind("source_multiphoton"),
  }

  handler = handlers.get(kind)
  if handler is None:
    return _finalize(
      _build_response(False, message=_categorize_error("unsupported_kind", f"qutip worker advanced operation not supported yet: {kind}"), error_category="unsupported_kind"),
    )

  response = handler()
  if not isinstance(response, dict):
    return _finalize(
      _build_response(False, message=_categorize_error("unsupported_kind", f"qutip worker unsupported advanced handler state for kind: {kind}"), error_category="unsupported_kind"),
    )

  if not isinstance(response.get("meta"), dict):
    response_meta = response.get("meta")
    if response_meta is None:
      response["meta"] = _cluster_state_meta(cluster_state, cluster_key)

  return response

def _handle_noop() -> dict:
  return _build_response(True, message="qutip worker noop")


def _finalize_response(
    response: dict,
    trace: dict,
    kind: str,
    profile_error: Optional[str],
    profile_meta: Optional[dict[str, Any]],
) -> dict:
  response = _attach_profile_metadata(response, profile_meta)
  if profile_error is not None and not response.get("error_category"):
    response["error_category"] = profile_error
  response["operation_model"] = _normalize_operation_model(response.get("operation_model"))
  if response["operation_model"] == "unsupported":
    response["operation_model"] = _operation_model_for_kind(kind)
  response.update(trace)
  return response


def run_operation(request: dict) -> dict:
  operation = _get_payload(request)
  kind = _canonicalize_kind(operation.get("kind", ""))
  seed = _get_request_seed(request)
  _, profile_meta, profile_error = _resolve_profile(request, kind, operation)
  trace = _trace_fields(request, operation)
  backend_config = request.get("backend_config", {})

  if profile_error is not None:
    error_reason = "qutip worker invalid profile configuration"
    if isinstance(profile_meta, dict) and isinstance(profile_meta.get("errors"), str):
      error_reason = f"{error_reason}: {profile_meta['errors']}"
    response = _build_response(
      False,
      error_category=profile_error,
      message=_categorize_error(profile_error, error_reason),
    )
    return _finalize_response(response, trace, kind, profile_error, profile_meta)

  profile_dim = _effective_profile_dim(profile_meta, int((profile_meta or {}).get("dim", 2)))
  # Initialize qutip import cache here so first-time heavy import does not
  # accidentally hit operation-level timeout.
  if _coerce_qutip_modules() is None:
    return _finalize_response(_qutip_unavailable_response(kind), trace, kind=kind, profile_error=profile_error, profile_meta=profile_meta)
  timeout_ms_raw = backend_config.get("qutip_worker_timeout_ms", 1000)
  try:
    timeout_ms = int(timeout_ms_raw or 1000)
  except (TypeError, ValueError):
    timeout_ms = 1000
  limit_error = _validate_backend_limits(request, operation)
  if limit_error is not None:
    return _finalize_response(limit_error, trace, kind, profile_error, profile_meta)

  if kind == "unitary":
    return _finalize_response(
      _run_with_timeout(_handle_unitary, operation, seed, timeout_ms, profile_meta=profile_meta, dim=profile_dim),
      trace,
      kind,
      profile_error,
      profile_meta,
    )
  if kind == "measurement":
    return _finalize_response(
      _run_with_timeout(_handle_measurement, operation, seed, timeout_ms, profile_meta=profile_meta, dim=profile_dim),
      trace,
      kind,
      profile_error,
      profile_meta,
    )
  if kind == "error_channel":
    return _finalize_response(
      _run_with_timeout(_handle_error_channel, operation, seed, timeout_ms, profile_meta=profile_meta, dim=profile_dim),
      trace,
      kind,
      profile_error,
      profile_meta,
    )
  if kind == "noise":
    return _finalize_response(
      _run_with_timeout(_handle_noise, operation, seed, timeout_ms, profile_meta=profile_meta, dim=profile_dim),
      trace,
      kind,
      profile_error,
      profile_meta,
    )
  if kind == "noop":
    return _finalize_response(_handle_noop(), trace, kind, profile_error, profile_meta)
  if _is_advanced_operation_kind(kind):
    return _finalize_response(
      _run_with_timeout(_handle_advanced, operation, seed, timeout_ms, profile_meta=profile_meta, dim=profile_dim),
      trace,
      kind,
      profile_error,
      profile_meta,
    )

  response = _build_response(False, message=_categorize_error("unsupported_kind", f"qutip worker unknown operation kind: {kind}"), error_category="unsupported_kind")
  return _finalize_response(response, trace, kind, profile_error, profile_meta)


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
    response = _build_response(False, message=f"qutip worker request parse error: {exc}", error_category="invalid_payload")
    output_path.write_text(json.dumps(response), encoding="utf-8")
    return 1

  response = run_operation(request)
  output_path.write_text(json.dumps(response), encoding="utf-8")
  return 0 if response.get("success") else 2


if __name__ == "__main__":
  raise SystemExit(main())
