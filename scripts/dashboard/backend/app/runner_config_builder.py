from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Mapping
import re

from .sim_models import SimRunStartRequest

OVERRIDE_KEY_RE = re.compile(r"^[A-Za-z0-9_.*\[\]-]+$")


def _render_override_value(raw: Any) -> str:
    text = str(raw).strip()
    if not text:
        return '""'

    lowered = text.lower()
    if lowered in {"true", "false"}:
        return lowered

    if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?[A-Za-z]+", text):
        return text

    try:
        float(text)
    except ValueError:
        pass
    else:
        return text

    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        return text

    escaped = text.replace('"', '\\"')
    return f'"{escaped}"'


def _normalize_overrides(overrides: Mapping[str, Any]) -> Dict[str, str]:
    normalized: Dict[str, str] = {}
    for key, value in (overrides or {}).items():
        normalized_key = str(key).strip()
        if not OVERRIDE_KEY_RE.match(normalized_key):
            raise ValueError(f"unsupported override key: {normalized_key}")
        normalized[normalized_key] = str(value)
    return normalized


def _normalize_sim_time_limit(raw: Any) -> str:
    text = str(raw).strip()
    if not text:
        raise ValueError("sim-time-limit override must not be empty")
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", text):
        return f"{text}s"
    return text


def _derived_config_name(config_name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(config_name).strip())
    cleaned = cleaned or "General"
    return f"Dashboard_{cleaned}"


def build_run_ini(
    *,
    template_path: Path,
    output_path: Path,
    log_file_path: Path,
    config_name: str,
    sim_time_limit: float | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> tuple[Path, str]:
    base = template_path.read_text(encoding="utf-8", errors="replace")
    overrides_map = _normalize_overrides(overrides or {})
    derived_config_name = _derived_config_name(config_name)

    if sim_time_limit is not None:
        overrides_map.setdefault("sim-time-limit", _normalize_sim_time_limit(sim_time_limit))

    if "sim-time-limit" in overrides_map:
        overrides_map["sim-time-limit"] = _normalize_sim_time_limit(overrides_map["sim-time-limit"])

    # Dashboard playback depends on JsonLogger output, so force-enable it here.
    overrides_map.setdefault("**.logger.enabled_log", "true")

    lines = [base.rstrip(), ""]
    lines.append(f"[Config {derived_config_name}]")
    lines.append(f"extends = {config_name}")
    lines.append(f"**.logger.log_filename = \"{log_file_path}\"")

    if "sim-time-limit" in overrides_map:
        lines.append(f"sim-time-limit = {_render_override_value(overrides_map.pop('sim-time-limit'))}")

    for key in sorted(overrides_map):
        lines.append(f"{key} = {_render_override_value(overrides_map[key])}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path, derived_config_name


def validate_run_spec_overrides(overrides: Mapping[str, Any] | None) -> Dict[str, str]:
    return _normalize_overrides(overrides or {})


def apply_request_overrides(request: SimRunStartRequest) -> Dict[str, str]:
    return _normalize_overrides(request.overrides)
