# QuISP Dashboard (Production + Simulation Control)

This directory provides a production dashboard server and Canvas UI for OMNeT++/QuISP logs.

> **日本語版**: [README.ja.md](README.ja.md) を参照してください。

- Visual APIs:
  - `GET /api/runs` / `GET /api/runs/{run_id}/topology`
  - `GET /api/runs/{run_id}/events` / `.../events/stream`
  - `GET /api/runs/{run_id}/subgraph`
  - `WS /api/runs/{run_id}/stream`
  - `GET /api/metrics`, `GET /metrics`
- Simulation APIs:
  - `GET /api/sim/templates`
  - `GET /api/sim/runs`
  - `POST /api/sim/runs`
  - `GET /api/sim/runs/{run_id}`
  - `GET /api/sim/runs/{run_id}/summary`
  - `GET /api/sim/runs/{run_id}/timeseries`
  - `POST /api/sim/runs/{run_id}/stop`
  - `GET /api/sim/runs/{run_id}/log`
  - `GET /api/sim/runs/{run_id}/metrics`
- Experiment APIs:
  - `GET /api/experiments/catalog`
  - `GET /api/experiments/catalog/schema`
  - `POST /api/experiments/compare`

The frontend is served at `/` and available at:
`scripts/dashboard/backend/app/static/index.html`.

## Install dashboard dependencies

```bash
cd <repo-root>
python3 -m pip install -r scripts/dashboard/backend/requirements.txt
```

## Install QuTiP runtime for dashboard-triggered QuISP runs

Use a repo-local virtualenv so all developers point QuISP at the same Python runtime.

```bash
cd <repo-root>
make qutip-env
make qutip-check
```

This creates:

- `<repo-root>/.venv-qutip`
- `<repo-root>/requirements-qutip.txt`

At runtime, QuISP will use:

```text
QUTIP_PYTHON_EXECUTABLE=<repo-root>/.venv-qutip/bin/python
```

if you start the dashboard with the provided helper below.

## Start dashboard server

Recommended:

```bash
cd <repo-root>
make dashboard-backend
```

This will:

1. use `<repo-root>/quisp/quisp` as the QuISP binary
2. start the dashboard on `127.0.0.1:8765`
3. point QuISP's qutip backend at `<repo-root>/.venv-qutip/bin/python`

Direct script entrypoint:

```bash
cd <repo-root>
./scripts/dashboard/run_backend.sh
```

Manual entrypoint:

```bash
cd <repo-root>
QUTIP_PYTHON_EXECUTABLE=<repo-root>/.venv-qutip/bin/python \
PYTHONPATH=<repo-root> \
python3 -m scripts.dashboard.backend.app.main \
  --workspace-root <repo-root> \
  --quisp-binary <repo-root>/quisp/quisp \
  --log-dir <repo-root>/scripts/dashboard/runs \
  --host 127.0.0.1 \
  --port 8765 \
  --audit-log <repo-root>/scripts/dashboard/dashboard_audit.log
```

Optional:

```bash
--workspace-root <repo-root> \
--quisp-binary <repo-root>/quisp \
--max-concurrent-runs 2 \
--run-timeout-seconds 7200 \
--stop-timeout-seconds 10
```

Open:

```text
http://localhost:8765/
```

For audit log:

```bash
tail -f <repo-root>/scripts/dashboard/dashboard_audit.log
```

## Simulation setup from UI

From the left panel:

1. Select a template from `Template`.
2. Select a `Config`.
3. (optional) set `Run Name`, `Num Runs`, `Seed Set`, `sim-time-limit`.
4. (optional) set override lines in `key=value` format.
   Allowed override key characters: alphanumeric, `_`, `.`, `-`, `[`, `]`.
5. Click `Run`.

The started job appears in the running-jobs list (`実行ジョブ`) and can be connected to the same visualization timeline via the `ビューへ` (To View) link.

If `Run` fails with a qutip import error, verify:

```bash
make qutip-check
```

