from __future__ import annotations

import asyncio
import json
import os
import secrets
import signal
import time
from pathlib import Path
from typing import Any, Optional

from .config_templates import get_template_path
from .experiment_aggregator import ExperimentAggregator
from .experiment_catalog import resolve_experiment_request
from .runner_config_builder import build_run_ini, validate_run_spec_overrides
from .sim_models import SimRunStartRequest, SimRunStatus
from .sim_store import SimRunRecord, SimulationRunStore, infer_status_message_from_logs
from .store import RunStore


class SimulationRunner:
    STOP_GRACE_SECONDS = 10.0

    def __init__(
        self,
        *,
        run_store: RunStore,
        sim_store: SimulationRunStore,
        quisp_binary: Path,
        execution_dir: Path,
        log_dir: Path,
        workspace_root: Path,
        max_concurrent_runs: int = 2,
        run_timeout_seconds: float = 7200.0,
        stop_timeout_seconds: float = 10.0,
        experiment_aggregator: Optional[ExperimentAggregator] = None,
        env: Optional[dict[str, str]] = None,
    ) -> None:
        self.run_store = run_store
        self.sim_store = sim_store
        self.quisp_binary = quisp_binary
        self.execution_dir = execution_dir
        self.log_dir = log_dir
        self.workspace_root = workspace_root
        self.max_concurrent_runs = max(1, int(max_concurrent_runs))
        self.run_timeout_seconds = max(0.0, float(run_timeout_seconds))
        self.stop_timeout_seconds = max(0.1, float(stop_timeout_seconds))
        self.experiment_aggregator = experiment_aggregator
        self._env = env
        self._tasks: dict[str, set[asyncio.Task[Any]]] = {}
        self._project_sim_root = (self.workspace_root / "quisp").resolve() if (self.workspace_root / "quisp").exists() else self.workspace_root.resolve()

    def _next_run_id(self, prefix: str = "run") -> str:
        ts = int(time.time() * 1000)
        token = secrets.token_hex(3)
        return f"{prefix}_{ts}_{token}"

    def _build_ned_path(self) -> str:
        roots = [
            self._project_sim_root / "modules",
            self._project_sim_root / "channels",
            self._project_sim_root / "networks",
        ]
        return ":".join(str(path) for path in roots if path.exists())

    def _build_command(
        self,
        *,
        config_name: str,
        ini_file: Path,
        num_runs: int,
        seed_set: Optional[int],
    ) -> list[str]:
        args = [
            str(self.quisp_binary),
            "-u",
            "Cmdenv",
            "--cmdenv-express-mode=true",
            "-n",
            self._build_ned_path(),
            "-c",
            config_name,
            "-f",
            str(ini_file),
        ]
        if num_runs > 1:
            args.extend(["-r", str(num_runs)])
        if seed_set is not None:
            args.extend(["--seed-set", str(seed_set)])
        return args

    async def _tail_stream(self, run_id: str, stream: asyncio.StreamReader, kind: str, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("a", encoding="utf-8") as handle:
            while True:
                line = await stream.readline()
                if not line:
                    return
                text = line.decode("utf-8", errors="replace")
                handle.write(text)
                handle.flush()
                await self.sim_store.append_output(run_id, kind, text)

    async def _stop_process(self, process: Any) -> None:
        if process.returncode is not None:
            return

        try:
            process.terminate()
        except ProcessLookupError:
            return

        try:
            await asyncio.wait_for(process.wait(), timeout=self.stop_timeout_seconds)
            return
        except asyncio.TimeoutError:
            pass

        try:
            process.kill()
        except ProcessLookupError:
            return

        await asyncio.wait_for(process.wait(), timeout=self.STOP_GRACE_SECONDS)

    async def _stop_pid(self, pid: int) -> None:
        if pid <= 0:
            return
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return

        deadline = time.time() + self.stop_timeout_seconds
        while time.time() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            await asyncio.sleep(0.2)

        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            return

        deadline = time.time() + self.STOP_GRACE_SECONDS
        while time.time() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            await asyncio.sleep(0.2)

    async def _monitor(self, run_id: str) -> None:
        record = await self.sim_store.get(run_id)
        process = record.process
        if process is None:
            await self.sim_store.update_run(
                run_id,
                status=SimRunStatus.FAILED,
                status_message="missing process",
                finished_at=time.time(),
            )
            self._tasks.pop(run_id, None)
            return

        timed_out = False
        try:
            if self.run_timeout_seconds:
                await asyncio.wait_for(process.wait(), timeout=self.run_timeout_seconds)
            else:
                await process.wait()
        except asyncio.TimeoutError:
            timed_out = True
            await self._stop_process(process)

        tail_tasks = [
            task
            for task in self._tasks.get(run_id, set())
            if task is not asyncio.current_task() and task is not None
        ]
        if tail_tasks:
            await asyncio.gather(*tail_tasks, return_exceptions=True)

        exit_code = process.returncode
        latest_record = await self.sim_store.get(run_id)
        updates: dict[str, Any] = {
            "finished_at": time.time(),
            "exit_code": exit_code,
        }
        if timed_out:
            updates["status"] = SimRunStatus.FAILED
            updates["status_message"] = infer_status_message_from_logs(
                SimRunStatus.FAILED,
                latest_record.stderr_tail,
                latest_record.stdout_tail,
                exit_code=exit_code,
                timeout_reached=True,
            )
            updates["timeout_reached"] = True
        elif latest_record.requested_stop:
            updates["status"] = SimRunStatus.TERMINATED
            updates["status_message"] = infer_status_message_from_logs(
                SimRunStatus.TERMINATED,
                latest_record.stderr_tail,
                latest_record.stdout_tail,
                exit_code=exit_code,
                requested_stop=True,
            )
        elif exit_code == 0:
            updates["status"] = SimRunStatus.FINISHED
            updates["status_message"] = infer_status_message_from_logs(
                SimRunStatus.FINISHED,
                latest_record.stderr_tail,
                latest_record.stdout_tail,
                exit_code=exit_code,
            )
        else:
            updates["status"] = SimRunStatus.FAILED
            updates["status_message"] = infer_status_message_from_logs(
                SimRunStatus.FAILED,
                latest_record.stderr_tail,
                latest_record.stdout_tail,
                exit_code=exit_code,
            )

        final_record = await self.sim_store.update_run(run_id, **updates)
        if self.experiment_aggregator is not None:
            try:
                self.experiment_aggregator.build_summary(
                    run_id,
                    display_name=final_record.display_name,
                    status=final_record.status.value,
                    experiment_profile_id=final_record.experiment_profile_id,
                    status_message=final_record.status_message,
                )
            except Exception:
                pass
        self._tasks.pop(run_id, None)

    async def start_run(self, *, request: SimRunStartRequest) -> SimRunRecord:
        active = await self.sim_store.count_active()
        if active >= self.max_concurrent_runs:
            raise RuntimeError("maximum concurrent runs exceeded")

        experiment_resolution = resolve_experiment_request(request)
        request = SimRunStartRequest(**experiment_resolution["request_dict"])
        run_id = self._next_run_id()
        request_overrides = validate_run_spec_overrides(request.overrides)
        qutip_python = (self._env or {}).get("QUTIP_PYTHON_EXECUTABLE") or os.environ.get("QUTIP_PYTHON_EXECUTABLE")
        if qutip_python:
            request_overrides.setdefault("**.qutip_python_executable", qutip_python)
        run_dir = self.log_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        log_path = run_dir / "run.jsonl"
        ini_path = run_dir / "run.ini"
        template_path = get_template_path(request.template_id, project_root=self.workspace_root)

        build_result = build_run_ini(
            template_path=template_path,
            output_path=ini_path,
            log_file_path=log_path,
            config_name=request.config_name,
            sim_time_limit=request.sim_time_limit,
            overrides=request_overrides,
        )
        effective_config_name = request.config_name
        if isinstance(build_result, tuple) and len(build_result) == 2:
            _, effective_config_name = build_result

        command = self._build_command(
            config_name=effective_config_name,
            ini_file=ini_path,
            num_runs=request.num_runs,
            seed_set=request.seed_set,
        )
        workdir = Path(request.workdir or self._project_sim_root).resolve()
        stdout_path = run_dir / "stdout.log"
        stderr_path = run_dir / "stderr.log"
        record = SimRunRecord(
            run_id=run_id,
            template_id=request.template_id or "",
            config_name=request.config_name or "",
            log_path=log_path,
            ini_path=ini_path,
            command=command,
            workdir=workdir,
            run_name=request.run_name,
            experiment_display_name=experiment_resolution["experiment_display_name"],
            experiment_profile_id=request.experiment_profile_id,
            parameter_values=dict(request.parameter_values or {}),
            requested_metrics=list(request.requested_metrics or []),
            tags={str(key): str(value) for key, value in dict(request.tags or {}).items()},
            num_runs=request.num_runs,
            seed_set=request.seed_set,
            sim_time_limit=request.sim_time_limit,
            status=SimRunStatus.QUEUED,
        )
        record.experiment_spec_path.write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "experiment_profile_id": request.experiment_profile_id,
                    "experiment_display_name": experiment_resolution["experiment_display_name"],
                    "run_name": request.run_name,
                    "template_id": request.template_id,
                    "config_name": request.config_name,
                    "parameter_values": request.parameter_values,
                    "requested_metrics": request.requested_metrics,
                    "tags": request.tags,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        record.resolved_overrides_path.write_text(
            json.dumps(experiment_resolution["resolved_overrides"], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        await self.sim_store.register(record)
        self.run_store.register_run_file(log_path, run_id=run_id)

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(workdir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, **(self._env or {})},
            )
        except Exception as exc:
            await self.sim_store.update_run(
                run_id,
                status=SimRunStatus.FAILED,
                status_message=f"failed to start process: {exc}",
                finished_at=time.time(),
            )
            raise

        await self.sim_store.update_run(
            run_id,
            status=SimRunStatus.STARTING,
            started_at=time.time(),
            status_message="starting",
            process=process,
            pid=process.pid,
        )

        assert process.stdout is not None and process.stderr is not None
        self._tasks[run_id] = {
            asyncio.create_task(self._tail_stream(run_id, process.stdout, "stdout", stdout_path)),
            asyncio.create_task(self._tail_stream(run_id, process.stderr, "stderr", stderr_path)),
        }
        self._tasks[run_id].add(asyncio.create_task(self._monitor(run_id)))

        await self.sim_store.update_run(run_id, status=SimRunStatus.RUNNING, status_message="running")
        return await self.sim_store.get(run_id)


    async def stop_run(self, run_id: str, timeout_seconds: float | None = None) -> SimRunRecord:
        record = await self.sim_store.get(run_id)
        if record.status in {SimRunStatus.FAILED, SimRunStatus.FINISHED, SimRunStatus.TERMINATED}:
            return record

        await self.sim_store.update_run(run_id, status=SimRunStatus.STOPPING, requested_stop=True, status_message="stopping")
        process = record.process
        if process is not None:
            try:
                await asyncio.wait_for(self._stop_process(process), timeout=timeout_seconds or self.stop_timeout_seconds)
            except asyncio.TimeoutError:
                await self.sim_store.update_run(run_id, status=SimRunStatus.TERMINATED, status_message="stop timeout")
        elif record.pid:
            try:
                await asyncio.wait_for(self._stop_pid(int(record.pid)), timeout=(timeout_seconds or self.stop_timeout_seconds) + self.STOP_GRACE_SECONDS)
            except asyncio.TimeoutError:
                await self.sim_store.update_run(run_id, status=SimRunStatus.TERMINATED, status_message="stop timeout")

        tasks = self._tasks.pop(run_id, None)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        final_record = await self.sim_store.get(run_id)
        if final_record.status in {SimRunStatus.STOPPING, SimRunStatus.STARTING, SimRunStatus.RUNNING}:
            await self.sim_store.update_run(run_id, status=SimRunStatus.TERMINATED, status_message="terminated")
        return await self.sim_store.get(run_id)

    async def list_runs(self) -> list[SimRunRecord]:
        return await self.sim_store.list_runs()

    async def get_run(self, run_id: str) -> SimRunRecord:
        return await self.sim_store.get(run_id)

    async def get_logs(self, run_id: str, limit: int = 200, mode: str = "all") -> list[str]:
        record = await self.sim_store.get(run_id)
        limit = max(1, int(limit))
        if mode == "stdout":
            return list(record.stdout_tail)[-limit:]
        if mode == "stderr":
            return list(record.stderr_tail)[-limit:]
        return (list(record.stdout_tail) + list(record.stderr_tail))[-limit:]

    async def get_metrics(self, run_id: str) -> dict[str, Any]:
        event_count = 0
        try:
            state = await self.run_store.refresh_run(run_id)
            event_count = len(state.indexes)
        except Exception:
            event_count = 0

        return {
            **await self.sim_store.to_metrics(run_id, event_count=event_count),
            "run_id": run_id,
        }
