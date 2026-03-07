from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional
import asyncio
import json
import os
import shutil
import time

from .sim_models import SimRunStatus


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _tail_file_lines(path: Path, *, limit: int = 2000) -> Deque[str]:
    lines: Deque[str] = deque(maxlen=limit)
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                lines.append(line.rstrip("\n")[:1000])
    except OSError:
        pass
    return lines


def _pid_exists(pid: Optional[int]) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _infer_created_at(run_id: str, fallback_path: Path) -> float:
    parts = str(run_id).split("_")
    if len(parts) >= 3 and parts[1].isdigit():
        millis = float(parts[1])
        return millis / 1000.0
    try:
        return fallback_path.stat().st_mtime
    except OSError:
        return time.time()


def _parse_run_ini(ini_path: Path) -> tuple[str, list[str]]:
    config_name = ""
    command: list[str] = []
    current_config = ""
    try:
        with ini_path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                stripped = line.strip()
                if stripped.startswith("[Config ") and stripped.endswith("]"):
                    current_config = stripped[len("[Config "):-1].strip()
                    continue
                if current_config.startswith("Dashboard_") and stripped.startswith("extends ="):
                    config_name = stripped.split("=", 1)[1].strip()
                if stripped.startswith("#../quisp "):
                    command = stripped[1:].split()
    except OSError:
        return "", []
    return config_name, command


def _infer_status_from_logs(stderr_tail: Deque[str], stdout_tail: Deque[str]) -> SimRunStatus:
    combined = list(stderr_tail)[-20:] + list(stdout_tail)[-20:]
    if any("Traceback" in line or "Error:" in line or "failed" in line.lower() for line in combined):
        return SimRunStatus.FAILED
    return SimRunStatus.FINISHED


def infer_status_message_from_logs(
    status: SimRunStatus,
    stderr_tail: Deque[str],
    stdout_tail: Deque[str],
    *,
    exit_code: Optional[int] = None,
    timeout_reached: bool = False,
    requested_stop: bool = False,
) -> str:
    stdout_lines = [line.strip() for line in list(stdout_tail)[-200:] if line and line.strip()]
    stderr_lines = [line.strip() for line in list(stderr_tail)[-200:] if line and line.strip()]

    if timeout_reached:
        return "runner timeout reached"
    if requested_stop or status == SimRunStatus.TERMINATED:
        return "terminated by user request"

    if status == SimRunStatus.FINISHED:
        for line in reversed(stdout_lines):
            if "Simulation time limit reached" in line:
                _, _, detail = line.partition("--")
                detail = detail.strip()
                return detail or "sim-time-limit reached"
        for line in reversed(stdout_lines):
            lowered = line.lower()
            if "no more events" in lowered:
                return "no more events in FES"
        return "finished"

    if status == SimRunStatus.FAILED:
        for line in reversed(stderr_lines):
            if line.startswith("Error:"):
                return line
        for line in reversed(stderr_lines):
            if "Traceback" in line:
                break
            if line:
                return line
        for line in reversed(stdout_lines):
            lowered = line.lower()
            if "<!>" in line or "error" in lowered or "failed" in lowered:
                return line
        if exit_code is not None:
            return f"exit code {exit_code}"
        return "failed"

    if status == SimRunStatus.STOPPING:
        return "stopping"
    if status == SimRunStatus.STARTING:
        return "starting"
    if status == SimRunStatus.RUNNING:
        return "running"
    if status == SimRunStatus.QUEUED:
        return "queued"
    return str(status)


