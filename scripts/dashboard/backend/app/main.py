from __future__ import annotations

import argparse
import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config_templates import TemplateNotFoundError, list_templates, template_with_configs
from .models import flatten_event_types
from .sim_models import (
    SimRunInfo,
    SimRunMetrics,
    SimRunStartRequest,
    SimRunStartResponse,
)
from .sim_store import SimulationRunStore
from .simulation_runner import SimulationRunner
from .store import RunStore


def _build_project_root() -> Path:
    current = Path(__file__).resolve()
    markers = ("pyproject.toml", "build.toml", "tbump.toml", ".git", "Makefile", "README.md")
    for candidate in [current, *current.parents]:
        for marker in markers:
            if (candidate / marker).exists():
                if (candidate / "scripts" / "dashboard").exists() or marker in {"pyproject.toml", ".git", "build.toml", "tbump.toml"}:
                    return candidate
    # fallback for custom checkout layouts
    for candidate in [current, *current.parents]:
        if candidate.name in {"quisp", "GITHUB"}:
            return candidate
    return current.parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    store: RunStore = app.state.store
    await store.discover_runs()
    yield


async def _to_sim_info_list(sim_store: SimulationRunStore, run_store: RunStore, records) -> list[SimRunInfo]:
    result: list[SimRunInfo] = []
    for record in records:
        base = record.to_dict()
        try:
            await run_store.refresh_run(record.run_id)
        except KeyError:
            pass
        base["event_count"] = run_store.get_event_count(record.run_id)
        result.append(SimRunInfo(**base))
    return result


