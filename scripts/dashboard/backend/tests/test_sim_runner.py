from __future__ import annotations

import asyncio
import pathlib
from typing import Optional

import pytest

from scripts.dashboard.backend.app.models import SimRunStartRequest
from scripts.dashboard.backend.app.sim_models import SimRunStatus
from scripts.dashboard.backend.app.sim_store import SimRunRecord, SimulationRunStore
from scripts.dashboard.backend.app.store import RunStore
from scripts.dashboard.backend.app.simulation_runner import SimulationRunner
from scripts.dashboard.backend.app import simulation_runner as simulation_runner_module


def _dummy_record(run_id: str) -> SimRunRecord:
    return SimRunRecord(
        run_id=run_id,
        template_id="template.ini",
        config_name="General",
        log_path=pathlib.Path("/tmp") / f"{run_id}.jsonl",
        ini_path=pathlib.Path("/tmp") / f"{run_id}.ini",
        command=["quisp"],
        workdir=pathlib.Path("/tmp"),
        status=SimRunStatus.RUNNING,
    )


@pytest.mark.anyio
async def test_sim_store_register_and_list(tmp_path):
    store = SimulationRunStore(max_concurrent_runs=2)
    first = _dummy_record("run_001")
    await store.register(first)
    assert await store.count_active() == 1
    listed = await store.list_runs()
    assert len(listed) == 1


@pytest.mark.anyio
async def test_simulation_runner_rejects_when_over_max_concurrency(tmp_path):
    run_store = RunStore(log_dir=tmp_path)
    sim_store = SimulationRunStore(max_concurrent_runs=1)
    await sim_store.register(
        _dummy_record("run_001"),
    )
    runner = SimulationRunner(
        run_store=run_store,
        sim_store=sim_store,
        quisp_binary=tmp_path / "quisp",
        execution_dir=tmp_path,
        log_dir=tmp_path / "runs",
        workspace_root=tmp_path,
        max_concurrent_runs=1,
    )
    request = SimRunStartRequest(
        template_id="template.ini",
        config_name="General",
        num_runs=1,
    )
    with pytest.raises(RuntimeError):
        await runner.start_run(request=request)


class _StubReader:
    def __init__(self, payloads):
        self._payloads = list(payloads) if payloads else []

    async def readline(self) -> bytes:
        if not self._payloads:
            return b""
        return self._payloads.pop(0)


class _StubProcess:
    def __init__(self, run_event: Optional[asyncio.Event] = None, return_code: int = 0):
        self.pid = 999
        self.returncode: Optional[int] = None
        self._wait_event = run_event or asyncio.Event()
        self.stdout = _StubReader([b""])
        self.stderr = _StubReader([b""])
        self._return_code = return_code

    def terminate(self) -> None:
        self.returncode = self._return_code
        self._wait_event.set()

    def kill(self) -> None:
        self.returncode = self._return_code
        self._wait_event.set()

    async def wait(self) -> int:
        await self._wait_event.wait()
        return int(self.returncode if self.returncode is not None else self._return_code)


@pytest.mark.anyio
async def test_simulation_runner_start_and_stop_transition(tmp_path, monkeypatch):
    run_store = RunStore(log_dir=tmp_path)
    sim_store = SimulationRunStore(max_concurrent_runs=2)
    runner = SimulationRunner(
        run_store=run_store,
        sim_store=sim_store,
        quisp_binary=tmp_path / "quisp",
        execution_dir=tmp_path,
        log_dir=tmp_path / "runs",
        workspace_root=tmp_path,
        max_concurrent_runs=2,
    )

    template_file = tmp_path / "template.ini"
    template_file.write_text("[Config General]\\n")

    wait_event = asyncio.Event()
    process = _StubProcess(run_event=wait_event)

    async def _fake_create_subprocess_exec(*_args, **_kwargs) -> _StubProcess:  # pragma: no cover - monkeypatch target
        return process

    def _fake_build_run_ini(*_args, **kwargs):
        return pathlib.Path(kwargs["output_path"]) if "output_path" in kwargs else pathlib.Path(_args[1])

    monkeypatch.setattr(simulation_runner_module.asyncio, "create_subprocess_exec", _fake_create_subprocess_exec)
    monkeypatch.setattr(simulation_runner_module, "get_template_path", lambda *_args, **_kwargs: template_file)
    monkeypatch.setattr(simulation_runner_module, "build_run_ini", _fake_build_run_ini)

    request = SimRunStartRequest(
        template_id="template.ini",
        config_name="General",
        num_runs=1,
    )
    record = await runner.start_run(request=request)
    assert record.status == SimRunStatus.RUNNING

    stop_record = await runner.stop_run(record.run_id, timeout_seconds=0.1)
    assert stop_record.status == SimRunStatus.TERMINATED

    final_record = await runner.get_run(record.run_id)
    assert final_record.exit_code in (0, None)


