from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional
import asyncio
import time

from .sim_models import SimRunStatus


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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
    process: Optional[Any] = field(default=None, repr=False)
    stdout_tail: Deque[str] = field(default_factory=lambda: deque(maxlen=2000))
    stderr_tail: Deque[str] = field(default_factory=lambda: deque(maxlen=2000))

    @property
    def dashboard_run_id(self) -> str:
        return self.run_id

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
            "dashboard_run_id": self.dashboard_run_id,
            "status": self.status,
            "status_message": self.status_message,
            "template_id": self.template_id,
            "config_name": self.config_name,
            "run_name": self.run_name,
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
        }


class SimulationRunStore:
    def __init__(self, max_concurrent_runs: int = 2) -> None:
        self.max_concurrent_runs = max(1, int(max_concurrent_runs))
        self._runs: Dict[str, SimRunRecord] = {}
        self._lock = asyncio.Lock()

    async def register(self, record: SimRunRecord) -> SimRunRecord:
        async with self._lock:
            for existing in self._runs.values():
                if existing.log_path == record.log_path:
                    raise ValueError(f"log_path already registered: {record.log_path}")
            if record.run_id in self._runs:
                raise ValueError(f"run already exists: {record.run_id}")
            self._runs[record.run_id] = record
        return record

    async def update_run(self, run_id: str, **updates: Any) -> SimRunRecord:
        async with self._lock:
            if run_id not in self._runs:
                raise KeyError(f"unknown run_id {run_id}")
            record = self._runs[run_id]
            for key, value in updates.items():
                if hasattr(record, key):
                    setattr(record, key, value)
            return record

    async def get(self, run_id: str) -> SimRunRecord:
        async with self._lock:
            if run_id not in self._runs:
                raise KeyError(f"unknown run_id {run_id}")
            return self._runs[run_id]

    async def list_runs(self) -> List[SimRunRecord]:
        async with self._lock:
            return sorted(self._runs.values(), key=lambda item: item.created_at, reverse=True)

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
            return record
