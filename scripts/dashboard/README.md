# QuISP Dashboard (Production + Simulation Control)

This directory provides a production dashboard server and Canvas UI for OMNeT++/QuISP logs.

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
  - `POST /api/sim/runs/{run_id}/stop`
  - `GET /api/sim/runs/{run_id}/log`
  - `GET /api/sim/runs/{run_id}/metrics`

The frontend is served at `/` and available at:
`scripts/dashboard/backend/app/static/index.html`.

## Install dependencies

```bash
cd /Users/shota/GITHUB/quisp
python3 -m pip install -r scripts/dashboard/backend/requirements.txt
```

## Start dashboard server

```bash
cd /Users/shota/GITHUB/quisp
python -m scripts.dashboard.backend.app.main \
  --log-dir scripts/dashboard/runs \
  --host 0.0.0.0 \
  --port 8765
```

Optional:

```bash
--workspace-root /Users/shota/GITHUB/quisp \
--quisp-binary /Users/shota/GITHUB/quisp/quisp \
--max-concurrent-runs 2 \
--run-timeout-seconds 7200 \
--stop-timeout-seconds 10
```

Open:

```text
http://localhost:8765/
```

## Simulation setup from UI

From the left panel:

1. Select a template from `Template`.
2. Select a `Config`.
3. (optional) set `Run Name`, `Num Runs`, `Seed Set`, `sim-time-limit`.
4. (optional) set override lines in `key=value` format.
   Allowed override key characters: alphanumeric, `_`, `.`, `-`, `[`, `]`.
5. Click `Run`.

The started job appears under `実行ジョブ` and is connectable to the same visualization timeline with `ビューへ`.

## 実験開始までの手順（おすすめ）

1. Dashboard起動時に `--log-dir` を書き込み可能なディレクトリ（既定: `scripts/dashboard/runs`）に設定しておく。
2. UIを開く: `http://localhost:8765/`
3. `Template` で `quisp/networks/*.ini` または `quisp/simulations/*.ini` 内のテンプレートを選ぶ。
4. `Config` から実行コンフィグを選ぶ。
5. `Num Runs`、`Seed Set`、`sim-time-limit` を必要に応じて設定。
6. `Run` を押す。
7. `実行ジョブ` の該当行で `ビューへ` を押して同じ run_id のイベント再生を開始。
8. `サブグラフ再計算` で `Focus`/`Hops`/`ノード正規表現` を切り替える。
9. 完了したら `Stop Selected` / `Stop` で終了要求を送る。状態は `running -> terminated` など遷移。

### 最短の実験サンプル

- 既存ログを可視化だけ行う場合: 
  - まず `layout`/テンプレート起動はせず、`--log-dir` 配下に `run.jsonl` を置く。
  - `実行一覧` 更新で run が検出されれば、`run_id` を選択して再生開始。
- まず1件だけUIで起動して挙動確認する場合:
  - `Num Runs: 1`、`Seed Set` 空、`sim-time-limit` 空で `Run`。
  - 1分以上進まない場合は、`maxNodes` を下げて表示を軽くして再試行。

### コマンド起動確認（API経由）

```bash
# テンプレート一覧
curl http://localhost:8765/api/sim/templates | jq

# 実行開始
curl -X POST http://localhost:8765/api/sim/runs \
  -H 'content-type: application/json' \
  -d '{
    "template_id":"networks/simple.ini",
    "config_name":"General",
    "num_runs":1
  }' | jq
```

上記は `template_id` を環境に合わせて置換してください（`/api/sim/templates` で実際のIDを確認）。

### 最短実験シナリオ（コマンド主導）

```bash
# 1) ダッシュボード起動
python -m scripts.dashboard.backend.app.main --log-dir scripts/dashboard/runs --port 8765

# 2) テンプレート/実行設定取得
curl -s http://localhost:8765/api/sim/templates | jq '.[0:5]'

# 3) 1回だけ実行
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
# 4) run_id を確認して状態監視
RUN_ID=... # 上のPOSTで返った run_id を代入
watch -n 5 "curl -s http://localhost:8765/api/sim/runs/$RUN_ID | jq '.status,.sim_time_limit,.metrics.lines_read'"

# 5) UIで同じrun_idを可視化
open http://localhost:8765/   # ブラウザで「実行ジョブ」->「ビューへ」

# 6) 収束後の停止（必要時）
curl -X POST http://localhost:8765/api/sim/runs/$RUN_ID/stop

# 7) ログ取得
curl -s http://localhost:8765/api/sim/runs/$RUN_ID/log | jq '.tail'
```

注記:
- `TemplateIDHere` は `curl .../api/sim/templates` の実体で置換してください。
- `open` は macOS向けコマンドです。Linuxは `xdg-open` など環境に合わせて置き換え。
- `watch` コマンドが使えない環境では5秒間隔でGETを手動実行してください。

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
- Stop uses graceful SIGTERM and SIGKILL fallback (timeout controlled via `--stop-timeout-seconds`).
- This implementation keeps log visualization and simulation control in one process and shares run IDs between APIs.
- Existing logs are discovered from `--log-dir` recursively; `run.jsonl` under each run directory is accepted and mapped by run directory name.