and make sure the dashboard was started via `make dashboard-backend` or `./scripts/dashboard/run_backend.sh`.

## Structured experiment mode

The dashboard now supports a curated structured mode on top of the existing raw launcher.

- `Experiment Profile` picks a profile with typed inputs and recommended result metrics.
- `Template / Config` still remains visible and is used as the legacy fallback path.
- `Core Inputs` exposes frequently tuned parameters.
- `Advanced Inputs` exposes the remaining profile-specific parameters.
- `Raw Overrides` still exists and has the highest precedence.

Current curated profiles:

- `two_node_mim_smoke`
- `verify_replay_timeline`
- `linear_five_mm_entanglement_swapping`
- `measurement7000_simple_mim`

Profile notes:

- `two_node_mim_smoke`
  - default backend: profile default is inherited from the selected config unless overridden
  - intended result: setup/request metrics such as `setup_success_ratio` and `setup_latency_s`
  - tuned default: `traffic.request_rate_hz=1.0` so the summary is not flooded with requests in a 2s smoke run
- `verify_replay_timeline`
  - default backend: `graph_state`
  - default `sim_time_limit`: `10.0s`
  - default `traffic.request_rate_hz`: `2.0`
  - intended result: confirm sim-time seek in `Replay`, cluster progression, and event emission starting at `t=0`
  - caveat: this profile prioritizes Replay UI verification over checking bell-pair activity in `Results`
- `linear_five_mm_entanglement_swapping`
  - default backend: `graph_state`
  - default `sim_time_limit`: `12.0s`
  - intended result: bell-pair activity metrics such as `bellpair_generation_rate_per_s` and `bellpair_inventory_peak`
  - caveat: this config does not normally emit application request/setup events, so `setup_success_ratio` is expected to stay unavailable
- `measurement7000_simple_mim`
  - intended result: large-topology launch/regression checks; metric availability depends strongly on the selected purification/backend settings

Override precedence is fixed as:

1. profile defaults
2. structured `parameter_values`
3. explicit raw `overrides`

If a `Template / Config` pair has no curated profile, the UI falls back to legacy mode and keeps only the execution-oriented structured fields.

## Experiment result summary

Each run directory can now contain experiment artifacts in addition to `run.jsonl`.

- `experiment_spec.json`
- `resolved_overrides.json`
- `experiment_summary.json`
- `experiment_timeseries.jsonl`

Summary metrics are computed by the backend, not in the browser. The initial result set focuses on:

- `setup_success_ratio`
- `setup_latency_s`
- `bellpair_generation_rate_per_s`
- `bellpair_inventory_peak`
- `bellpair_inventory_mean`
- `photon_loss_rate_per_s`
- `link_fidelity`
- `link_bellpair_rate_per_s`
- `failure_reason_breakdown`

`setup_success_ratio` is intentionally defined as setup-phase success, not application-level completion:

- submitted: a request was emitted from the source side
- success: setup was accepted by the connection manager
- reject: setup was explicitly rejected

Unavailable metrics are returned as unavailable, not coerced to zero.

Two practical interpretations matter in the current implementation:

- `two_node_mim_smoke` is the profile to use when you want request/setup metrics.
- `verify_replay_timeline` is the profile to use when you want early replayable events and time-seek verification.
- `linear_five_mm_entanglement_swapping` is the profile to use when you want bell-pair activity and topology animation, not request/setup success.

## Experiment comparison

Use `比較+` (Compare+) from the run list to add runs to the compare queue. The compare drawer fetches:

- per-run scalar metrics
- distribution summaries such as `mean / p50 / p95 / p99`
- availability warnings when a metric is not present for one of the runs

The compare API is also available directly:

```bash
curl -X POST http://localhost:8765/api/experiments/compare \
  -H 'content-type: application/json' \
  -d '{
    "run_ids": ["run_a", "run_b"],
    "metric_ids": ["setup_success_ratio", "link_fidelity"]
  }' | jq
```

