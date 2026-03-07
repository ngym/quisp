from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence
import re

from .sim_models import SimTemplate

CONFIG_RE = re.compile(r"^\s*\[Config\s+([^\]]+)\]\s*$")


class TemplateNotFoundError(RuntimeError):
    pass


class TemplateParsingError(RuntimeError):
    pass


def _project_root(script_file: Path) -> Path:
    resolved = script_file.resolve()
    markers = ("pyproject.toml", "build.toml", "tbump.toml", ".git", "Makefile", "README.md")
    for candidate in [resolved, *resolved.parents]:
        for marker in markers:
            if (candidate / marker).exists():
                if (candidate / "scripts" / "dashboard").exists() or marker in {"pyproject.toml", ".git", "build.toml", "tbump.toml"}:
                    return candidate
    for candidate in [resolved, *resolved.parents]:
        if candidate.name in {"quisp", "GITHUB"}:
            return candidate
    return resolved.parent


def _iso_mtime(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except OSError:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _extract_config_names(text: str) -> list[str]:
    names: list[str] = []
    for line in text.splitlines():
        m = CONFIG_RE.match(line)
        if not m:
            continue
        name = m.group(1).strip()
        if name:
            names.append(name)
    # deterministic order for reproducibility
    return names


def _template_search_roots(project_root: Path) -> list[Path]:
    return [
        project_root / "quisp" / "networks",
        project_root / "quisp" / "simulations",
        project_root / "simulations",
    ]


def _dashboard_default_workdir(project_root: Path) -> Path:
    candidate = (project_root / "quisp").resolve()
    if candidate.exists():
        return candidate
    return project_root.resolve()


def _iter_template_files(project_root: Path) -> list[Path]:
    roots = _template_search_roots(project_root)
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        files.extend(sorted(root.glob("*.ini")))
    return files


def _read_template(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")


def _build_description(path: Path, content: str) -> Optional[str]:
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            comment = line[1:].strip()
            return comment[:120] if comment else None
    return None


def list_templates(*, project_root: Optional[Path] = None) -> list[SimTemplate]:
    root = project_root or _project_root(Path(__file__))
    default_workdir = _dashboard_default_workdir(root)
    templates: list[SimTemplate] = []
    for path in _iter_template_files(root):
        content = _read_template(path)
        available = sorted(set(_extract_config_names(content)), key=str)
        relative_id = str(path.relative_to(root).as_posix())
        templates.append(
            SimTemplate(
                template_id=relative_id,
                path=str(path.resolve()),
                available_configs=available,
                description=_build_description(path, content),
                default_workdir=str(default_workdir),
                last_modified=_iso_mtime(path),
            )
        )
    return templates


def get_template_path(template_id: str, *, project_root: Optional[Path] = None) -> Path:
    root = project_root or _project_root(Path(__file__))
    if not template_id:
        raise TemplateNotFoundError("template_id is required")
    try:
        candidate = Path(template_id)
    except Exception as exc:  # pragma: no cover - defensive
        raise TemplateNotFoundError(f"invalid template_id: {exc}")
    if candidate.is_absolute():
        raise TemplateNotFoundError("template_id must be relative")

    candidate = (root / candidate).resolve()
    allowed: list[Path] = [
        path
        for p in _iter_template_files(root)
        for path in [p]
    ]
    allowed_set = {p.resolve() for p in allowed}
    if candidate not in allowed_set:
        raise TemplateNotFoundError(f"template not allowed: {template_id}")
    return candidate


def template_with_configs(template_id: str, *, project_root: Optional[Path] = None) -> Dict[str, List[str] | Path]:
    template_path = get_template_path(template_id, project_root=project_root)
    root = project_root or _project_root(Path(__file__))
    text = _read_template(template_path)
    return {
        "path": template_path,
        "config_names": _extract_config_names(text),
        "default_workdir": str(_dashboard_default_workdir(root)),
    }