@dataclass
class SimRunRecord:
    run_id: str
    template_id: str
    config_name: str
    log_path: Path
    ini_path: Path
    command: List[str]
    workdir: Path
    run_name: Optional[str] = None
    experiment_display_name: Optional[str] = None
    experiment_profile_id: Optional[str] = None
    parameter_values: Dict[str, Any] = field(default_factory=dict)
    requested_metrics: List[str] = field(default_factory=list)
    tags: Dict[str, str] = field(default_factory=dict)
    num_runs: int = 1
    seed_set: Optional[int] = None
    sim_time_limit: Optional[float] = None
    status: SimRunStatus = SimRunStatus.QUEUED
    status_message: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    pid: Optional[int] = None
    exit_code: Optional[int] = None
    output_lines: int = 0
    timeout_reached: bool = False
    requested_stop: bool = False
    archived: bool = False
    process: Optional[Any] = field(default=None, repr=False)
    stdout_tail: Deque[str] = field(default_factory=lambda: deque(maxlen=2000))
    stderr_tail: Deque[str] = field(default_factory=lambda: deque(maxlen=2000))

    @property
    def dashboard_run_id(self) -> str:
        return self.run_id

    @property
    def run_dir(self) -> Path:
        return self.log_path.parent

    @property
    def metadata_path(self) -> Path:
        return self.run_dir / "sim_run.json"

    @property
    def experiment_spec_path(self) -> Path:
        return self.run_dir / "experiment_spec.json"

    @property
    def resolved_overrides_path(self) -> Path:
        return self.run_dir / "resolved_overrides.json"

    @property
    def experiment_summary_path(self) -> Path:
        return self.run_dir / "experiment_summary.json"

    @property
    def experiment_timeseries_path(self) -> Path:
        return self.run_dir / "experiment_timeseries.jsonl"

    @property
    def display_name(self) -> str:
        if self.experiment_display_name and self.experiment_display_name.strip():
            return self.experiment_display_name.strip()
        if self.run_name and self.run_name.strip():
            return self.run_name.strip()
        if self.config_name and self.config_name.strip():
            return self.config_name.strip()
        template_name = Path(self.template_id).stem
        return template_name or self.run_id

    @property
    def created_at_iso(self) -> str:
        return datetime.fromtimestamp(self.created_at, tz=timezone.utc).isoformat().replace("+00:00", "Z")

    @property
    def started_at_iso(self) -> Optional[str]:
        if self.started_at is None:
            return None
        return datetime.fromtimestamp(self.started_at, tz=timezone.utc).isoformat().replace("+00:00", "Z")

    @property
    def finished_at_iso(self) -> Optional[str]:
        if self.finished_at is None:
            return None
        return datetime.fromtimestamp(self.finished_at, tz=timezone.utc).isoformat().replace("+00:00", "Z")

    @property
    def elapsed_seconds(self) -> float:
        end = self.finished_at if self.finished_at is not None else time.time()
        if self.started_at is None:
            return max(0.0, end - self.created_at)
        return max(0.0, end - self.started_at)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "display_name": self.display_name,
            "experiment_display_name": self.experiment_display_name,
            "dashboard_run_id": self.dashboard_run_id,
            "status": self.status,
            "status_message": self.status_message,
            "template_id": self.template_id,
            "config_name": self.config_name,
            "run_name": self.run_name,
            "experiment_profile_id": self.experiment_profile_id,
            "parameter_values": dict(self.parameter_values),
            "requested_metrics": list(self.requested_metrics),
            "tags": dict(self.tags),
            "experiment_summary_available": self.experiment_summary_path.exists(),
            "pid": self.pid,
            "workdir": str(self.workdir),
            "log_path": str(self.log_path),
            "created_at": self.created_at_iso,
            "started_at": self.started_at_iso,
            "finished_at": self.finished_at_iso,
            "exit_code": self.exit_code,
            "num_runs": self.num_runs,
            "seed_set": self.seed_set,
            "sim_time_limit": self.sim_time_limit,
            "command": list(self.command),
            "stdout_tail": list(self.stdout_tail),
            "stderr_tail": list(self.stderr_tail),
            "output_lines": self.output_lines,
            "timeout_reached": self.timeout_reached,
            "requested_stop": self.requested_stop,
            "archived": self.archived,
        }

    def to_persisted_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "template_id": self.template_id,
            "config_name": self.config_name,
            "run_name": self.run_name,
            "experiment_display_name": self.experiment_display_name,
            "experiment_profile_id": self.experiment_profile_id,
            "parameter_values": dict(self.parameter_values),
            "requested_metrics": list(self.requested_metrics),
            "tags": dict(self.tags),
            "log_path": str(self.log_path),
            "ini_path": str(self.ini_path),
            "command": list(self.command),
            "workdir": str(self.workdir),
            "num_runs": self.num_runs,
            "seed_set": self.seed_set,
            "sim_time_limit": self.sim_time_limit,
            "status": self.status,
            "status_message": self.status_message,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "pid": self.pid,
            "exit_code": self.exit_code,
            "output_lines": self.output_lines,
            "timeout_reached": self.timeout_reached,
            "requested_stop": self.requested_stop,
            "archived": self.archived,
        }