## Classical packet visualization taxonomy

The dashboard now treats classical traffic in three separate categories:

- `classical_packet_hop`
  - emitted from `<repo-root>/quisp/modules/Common/Router.cc`
  - represents one actual hop sent to `toQueue`
  - used as the only classical edge animation source
- `classical_packet_deliver_local`
  - emitted from `Router` when a classical packet is handed to `toApp`, `cmPort`, `rePort`, `hmPort`, or `rdPort`
  - rendered as a node-local pulse
- summary / metrics / metadata
  - `experiment_request_*`
  - `experiment_link_quality_sample`
  - `topology_snapshot`
  - these are not packet animations; they are used in Results, key moments, and summaries

Canonical classical packet families are:

- `connection_setup`
- `ruleset_forwarding`
- `swapping`
- `purification`
- `link_generation`
- `tomography`
- `routing`
- `unknown`

Family visibility defaults:

- `Replay`
  - shows `connection_setup`, `ruleset_forwarding`, `swapping`, `purification`, `link_generation`
  - hides `routing` and `tomography` by default
- `Monitor core`
  - includes `connection_setup`, `ruleset_forwarding`, `swapping`, `purification`, `link_generation`, `flying`, `bellpairs`, `loss`, `link_quality`
  - does not include `routing`, `tomography`, or `unknown` unless explicitly selected in the filter

Protocol-level classical packets such as `SwappingResult`, `PurificationResult`, `MSMResult`, and `LinkTomography*` are only drawn when the run contains canonical Router-level packet events. Old runs without `classical_packet_hop` / `classical_packet_deliver_local` keep their summaries and raw logs, but do not synthesize fake packet paths from generic `handleMessage` traces.

This means old runs that do not contain `classical_packet_hop` / `classical_packet_deliver_local` will no longer fake classical packet animation from generic `handleMessage` logs. The UI keeps raw logs and summaries, but avoids drawing misleading packet paths.

## Known validated runs

These runs were checked against the current implementation on March 7, 2026.

- `Two-node MIM smoke`
  - representative run: `run_1772837145074_6d6a8c`
  - expected summary shape:
    - `request_submitted_count > 0`
    - `request_setup_success_count > 0`
    - `setup_success_ratio` available
- `Linear five MM default`
  - representative run: `run_1772837875887_33e37e`
  - expected summary shape:
    - `bellpair_generated_count > 0`
    - `bellpair_generation_rate_per_s` available
    - `bellpair_inventory_peak > 0`
    - `setup_success_ratio` unavailable

## Recommended steps to start an experiment

1. When starting the dashboard, set `--log-dir` to a writable directory (default: `scripts/dashboard/runs`).
2. Open the UI: `http://localhost:8765/`
3. Pick a template from `Template` (entries from `quisp/networks/*.ini` or `quisp/simulations/*.ini`).
4. Pick a `Config`.
5. Set `Num Runs`, `Seed Set`, and `sim-time-limit` as needed.
6. Click `Run`.
7. From the corresponding row in the running-jobs list (`実行ジョブ`), click `ビューへ` (To View) to start event playback for the same `run_id`.
8. Use `サブグラフ再計算` (Recompute subgraph) to switch `Focus` / `Hops` / node regex.
9. When done, send a stop request via `Stop Selected` / `Stop`. State transitions like `running -> terminated`.

### Quickest experiment samples

- Visualize an existing log only:
  - Skip `layout` / template launching and place `run.jsonl` under `--log-dir`.
  - Once the run appears after refreshing the run list, select the `run_id` and start playback.
- Try one run from the UI first to check behavior:
  - Set `Num Runs: 1`, leave `Seed Set` and `sim-time-limit` empty, then click `Run`.
  - If it does not progress for over a minute, lower `maxNodes` to lighten rendering and retry.

### Command-line launch check (via API)