@pytest.mark.anyio
async def test_simulation_runner_failure_marks_failed(tmp_path, monkeypatch):
    run_store = RunStore(log_dir=tmp_path)
    sim_store = SimulationRunStore(max_concurrent_runs=1)
    runner = SimulationRunner(
        run_store=run_store,
        sim_store=sim_store,
        quisp_binary=tmp_path / "missing_binary",
        execution_dir=tmp_path,
        log_dir=tmp_path / "runs",
        workspace_root=tmp_path,
        max_concurrent_runs=1,
    )

    template_file = tmp_path / "template.ini"
    template_file.write_text("[Config General]\\n")

    async def _fake_create_subprocess_exec(*_args, **_kwargs):
        raise FileNotFoundError("binary missing")

    def _fake_build_run_ini(*_args, **kwargs):
        return pathlib.Path(kwargs["output_path"]) if "output_path" in kwargs else pathlib.Path(_args[1])

    monkeypatch.setattr(simulation_runner_module.asyncio, "create_subprocess_exec", _fake_create_subprocess_exec)
    monkeypatch.setattr(simulation_runner_module, "get_template_path", lambda *_args, **_kwargs: template_file)
    monkeypatch.setattr(simulation_runner_module, "build_run_ini", _fake_build_run_ini)

    request = SimRunStartRequest(
        template_id="template.ini",
        config_name="General",
        num_runs=1,
    )
    with pytest.raises(OSError):
        await runner.start_run(request=request)

    records = await sim_store.list_runs()
    assert len(records) == 1
    assert records[0].status == SimRunStatus.FAILED


@pytest.mark.anyio
async def test_simulation_runner_build_command_uses_derived_config_and_ned_path(tmp_path, monkeypatch):
    modules_dir = tmp_path / "quisp" / "modules"
    channels_dir = tmp_path / "quisp" / "channels"
    networks_dir = tmp_path / "quisp" / "networks"
    modules_dir.mkdir(parents=True)
    channels_dir.mkdir(parents=True)
    networks_dir.mkdir(parents=True)

    run_store = RunStore(log_dir=tmp_path)
    sim_store = SimulationRunStore(max_concurrent_runs=2)
    captured: dict[str, list[str]] = {}
    quisp_binary = tmp_path / "bin" / "quisp"
    quisp_binary.parent.mkdir(parents=True)
    quisp_binary.write_text("", encoding="utf-8")
    runner = SimulationRunner(
        run_store=run_store,
        sim_store=sim_store,
        quisp_binary=quisp_binary,
        execution_dir=tmp_path,
        log_dir=tmp_path / "runs",
        workspace_root=tmp_path,
        max_concurrent_runs=2,
    )

    template_file = tmp_path / "template.ini"
    template_file.write_text("[Config General]\\n")

    wait_event = asyncio.Event()
    process = _StubProcess(run_event=wait_event)

    async def _fake_create_subprocess_exec(*args, **_kwargs) -> _StubProcess:  # pragma: no cover - monkeypatch target
        captured["command"] = list(map(str, args))
        return process

    def _fake_build_run_ini(*_args, **kwargs):
        return (pathlib.Path(kwargs["output_path"]), "Dashboard_General")

    monkeypatch.setattr(simulation_runner_module.asyncio, "create_subprocess_exec", _fake_create_subprocess_exec)
    monkeypatch.setattr(simulation_runner_module, "get_template_path", lambda *_args, **_kwargs: template_file)
    monkeypatch.setattr(simulation_runner_module, "build_run_ini", _fake_build_run_ini)

    request = SimRunStartRequest(
        template_id="template.ini",
        config_name="General",
        num_runs=2,
        seed_set=123,
    )
    record = await runner.start_run(request=request)
    assert record.status == SimRunStatus.RUNNING

    command = captured.get("command")
    assert command is not None
    assert command[0] == str(quisp_binary)
    assert "-n" in command
    expected_ned = ":".join([str(modules_dir), str(channels_dir), str(networks_dir)])
    assert command[command.index("-n") + 1] == expected_ned
    assert "-c" in command
    assert "Dashboard_General" in command
    assert "-r" in command and command[command.index("-r") + 1] == "2"
    assert "--seed-set" in command and command[command.index("--seed-set") + 1] == "123"

    await runner.stop_run(record.run_id, timeout_seconds=0.1)