def create_app(
    *,
    log_dir: Path,
    allow_origins: Optional[List[str]] = None,
    quisp_binary: Optional[Path] = None,
    workspace_root: Optional[Path] = None,
    max_concurrent_runs: int = 2,
    run_timeout_seconds: float = 7200.0,
    stop_timeout_seconds: float = 10.0,
) -> FastAPI:
    app = FastAPI(title="QuISP Dashboard API", lifespan=lifespan)
    router = APIRouter(prefix="/api")
    store = RunStore(log_dir=log_dir)
    sim_store = SimulationRunStore(max_concurrent_runs=max_concurrent_runs)
    app.state.store = store
    app.state.sim_store = sim_store

    workspace_root = workspace_root or _build_project_root()
    quisp_binary = quisp_binary or (workspace_root / "quisp")
    simulation_runner = SimulationRunner(
        run_store=store,
        sim_store=sim_store,
        quisp_binary=quisp_binary,
        execution_dir=log_dir,
        log_dir=log_dir,
        workspace_root=workspace_root,
        max_concurrent_runs=max_concurrent_runs,
        run_timeout_seconds=run_timeout_seconds,
        stop_timeout_seconds=stop_timeout_seconds,
    )
    app.state.simulation_runner = simulation_runner
    app.state.workspace_root = workspace_root

    if allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allow_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @router.get("/runs")
    async def list_runs():
        await store.discover_runs()
        return [run.to_dict() for run in store.list_runs()]

    @router.get("/runs/{run_id}/topology")
    async def get_topology(
        run_id: str,
        max_nodes: int = Query(default=3000, ge=1, le=200000),
    ):
        try:
            await store.refresh_run(run_id)
            return await store.get_topology(run_id, max_nodes=max_nodes)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @router.get("/runs/{run_id}/events")
    async def get_events(
        run_id: str,
        from_event_id: int = Query(default=0, ge=0),
        from_time: Optional[float] = Query(default=None, ge=0),
        limit: int = Query(default=5000, ge=1, le=50000),
        types: Optional[str] = None,
    ):
        type_filter = flatten_event_types(types)
        try:
            window = await store.get_events(
                run_id,
                from_event_id=from_event_id,
                from_time=from_time,
                limit=limit,
                types=type_filter,
            )
            return window.to_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @router.get("/runs/{run_id}/events/stream")
    async def stream_events(
        run_id: str,
        from_cursor: int = Query(default=0, ge=0),
        limit: int = Query(default=2000, ge=1, le=50000),
        types: Optional[str] = None,
        timeout: float = Query(default=1.0, ge=0.1, le=10.0),
    ):
        type_filter = flatten_event_types(types)
        deadline = asyncio.get_running_loop().time() + timeout
        try:
            while True:
                window = await store.get_events(
                    run_id=run_id,
                    from_event_id=from_cursor,
                    limit=limit,
                    types=type_filter,
                )
                if window.events:
                    return window.to_dict()
                if asyncio.get_running_loop().time() >= deadline:
                    return {
                        "window_id": f"{run_id}:{from_cursor}",
                        "frame_index": from_cursor // limit,
                        "events": [],
                        "state_delta": {"count": 0, "from_event_id": from_cursor},
                        "next_cursor": from_cursor,
                        "has_more": False,
                    }
                await asyncio.sleep(0.2)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @router.get("/runs/{run_id}/subgraph")
    async def get_subgraph(
        run_id: str,
        focus: Optional[str] = None,
        hops: int = Query(default=0, ge=0, le=20),
        max_nodes: int = Query(default=3000, ge=1, le=200000),
        node_regex: Optional[str] = None,
    ):
        if node_regex:
            import re

            try:
                re.compile(node_regex)
            except re.error as exc:
                raise HTTPException(status_code=400, detail=f"invalid node_regex: {exc}")
        try:
            return await store.get_subgraph(
                run_id,
                focus=focus,
                hops=hops,
                max_nodes=max_nodes,
                node_regex=node_regex,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @router.get("/sim/templates")
    async def list_sim_templates():
        try:
            templates = list_templates(project_root=workspace_root)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        return [template.dict() for template in templates]

    @router.get("/sim/runs")
    async def list_sim_runs() -> list[SimRunInfo]:
        runs = await simulation_runner.list_runs()
        return await _to_sim_info_list(sim_store, store, runs)

    @router.post("/sim/runs")
    async def start_sim_run(request: SimRunStartRequest) -> SimRunStartResponse:
        template_info = template_with_configs(request.template_id, project_root=workspace_root)
        config_names = template_info.get("config_names", [])
        if not request.workdir:
            default_workdir = template_info.get("default_workdir")
            if default_workdir:
                request_dict = request.dict()
                request_dict["workdir"] = str(default_workdir)
                request = SimRunStartRequest(**request_dict)
        if request.config_name not in config_names:
            raise HTTPException(status_code=400, detail=f"config_name not found in template: {request.config_name}")

        if request.workdir:
            requested_workdir = Path(request.workdir)
            if not requested_workdir.is_absolute():
                requested_workdir = (workspace_root / requested_workdir).resolve()
            else:
                requested_workdir = requested_workdir.resolve()
            try:
                requested_workdir.relative_to(workspace_root)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="workdir must be inside workspace_root") from exc
            if not requested_workdir.exists():
                raise HTTPException(status_code=400, detail=f"workdir does not exist: {request.workdir}")
            request_dict = request.dict()
            request_dict["workdir"] = str(requested_workdir)
            request = SimRunStartRequest(**request_dict)

        try:
            record = await simulation_runner.start_run(request=request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except TemplateNotFoundError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"failed to start simulation: {exc}")

        return SimRunStartResponse(
            run_id=record.run_id,
            status=record.status,
            log_path=str(record.log_path),
            dashboard_run_id=record.dashboard_run_id,
        )

    @router.get("/sim/runs/{run_id}")
    async def get_sim_run(run_id: str) -> SimRunInfo:
        try:
            record = await simulation_runner.get_run(run_id)
            return (await _to_sim_info_list(sim_store, store, [record]))[0]
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @router.post("/sim/runs/{run_id}/stop")
    async def stop_sim_run(run_id: str, timeout_seconds: float = Query(default=10.0, ge=0.1, le=600.0)) -> SimRunInfo:
        try:
            record = await simulation_runner.stop_run(run_id, timeout_seconds=timeout_seconds)
            return (await _to_sim_info_list(sim_store, store, [record]))[0]
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @router.get("/sim/runs/{run_id}/log")
    async def get_sim_run_log(
        run_id: str,
        limit: int = Query(default=200, ge=1, le=2000),
        mode: str = Query(default="all"),
    ):
        mode = str(mode).lower()
        if mode not in {"all", "stdout", "stderr"}:
            raise HTTPException(status_code=400, detail="mode must be all, stdout, or stderr")
        try:
            return {
                "run_id": run_id,
                "mode": mode,
                "lines": await simulation_runner.get_logs(run_id, limit=limit, mode=mode),
            }
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @router.get("/sim/runs/{run_id}/metrics")
    async def get_sim_metrics(run_id: str):
        try:
            return SimRunMetrics(**await simulation_runner.get_metrics(run_id)).dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @router.get("/metrics")
    async def get_metrics():
        return store.get_metrics()

    @router.websocket("/runs/{run_id}/stream")
    async def stream_ws(websocket: WebSocket, run_id: str, from_cursor: int = 0, types: Optional[str] = None):
        await websocket.accept()
        store.metrics.websocket_clients += 1
        cursor = max(0, from_cursor)
        type_filter = flatten_event_types(types)
        try:
            while True:
                window = await store.get_events(run_id=run_id, from_event_id=cursor, limit=5000, types=type_filter)
                if window.events:
                    cursor = window.next_cursor
                    await websocket.send_json(window.to_dict())
                await asyncio.sleep(0.25)
        except KeyError as exc:
            await websocket.close(code=1008, reason=str(exc))
        except WebSocketDisconnect:
            pass
        finally:
            store.metrics.websocket_clients = max(0, store.metrics.websocket_clients - 1)

    app.include_router(router)

    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount(
            "/",
            StaticFiles(directory=str(static_dir), html=True),
            name="static",
        )

    return app