```bash
# list templates
curl http://localhost:8765/api/sim/templates | jq

# start a run
curl -X POST http://localhost:8765/api/sim/runs \
  -H 'content-type: application/json' \
  -d '{
    "template_id":"networks/simple.ini",
    "config_name":"General",
    "num_runs":1
  }' | jq
```

Replace `template_id` to match your environment (find the actual ID via `/api/sim/templates`).

### Shortest experiment scenario (command-driven)

```bash
# 1) start the dashboard
python -m scripts.dashboard.backend.app.main --log-dir scripts/dashboard/runs --port 8765

# 2) fetch templates / run configs
curl -s http://localhost:8765/api/sim/templates | jq '.[0:5]'

# 3) execute once
curl -s -X POST http://localhost:8765/api/sim/runs \
  -H 'content-type: application/json' \
  -d '{
    "template_id": "TemplateIDHere",
    "config_name": "General",
    "run_name": "exp-smoke",
    "num_runs": 1,
    "seed_set": "1"
  }' | jq
```

```bash
# 4) capture run_id and watch status
RUN_ID=... # paste the run_id returned by the POST above
watch -n 5 "curl -s http://localhost:8765/api/sim/runs/$RUN_ID | jq '.status,.sim_time_limit,.metrics.lines_read'"

# 5) visualize the same run_id from the UI
open http://localhost:8765/   # in browser: running-jobs list -> To View

# 6) stop after convergence (if needed)
curl -X POST http://localhost:8765/api/sim/runs/$RUN_ID/stop

# 7) fetch the log
curl -s http://localhost:8765/api/sim/runs/$RUN_ID/log | jq '.tail'
```

Notes:
- Replace `TemplateIDHere` with an actual ID from `curl .../api/sim/templates`.
- `open` is a macOS command. On Linux, substitute with `xdg-open` or your environment's equivalent.
- If `watch` is not available, run the GET manually every 5 seconds.

### Simulation API Notes

- `POST /api/sim/runs` accepts template/ini and config; run_id format is `run_<unixms>_<token>`.
- `workdir` omitted → uses template directory by default.
- State transitions: `queued -> starting -> running -> (finished | failed | terminated)`.
- `POST /api/sim/runs/{run_id}/stop` attempts SIGTERM -> SIGKILL fallback (or timeout in `--stop-timeout-seconds`).

## Notes

- Template search is limited to:
  - `quisp/networks/*.ini`
  - `quisp/simulations/*.ini`
- Simulation log path is written under `scripts/dashboard/runs/{run_id}/run.jsonl`.
- Process stdout/stderr are also persisted under `scripts/dashboard/runs/{run_id}/stdout.log` and `scripts/dashboard/runs/{run_id}/stderr.log`.
- Stop uses graceful SIGTERM and SIGKILL fallback (timeout controlled via `--stop-timeout-seconds`).
- This implementation keeps log visualization and simulation control in one process and shares run IDs between APIs.
- Existing logs are discovered from `--log-dir` recursively; `run.jsonl` under each run directory is accepted and mapped by run directory name.

## Viewer modes

The dashboard viewer now has three distinct modes.

### Monitor

`Monitor` is the default for `queued`, `starting`, and `running` runs.
It does not replay raw events. Instead, it polls aggregated activity from `GET /api/runs/{run_id}/activity` once per second and renders:

- node activity heat
- edge activity heat
- key moments
- stream health
- `sim進行倍率` (sim-time advance ratio): `delta(sim_time) / delta(real_time)`
- `可視イベント密度` (visible event density): `dashboard-visible events / sim-second`

`LIVE` in this mode means "follow the live edge". Moving the timeline away from the end turns the view into historical activity inspection instead of raw event playback.

### Replay

`Replay` is the detailed raw-event analysis mode. It keeps the existing event APIs:

- `GET /api/runs/{run_id}/events`
- `GET /api/runs/{run_id}/events/stream`
- `WS /api/runs/{run_id}/stream`

Replay adds viewer-side speed metrics:

