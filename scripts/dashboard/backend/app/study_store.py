"""Tiny JSON-backed store for Study annotations (hypothesis, notes).

Phase 3-B introduces the notion of a Study attached to an experiment
profile. Until a richer backend model materialises, we persist just the
free-text fields the researcher writes alongside a profile so they
survive across reloads and across machines (when the runs/ directory
is shared).

Each profile is stored as scripts/dashboard/studies/<profile_id>.json
with a stable schema:

    {
      "profile_id": "verify_linear_five_activity",
      "hypothesis": "...",
      "notes": "...",
      "updated_at": "2026-05-04T10:34:12+00:00"
    }

The store is intentionally minimal: no history, no concurrent-write
conflict resolution beyond a process-local lock. That matches how the
dashboard is run today (single uvicorn process). When we move to a
real Studies model the same JSON files become the migration source.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


_PROFILE_ID_ALLOWED = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")


def _sanitise_profile_id(profile_id: str) -> str:
    """Reject anything that could escape the studies directory.

    Profile ids in the catalog are conservative ASCII slugs already, so
    this is a defence-in-depth check rather than a transformation.
    """

    text = (profile_id or "").strip()
    if not text:
        raise ValueError("profile_id is empty")
    if any(ch not in _PROFILE_ID_ALLOWED for ch in text):
        raise ValueError(f"profile_id contains illegal characters: {profile_id!r}")
    if text.startswith(".") or "/" in text or "\\" in text:
        raise ValueError(f"profile_id is not a safe filename: {profile_id!r}")
    return text


class StudyStore:
    """Per-profile hypothesis / notes store backed by JSON files."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    # ---- Public API -------------------------------------------------

    def get(self, profile_id: str) -> Dict[str, Any]:
        safe_id = _sanitise_profile_id(profile_id)
        path = self.root / f"{safe_id}.json"
        if not path.exists():
            return {
                "profile_id": safe_id,
                "hypothesis": "",
                "notes": "",
                "updated_at": None,
            }
        try:
            with self._lock:
                raw = path.read_text(encoding="utf-8")
            data = json.loads(raw) if raw.strip() else {}
        except (OSError, json.JSONDecodeError):
            # Corrupt file: report empty rather than 500. The next save
            # will overwrite it cleanly.
            return {
                "profile_id": safe_id,
                "hypothesis": "",
                "notes": "",
                "updated_at": None,
            }
        return {
            "profile_id": safe_id,
            "hypothesis": str(data.get("hypothesis") or ""),
            "notes": str(data.get("notes") or ""),
            "updated_at": data.get("updated_at"),
        }

    def upsert(self, profile_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        safe_id = _sanitise_profile_id(profile_id)
        merged = self.get(safe_id)
        if "hypothesis" in payload:
            merged["hypothesis"] = str(payload.get("hypothesis") or "").strip()
        if "notes" in payload:
            merged["notes"] = str(payload.get("notes") or "")  # preserve newlines for notes
        merged["updated_at"] = datetime.now(timezone.utc).isoformat()
        path = self.root / f"{safe_id}.json"
        with self._lock:
            path.write_text(
                json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        return merged

    def list_all(self) -> Dict[str, Dict[str, Any]]:
        """Best-effort dump for diagnostics; not used by the UI yet."""
        out: Dict[str, Dict[str, Any]] = {}
        for path in self.root.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                out[path.stem] = data
            except (OSError, json.JSONDecodeError):
                continue
        return out