def run_server(
    log_dir: Path,
    host: str,
    port: int,
    allow_origins: Optional[List[str]],
    quisp_binary: Optional[Path],
    workspace_root: Path,
    max_concurrent_runs: int,
    run_timeout_seconds: float,
    stop_timeout_seconds: float,
) -> None:
    import uvicorn

    app = create_app(
        log_dir=log_dir,
        allow_origins=allow_origins,
        quisp_binary=quisp_binary,
        workspace_root=workspace_root,
        max_concurrent_runs=max_concurrent_runs,
        run_timeout_seconds=run_timeout_seconds,
        stop_timeout_seconds=stop_timeout_seconds,
    )
    uvicorn.run(app, host=host, port=port)


def parse_args() -> argparse.Namespace:
    cwd = _build_project_root()
    parser = argparse.ArgumentParser(description="QuISP dashboard API and static viewer")
    parser.add_argument("--log-dir", required=False, default=str(cwd / "scripts" / "dashboard" / "runs"), help="Directory containing QuISP json log files")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=8765, help="Bind port")
    parser.add_argument(
        "--allow-origin",
        action="append",
        default=None,
        help="Allowed CORS origin. Can be repeated for multiple origins.",
    )
    parser.add_argument("--workspace-root", default=str(cwd), help="Workspace root for template discovery and simulation execution")
    parser.add_argument("--quisp-binary", default=str(cwd / "quisp"), help="Path to quisp binary")
    parser.add_argument("--max-concurrent-runs", type=int, default=int(os.getenv("Q_DASH_MAX_CONCURRENT_RUNS", "2")))
    parser.add_argument("--run-timeout-seconds", type=float, default=float(os.getenv("Q_DASH_RUN_TIMEOUT_SECONDS", "7200")))
    parser.add_argument("--stop-timeout-seconds", type=float, default=float(os.getenv("Q_DASH_STOP_TIMEOUT_SECONDS", "10")))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    allow_origins = args.allow_origin if args.allow_origin else None
    run_server(
        log_dir=Path(args.log_dir),
        host=args.host,
        port=args.port,
        allow_origins=allow_origins,
        quisp_binary=Path(args.quisp_binary),
        workspace_root=Path(args.workspace_root),
        max_concurrent_runs=max(1, args.max_concurrent_runs),
        run_timeout_seconds=max(0.0, args.run_timeout_seconds),
        stop_timeout_seconds=max(0.1, args.stop_timeout_seconds),
    )


if __name__ == "__main__":
    main()