- `実効sim再生倍率` (effective sim playback rate): observed `delta(displayed sim_time) / delta(real_time)`
- `再生イベント速度` (replay event speed): replayed events per wall-clock second
- `可視イベント密度` (visible event density): visible logged events per sim-second in the active analysis window

Use this mode when you need to step through `flying_qubit_*`, `BellPair*`, or request/setup events in detail.

### Results

`Results` is the default for completed runs when summary artifacts are available. It is intended for experiment evaluation, not playback. In addition to experiment summaries and compare tables, it now shows viewer diagnostics derived from `GET /api/runs/{run_id}/activity/summary`:

- `可視イベント密度 mean` (visible event density mean)
- `可視イベント密度 p95` (visible event density p95)
- `可視イベント密度 peak` (visible event density peak)

## Activity APIs

Two new APIs support the monitor and viewer diagnostics surfaces.

### `GET /api/runs/{run_id}/activity`

Returns an `ActivitySnapshot` for a cursor-anchored lookback window.
It includes:

- `global_totals`
- `bins`
- `view_node_activity`
- `view_edge_activity`
- `key_moments`

Key query parameters:

- `anchor_cursor`
- `window_s`
- `lookback_s`
- `classes`
- `focus`
- `hops`
- `max_nodes`
- `node_regex`

### `GET /api/runs/{run_id}/activity/summary`

Returns whole-run viewer diagnostics for visible event density, including:

- `visible_event_density.mean`
- `visible_event_density.p95`
- `visible_event_density.p99`
- `peak_windows`
- `global_counts_by_class`

## Mode selection rules

The UI chooses the default viewer mode automatically.

- `queued | starting | running` -> `Monitor`
- `finished | failed | terminated` with summary -> `Results`
- `finished | failed | terminated` without summary -> `Replay`

This prevents finished runs from being shown as if they were stalled live streams.

## Recommended verification experiments

If you want to confirm both the simulator and the dashboard quickly, use the following two curated profiles in order.

### 1. `verify_two_node_setup`

Purpose:
- confirm launcher -> simulator -> summary artifact -> Results path
- confirm request/setup metrics are non-empty
- confirm short runs finish cleanly

Defaults:
- template: `quisp/simulations/two_nodes.ini`
- config: `two_node_MIM`
- backend: `graph_state`
- sim-time-limit: `4.0s`
- request rate: `1.0 Hz`

What you should see:
- `request_submitted_count`
- `request_setup_success_count`
- `setup_success_ratio`
- `setup_latency_s`

Use this first when you want a fast sanity check.

### 2. `verify_linear_five_activity`

Purpose:
- confirm topology rendering in `Monitor`
- confirm heat view and key moments
- confirm `Replay` on a non-trivial run
- confirm bell-pair activity metrics in `Results`

Defaults:
- template: `quisp/networks/omnetpp.ini`
- config: `EntanglementSwapping_Linear_FIVE_MM_Test`
- backend: `graph_state`
- sim-time-limit: `12.0s`
- emission success probability: `1.0`

What you should see:
- `1-2-3-4-5` line topology
- active node/edge heat in `Monitor`
- bell-pair bursts and terminal key moments
- `bellpair_generated_count`
- `bellpair_generation_rate_per_s`
- `bellpair_inventory_peak`

Use this second when you want to validate the GUI itself.

### 3. `verify_qutip_backend`

Purpose:
- confirm repo-local QuTiP environment wiring
- confirm `qutip_density_matrix` backend launches without import failure
- confirm dashboard launch path works even when the backend is slower than `graph_state`

Defaults:
- template: `quisp/simulations/two_nodes.ini`
- config: `two_node_MIM`
- backend: `qutip_density_matrix`
- sim-time-limit: `4.0s`
- request rate: `0.5 Hz`

What you should see:
- clean run startup with `qutip` backend selected
- `request_submitted_count`
- `request_setup_success_count`
- no `ModuleNotFoundError: No module named 'qutip'`

Use this after the first two profiles if you want to verify the QuTiP execution path specifically.