class SimulationRunStore:
    def __init__(self, max_concurrent_runs: int = 2) -> None:
        self.max_concurrent_runs = max(1, int(max_concurrent_runs))
        self._runs: Dict[str, SimRunRecord] = {}
        self._lock = asyncio.Lock()

    def _persist_record(self, record: SimRunRecord) -> None:
        record.metadata_path.parent.mkdir(parents=True, exist_ok=True)
        record.metadata_path.write_text(
            json.dumps(record.to_persisted_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _restore_record(self, metadata_path: Path) -> Optional[SimRunRecord]:
        try:
            raw = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return None

        if not isinstance(raw, dict):
            return None

        run_id = str(raw.get("run_id") or metadata_path.parent.name)
        try:
            status = SimRunStatus(str(raw.get("status") or SimRunStatus.FINISHED))
        except ValueError:
            status = SimRunStatus.FINISHED

        pid = raw.get("pid")
        if status in {SimRunStatus.QUEUED, SimRunStatus.STARTING, SimRunStatus.RUNNING, SimRunStatus.STOPPING} and not _pid_exists(pid):
            status = SimRunStatus.TERMINATED
            raw["status_message"] = raw.get("status_message") or "restored after backend restart"

        run_dir = metadata_path.parent
        log_path = Path(raw.get("log_path") or (run_dir / "run.jsonl"))
        ini_path = Path(raw.get("ini_path") or (run_dir / "run.ini"))
        stdout_tail = _tail_file_lines(run_dir / "stdout.log")
        stderr_tail = _tail_file_lines(run_dir / "stderr.log")

        persisted_status_message = raw.get("status_message")
        inferred_status_message = infer_status_message_from_logs(
            status,
            stderr_tail,
            stdout_tail,
            exit_code=raw.get("exit_code"),
            timeout_reached=bool(raw.get("timeout_reached") or False),
            requested_stop=bool(raw.get("requested_stop") or False),
        )
        if persisted_status_message in {None, "", "queued", "starting", "running", "stopping", "terminated", "finished", "failed"}:
            persisted_status_message = inferred_status_message

        return SimRunRecord(
            run_id=run_id,
            template_id=str(raw.get("template_id") or ""),
            config_name=str(raw.get("config_name") or ""),
            log_path=log_path,
            ini_path=ini_path,
            command=[str(item) for item in (raw.get("command") or [])],
            workdir=Path(raw.get("workdir") or run_dir),
            run_name=raw.get("run_name"),
            experiment_display_name=raw.get("experiment_display_name"),
            experiment_profile_id=raw.get("experiment_profile_id"),
            parameter_values=dict(raw.get("parameter_values") or {}),
            requested_metrics=[str(item) for item in (raw.get("requested_metrics") or [])],
            tags={str(key): str(value) for key, value in dict(raw.get("tags") or {}).items()},
            num_runs=int(raw.get("num_runs") or 1),
            seed_set=raw.get("seed_set"),
            sim_time_limit=raw.get("sim_time_limit"),
            status=status,
            status_message=persisted_status_message,
            created_at=float(raw.get("created_at") or time.time()),
            started_at=raw.get("started_at"),
            finished_at=raw.get("finished_at"),
            pid=pid,
            exit_code=raw.get("exit_code"),
            output_lines=int(raw.get("output_lines") or 0),
            timeout_reached=bool(raw.get("timeout_reached") or False),
            requested_stop=bool(raw.get("requested_stop") or False),
            archived=bool(raw.get("archived") or False),
            stdout_tail=stdout_tail,
            stderr_tail=stderr_tail,
        )

    def _restore_from_run_dir(self, run_dir: Path) -> Optional[SimRunRecord]:
        log_path = run_dir / "run.jsonl"
        ini_path = run_dir / "run.ini"
        if not log_path.exists() and not ini_path.exists():
            return None

        config_name, command = _parse_run_ini(ini_path)
        stdout_tail = _tail_file_lines(run_dir / "stdout.log")
        stderr_tail = _tail_file_lines(run_dir / "stderr.log")
        run_id = run_dir.name
        created_at = _infer_created_at(run_id, log_path if log_path.exists() else ini_path)
        experiment_spec: dict[str, Any] = {}
        try:
            experiment_spec = json.loads((run_dir / "experiment_spec.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            experiment_spec = {}

        status = _infer_status_from_logs(stderr_tail, stdout_tail)
        return SimRunRecord(
            run_id=run_id,
            template_id="",
            config_name=config_name,
            log_path=log_path,
            ini_path=ini_path,
            command=command,
            workdir=run_dir,
            run_name=experiment_spec.get("run_name"),
            experiment_display_name=experiment_spec.get("experiment_display_name"),
            experiment_profile_id=experiment_spec.get("experiment_profile_id"),
            parameter_values=dict(experiment_spec.get("parameter_values") or {}),
            requested_metrics=[str(item) for item in (experiment_spec.get("requested_metrics") or [])],
            tags={str(key): str(value) for key, value in dict(experiment_spec.get("tags") or {}).items()},
            status=status,
            status_message=infer_status_message_from_logs(status, stderr_tail, stdout_tail),
            created_at=created_at,
            finished_at=created_at,
            archived=False,
            stdout_tail=stdout_tail,
            stderr_tail=stderr_tail,
        )

    async def register(self, record: SimRunRecord) -> SimRunRecord:
        async with self._lock:
            for existing in self._runs.values():
                if existing.log_path == record.log_path:
                    raise ValueError(f"log_path already registered: {record.log_path}")
            if record.run_id in self._runs:
                raise ValueError(f"run already exists: {record.run_id}")
            self._runs[record.run_id] = record
            self._persist_record(record)
        return record

    async def update_run(self, run_id: str, **updates: Any) -> SimRunRecord:
        async with self._lock:
            if run_id not in self._runs:
                raise KeyError(f"unknown run_id {run_id}")
            record = self._runs[run_id]
            for key, value in updates.items():
                if hasattr(record, key):
                    setattr(record, key, value)
            self._persist_record(record)
            return record

    async def get(self, run_id: str) -> SimRunRecord:
        async with self._lock:
            if run_id not in self._runs:
                raise KeyError(f"unknown run_id {run_id}")
            return self._runs[run_id]

    async def list_runs(self) -> List[SimRunRecord]:
        async with self._lock:
            return sorted(self._runs.values(), key=lambda item: item.created_at, reverse=True)

    async def restore_from_disk(self, log_dir: Path) -> List[SimRunRecord]:
        restored: List[SimRunRecord] = []
        async with self._lock:
            for run_dir in sorted(path for path in log_dir.iterdir() if path.is_dir()):
                metadata_path = run_dir / "sim_run.json"
                record = self._restore_record(metadata_path) if metadata_path.exists() else self._restore_from_run_dir(run_dir)
                if record is None or record.run_id in self._runs:
                    continue
                self._runs[record.run_id] = record
                restored.append(record)
        return restored

    async def count_active(self) -> int:
        runs = await self.list_runs()
        return sum(1 for item in runs if item.status in {SimRunStatus.QUEUED, SimRunStatus.STARTING, SimRunStatus.RUNNING})

    async def append_output(self, run_id: str, stream: str, line: str) -> SimRunRecord:
        line = line.rstrip("\n")[:1000]
        async with self._lock:
            if run_id not in self._runs:
                raise KeyError(f"unknown run_id {run_id}")
            record = self._runs[run_id]
            record.output_lines += 1
            if stream == "stderr":
                record.stderr_tail.append(line)
            else:
                record.stdout_tail.append(line)
            return record

    async def latest_status(self, run_id: str) -> SimRunStatus:
        record = await self.get(run_id)
        return record.status

    async def archive_runs(
        self,
        *,
        run_ids: Optional[List[str]] = None,
        completed_only: bool = False,
        archived: bool = True,
    ) -> List[SimRunRecord]:
        async with self._lock:
            selected_ids = set(run_ids or [])
            updated: List[SimRunRecord] = []
            for record in self._runs.values():
                if selected_ids and record.run_id not in selected_ids:
                    continue
                if completed_only and record.status not in {SimRunStatus.FINISHED, SimRunStatus.FAILED, SimRunStatus.TERMINATED}:
                    continue
                if record.status in {SimRunStatus.QUEUED, SimRunStatus.STARTING, SimRunStatus.RUNNING, SimRunStatus.STOPPING}:
                    continue
                if record.archived == archived:
                    continue
                record.archived = archived
                self._persist_record(record)
                updated.append(record)
            if selected_ids and not updated and not completed_only:
                missing = sorted(run_id for run_id in selected_ids if run_id not in self._runs)
                if missing:
                    raise KeyError(f"unknown run_id {missing[0]}")
            return sorted(updated, key=lambda item: item.created_at, reverse=True)

    async def delete_runs(
        self,
        *,
        run_ids: Optional[List[str]] = None,
        delete_all_archived: bool = False,
    ) -> List[str]:
        async with self._lock:
            selected_ids = set(run_ids or [])
            targets: List[SimRunRecord] = []
            for record in self._runs.values():
                if delete_all_archived:
                    if not record.archived:
                        continue
                elif selected_ids:
                    if record.run_id not in selected_ids:
                        continue
                else:
                    continue
                if record.status in {SimRunStatus.QUEUED, SimRunStatus.STARTING, SimRunStatus.RUNNING, SimRunStatus.STOPPING}:
                    raise RuntimeError(f"cannot delete active run: {record.run_id}")
                if not record.archived:
                    raise RuntimeError(f"run must be archived before delete: {record.run_id}")
                targets.append(record)

            if selected_ids and not targets:
                missing = sorted(run_id for run_id in selected_ids if run_id not in self._runs)
                if missing:
                    raise KeyError(f"unknown run_id {missing[0]}")
                return []

            deleted_ids: List[str] = []
            for record in targets:
                shutil.rmtree(record.run_dir, ignore_errors=False)
                self._runs.pop(record.run_id, None)
                deleted_ids.append(record.run_id)
            return deleted_ids

    async def to_metrics(self, run_id: str, event_count: int = 0) -> Dict[str, Any]:
        record = await self.get(run_id)
        log_touched: Optional[str] = None
        try:
            log_touched = datetime.fromtimestamp(record.log_path.stat().st_mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        except OSError:
            log_touched = None
        return {
            "run_id": record.run_id,
            "status": record.status,
            "elapsed_seconds": record.elapsed_seconds,
            "output_lines": record.output_lines,
            "event_count": max(0, int(event_count)),
            "log_touched": log_touched,
            "stdout_tail_lines": len(record.stdout_tail),
            "stderr_tail_lines": len(record.stderr_tail),
            "last_log_path": str(record.log_path),
        }

    async def set_process(self, run_id: str, process: Any) -> SimRunRecord:
        async with self._lock:
            record = await self.get(run_id)
            record.process = process
            record.pid = getattr(process, "pid", None)
            self._persist_record(record)
            return record
