# QuISP ダッシュボード（本番＋シミュレーション制御）

このディレクトリは、OMNeT++/QuISP のログを扱う本番ダッシュボードサーバと Canvas UI を提供します。

> **English version**: see [README.md](README.md).

- 可視化 API:
  - `GET /api/runs` / `GET /api/runs/{run_id}/topology`
  - `GET /api/runs/{run_id}/events` / `.../events/stream`
  - `GET /api/runs/{run_id}/subgraph`
  - `WS /api/runs/{run_id}/stream`
  - `GET /api/metrics`, `GET /metrics`
- シミュレーション API:
  - `GET /api/sim/templates`
  - `GET /api/sim/runs`
  - `POST /api/sim/runs`
  - `GET /api/sim/runs/{run_id}`
  - `GET /api/sim/runs/{run_id}/summary`
  - `GET /api/sim/runs/{run_id}/timeseries`
  - `POST /api/sim/runs/{run_id}/stop`
  - `GET /api/sim/runs/{run_id}/log`
  - `GET /api/sim/runs/{run_id}/metrics`
- 実験 API:
  - `GET /api/experiments/catalog`
  - `GET /api/experiments/catalog/schema`
  - `POST /api/experiments/compare`

フロントエンドは `/` で配信され、実体は `scripts/dashboard/backend/app/static/index.html` にあります。

以下、`<repo-root>` は QuISP リポジトリのルート（このリポジトリを clone したパス）を指します。

## ダッシュボード依存のインストール

```bash
cd <repo-root>
python3 -m pip install -r scripts/dashboard/backend/requirements.txt
```

## ダッシュボード起動用 QuTiP ランタイムのインストール

開発者全員が QuISP を同じ Python ランタイムに向けるため、リポジトリ内 venv を使う方法を推奨します。

```bash
cd <repo-root>
make qutip-env
make qutip-check
```

これにより以下が作成されます:

- `<repo-root>/.venv-qutip`
- `<repo-root>/requirements-qutip.txt`

下記のヘルパースクリプト経由でダッシュボードを起動した場合、QuISP は実行時に次の Python を使います:

```text
QUTIP_PYTHON_EXECUTABLE=<repo-root>/.venv-qutip/bin/python
```

## ダッシュボードサーバの起動

推奨:

```bash
cd <repo-root>
make dashboard-backend
```

これにより:

1. `<repo-root>/quisp/quisp` を QuISP バイナリとして使用
2. ダッシュボードを `127.0.0.1:8765` で起動
3. QuISP の qutip バックエンドを `<repo-root>/.venv-qutip/bin/python` に向ける

スクリプト直接起動:

```bash
cd <repo-root>
./scripts/dashboard/run_backend.sh
```

手動起動:

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

任意オプション:

```bash
--workspace-root <repo-root> \
--quisp-binary <repo-root>/quisp/quisp \
--max-concurrent-runs 2 \
--run-timeout-seconds 7200 \
--stop-timeout-seconds 10
```

ブラウザで開く:

```text
http://localhost:8765/
```

監査ログ:

```bash
tail -f <repo-root>/scripts/dashboard/dashboard_audit.log
```

## UI からのシミュレーション設定

左パネルから:

1. `Template` でテンプレートを選択。
2. `Config` を選択。
3. （任意）`Run Name`、`Num Runs`、`Seed Set`、`sim-time-limit` を設定。
4. （任意）`key=value` 形式で override 行を設定。許可されるキー文字は英数字、`_`、`.`、`-`、`[`、`]`。
5. `Run` を押す。

起動したジョブは `実行ジョブ` に表示され、`ビューへ` で同じ可視化タイムラインに接続できます。

`Run` が qutip の import エラーで失敗した場合は次を確認してください:

```bash
make qutip-check
```

加えて、ダッシュボードを `make dashboard-backend` もしくは `./scripts/dashboard/run_backend.sh` から起動したことも確認してください。

## 構造化実験モード

ダッシュボードは、既存の生ランチャーに加えてキュレーション済みの構造化モードをサポートします。

- `Experiment Profile` で型付き入力と推奨結果メトリクスを持つプロファイルを選択。
- `Template / Config` も従来どおり表示され、レガシーフォールバック経路として機能。
- `Core Inputs` には頻繁にチューニングするパラメータを表示。
- `Advanced Inputs` にはプロファイル固有の残りパラメータを表示。
- `Raw Overrides` も引き続き存在し、最高優先度を持つ。

現在のキュレーション済みプロファイル:

- `two_node_mim_smoke`
- `verify_replay_timeline`
- `linear_five_mm_entanglement_swapping`
- `measurement7000_simple_mim`

プロファイル別メモ:

- `two_node_mim_smoke`
  - 既定バックエンド: 上書きが無ければ選択 config の既定を継承
  - 想定する結果: `setup_success_ratio`、`setup_latency_s` 等のセットアップ／リクエスト指標
  - 既定チューニング: `traffic.request_rate_hz=1.0`（2 秒の smoke 実行でリクエストがサマリを溢れさせないため）
- `verify_replay_timeline`
  - 既定バックエンド: `graph_state`
  - 既定 `sim_time_limit`: `10.0s`
  - 既定 `traffic.request_rate_hz`: `2.0`
  - 想定する結果: `Replay` の sim-time シーク、cluster 進行、`t=0` からの event 発生確認
  - 注意: Results の bell-pair 活動確認よりも、Replay UI 検証を優先したプロファイル
- `linear_five_mm_entanglement_swapping`
  - 既定バックエンド: `graph_state`
  - 既定 `sim_time_limit`: `12.0s`
  - 想定する結果: `bellpair_generation_rate_per_s`、`bellpair_inventory_peak` 等の bell-pair 活動指標
  - 注意: この config は通常アプリケーションのリクエスト／セットアップイベントを発行しないため、`setup_success_ratio` は unavailable のまま
- `measurement7000_simple_mim`
  - 想定する結果: 大規模トポロジの起動・回帰チェック。指標の availability は選択した purification／backend 設定に強く依存

override の優先順序は次の通り（固定）:

1. profile defaults
2. 構造化 `parameter_values`
3. 明示的な raw `overrides`

`Template / Config` の組にキュレーション済みプロファイルが無い場合、UI はレガシーモードへフォールバックし、実行向けの構造化フィールドのみを残します。

## 実験結果サマリ

各 run ディレクトリには `run.jsonl` に加えて実験成果物を含められます。

- `experiment_spec.json`
- `resolved_overrides.json`
- `experiment_summary.json`
- `experiment_timeseries.jsonl`

サマリ指標はブラウザではなくバックエンド側で計算されます。初期の結果セットは次に注力しています:

- `setup_success_ratio`
- `setup_latency_s`
- `bellpair_generation_rate_per_s`
- `bellpair_inventory_peak`
- `bellpair_inventory_mean`
- `photon_loss_rate_per_s`
- `link_fidelity`
- `link_bellpair_rate_per_s`
- `failure_reason_breakdown`

`setup_success_ratio` は意図的に「セットアップ段階の成功」として定義されており、アプリケーション層の完了ではありません:

- submitted: ソース側からリクエストが発行された
- success: コネクションマネージャがセットアップを受理した
- reject: セットアップが明示的に拒否された

利用不可の指標は zero に丸めず unavailable として返します。

現在の実装で実用上重要な解釈:

- リクエスト／セットアップ指標が欲しいときは `two_node_mim_smoke`。
- 早期再生イベントと time-seek 検証が欲しいときは `verify_replay_timeline`。
- bell-pair 活動とトポロジアニメーションが欲しい（リクエスト／セットアップ成功は不要）ときは `linear_five_mm_entanglement_swapping`。

## 実験比較

run リストの `比較+` で比較キューに run を追加できます。比較ドロワーは次を取得します:

- run ごとのスカラ指標
- `mean / p50 / p95 / p99` 等の分布サマリ
- 一方の run に指標が存在しない場合の availability 警告

比較 API は直接利用も可能:

```bash
curl -X POST http://localhost:8765/api/experiments/compare \
  -H 'content-type: application/json' \
  -d '{
    "run_ids": ["run_a", "run_b"],
    "metric_ids": ["setup_success_ratio", "link_fidelity"]
  }' | jq
```

## 古典パケット可視化のタクソノミ

ダッシュボードは古典トラフィックを 3 種類に分けて扱います。

- `classical_packet_hop`
  - `<repo-root>/quisp/modules/Common/Router.cc` から発行
  - `toQueue` に送られた実際のホップ 1 つを表す
  - 古典エッジアニメーションの唯一のソースとして使用
- `classical_packet_deliver_local`
  - `Router` から `toApp`、`cmPort`、`rePort`、`hmPort`、`rdPort` に古典パケットが渡される際に発行
  - ノードローカルの脈動として描画
- summary / metrics / metadata
  - `experiment_request_*`
  - `experiment_link_quality_sample`
  - `topology_snapshot`
  - これらはパケットアニメーションではなく、Results・key moments・サマリで使用される

正準的な古典パケットファミリ:

- `connection_setup`
- `ruleset_forwarding`
- `swapping`
- `purification`
- `link_generation`
- `tomography`
- `routing`
- `unknown`

ファミリの既定可視性:

- `Replay`
  - `connection_setup`、`ruleset_forwarding`、`swapping`、`purification`、`link_generation` を表示
  - 既定では `routing`、`tomography` を非表示
- `Monitor core`
  - `connection_setup`、`ruleset_forwarding`、`swapping`、`purification`、`link_generation`、`flying`、`bellpairs`、`loss`、`link_quality` を含む
  - フィルタで明示選択しない限り `routing`、`tomography`、`unknown` は含まない

`SwappingResult`、`PurificationResult`、`MSMResult`、`LinkTomography*` 等のプロトコル層古典パケットは、run が正準的な Router レベルのパケットイベントを含んでいる場合のみ描画されます。`classical_packet_hop` / `classical_packet_deliver_local` を含まない古いログは、サマリと生ログは保持しますが、汎用的な `handleMessage` トレースから疑似のパケット経路を合成することはしません。

つまり、`classical_packet_hop` / `classical_packet_deliver_local` を含まない古い run では、汎用的な `handleMessage` ログから古典パケットアニメーションを偽造することはありません。UI は生ログとサマリは保持しますが、誤解を招くパケット経路の描画は避けます。

## 検証済み run

これらの run は 2026 年 3 月 7 日時点の実装に対して確認されています。

- `Two-node MIM smoke`
  - 代表 run: `run_1772837145074_6d6a8c`
  - 期待されるサマリ形:
    - `request_submitted_count > 0`
    - `request_setup_success_count > 0`
    - `setup_success_ratio` 利用可能
- `Linear five MM default`
  - 代表 run: `run_1772837875887_33e37e`
  - 期待されるサマリ形:
    - `bellpair_generated_count > 0`
    - `bellpair_generation_rate_per_s` 利用可能
    - `bellpair_inventory_peak > 0`
    - `setup_success_ratio` 利用不可

## 実験開始までの手順（おすすめ）

1. ダッシュボード起動時に `--log-dir` を書き込み可能なディレクトリ（既定: `scripts/dashboard/runs`）に設定しておく。
2. UI を開く: `http://localhost:8765/`
3. `Template` で `quisp/networks/*.ini` または `quisp/simulations/*.ini` 内のテンプレートを選ぶ。
4. `Config` から実行コンフィグを選ぶ。
5. `Num Runs`、`Seed Set`、`sim-time-limit` を必要に応じて設定。
6. `Run` を押す。
7. `実行ジョブ` の該当行で `ビューへ` を押して同じ run_id のイベント再生を開始。
8. `サブグラフ再計算` で `Focus`/`Hops`/`ノード正規表現` を切り替える。
9. 完了したら `Stop Selected` / `Stop` で終了要求を送る。状態は `running -> terminated` 等に遷移。

### 最短の実験サンプル

- 既存ログを可視化だけ行う場合:
  - `layout`/テンプレート起動はせず、`--log-dir` 配下に `run.jsonl` を置く。
  - `実行一覧` 更新で run が検出されれば、`run_id` を選択して再生開始。
- まず 1 件だけ UI で起動して挙動確認する場合:
  - `Num Runs: 1`、`Seed Set` 空、`sim-time-limit` 空で `Run`。
  - 1 分以上進まない場合は、`maxNodes` を下げて表示を軽くして再試行。

### コマンド起動確認（API 経由）

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

`template_id` は環境に合わせて置換してください（`/api/sim/templates` で実体 ID を確認）。

### 最短実験シナリオ（コマンド主導）

```bash
# 1) ダッシュボード起動
python -m scripts.dashboard.backend.app.main --log-dir scripts/dashboard/runs --port 8765

# 2) テンプレート/実行設定取得
curl -s http://localhost:8765/api/sim/templates | jq '.[0:5]'

# 3) 1 回だけ実行
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
RUN_ID=... # 上の POST で返った run_id を代入
watch -n 5 "curl -s http://localhost:8765/api/sim/runs/$RUN_ID | jq '.status,.sim_time_limit,.metrics.lines_read'"

# 5) UI で同じ run_id を可視化
open http://localhost:8765/   # ブラウザで「実行ジョブ」->「ビューへ」

# 6) 収束後の停止（必要時）
curl -X POST http://localhost:8765/api/sim/runs/$RUN_ID/stop

# 7) ログ取得
curl -s http://localhost:8765/api/sim/runs/$RUN_ID/log | jq '.tail'
```

注記:
- `TemplateIDHere` は `curl .../api/sim/templates` の実体で置換してください。
- `open` は macOS 向けコマンドです。Linux は `xdg-open` など環境に合わせて置き換え。
- `watch` が使えない環境では 5 秒間隔で GET を手動実行してください。

### Simulation API メモ

- `POST /api/sim/runs` は template/ini と config を受け取る。run_id 形式は `run_<unixms>_<token>`。
- `workdir` 省略時はテンプレートのディレクトリを既定で使用。
- 状態遷移: `queued -> starting -> running -> (finished | failed | terminated)`。
- `POST /api/sim/runs/{run_id}/stop` は SIGTERM → SIGKILL のフォールバック（または `--stop-timeout-seconds` のタイムアウト）。

## メモ

- テンプレート探索の対象:
  - `quisp/networks/*.ini`
  - `quisp/simulations/*.ini`
- シミュレーションログのパスは `scripts/dashboard/runs/{run_id}/run.jsonl` 配下に書かれます。
- プロセスの stdout/stderr も `scripts/dashboard/runs/{run_id}/stdout.log` および `scripts/dashboard/runs/{run_id}/stderr.log` に保存されます。
- 停止は graceful な SIGTERM、SIGKILL フォールバック（タイムアウトは `--stop-timeout-seconds`）を使用。
- この実装はログ可視化とシミュレーション制御を 1 プロセスにまとめ、API 間で run ID を共有します。
- 既存ログは `--log-dir` 配下を再帰的に検出し、各 run ディレクトリ直下の `run.jsonl` を受理して run ディレクトリ名でマッピングします。

## ビューワモード

ダッシュボードのビューワには 3 つのモードがあります。

### Monitor

`Monitor` は `queued`、`starting`、`running` の run の既定モードです。生イベントを再生せず、`GET /api/runs/{run_id}/activity` を 1 秒に 1 回ポーリングし、集約された活動を描画します:

- ノード活動ヒート
- エッジ活動ヒート
- key moments
- ストリームヘルス
- `sim 進行倍率`（`delta(sim_time) / delta(real_time)`）
- `可視イベント密度`（`dashboard-visible events / sim-second`）

このモードでの `LIVE` は「ライブエッジを追跡」を意味します。タイムラインを末尾から動かすと、生イベント再生ではなく履歴的な活動の検査ビューに切り替わります。

### Replay

`Replay` は詳細な生イベント解析モードです。既存のイベント API を引き続き使用します:

- `GET /api/runs/{run_id}/events`
- `GET /api/runs/{run_id}/events/stream`
- `WS /api/runs/{run_id}/stream`

Replay はビューワ側の速度メトリクスを追加します:

- `実効sim再生倍率`: 観測された `delta(displayed sim_time) / delta(real_time)`
- `再生イベント速度`: 実時間 1 秒あたりの再生イベント数
- `可視イベント密度`: アクティブな解析窓における sim-second あたりの可視ログイベント数

`flying_qubit_*`、`BellPair*`、リクエスト／セットアップイベントを詳細にステップする場合はこのモードを使ってください。

### Results

`Results` はサマリ成果物が利用可能な完了済み run の既定です。再生用ではなく実験評価用です。実験サマリと比較表に加え、`GET /api/runs/{run_id}/activity/summary` から導出されるビューワ診断を表示します:

- `可視イベント密度 mean`
- `可視イベント密度 p95`
- `可視イベント密度 peak`

## アクティビティ API

monitor とビューワ診断画面のために 2 つの API を追加しています。

### `GET /api/runs/{run_id}/activity`

カーソル基準の lookback 窓に対する `ActivitySnapshot` を返します。次を含みます:

- `global_totals`
- `bins`
- `view_node_activity`
- `view_edge_activity`
- `key_moments`

主なクエリパラメータ:

- `anchor_cursor`
- `window_s`
- `lookback_s`
- `classes`
- `focus`
- `hops`
- `max_nodes`
- `node_regex`

### `GET /api/runs/{run_id}/activity/summary`

可視イベント密度に対する run 全体のビューワ診断を返します:

- `visible_event_density.mean`
- `visible_event_density.p95`
- `visible_event_density.p99`
- `peak_windows`
- `global_counts_by_class`

## モード選択ルール

UI は既定のビューワモードを自動選択します。

- `queued | starting | running` -> `Monitor`
- `finished | failed | terminated` でサマリあり -> `Results`
- `finished | failed | terminated` でサマリなし -> `Replay`

これにより、完了済み run が「stall した live stream」のように表示されることを防ぎます。

## 推奨検証実験

シミュレータとダッシュボードを素早く確認したい場合は、以下のキュレーション済みプロファイルを順に使ってください。

### 1. `verify_two_node_setup`

目的:
- ランチャー → シミュレータ → サマリ成果物 → Results 経路を確認
- リクエスト／セットアップ指標が空でないことを確認
- 短時間 run がクリーンに完了することを確認

既定:
- template: `quisp/simulations/two_nodes.ini`
- config: `two_node_MIM`
- backend: `graph_state`
- sim-time-limit: `4.0s`
- request rate: `1.0 Hz`

期待される表示:
- `request_submitted_count`
- `request_setup_success_count`
- `setup_success_ratio`
- `setup_latency_s`

素早い sanity check が欲しいときに最初に使ってください。

### 2. `verify_linear_five_activity`

目的:
- `Monitor` でのトポロジ描画を確認
- ヒートビューと key moments を確認
- 自明でない run での `Replay` を確認
- `Results` での bell-pair 活動指標を確認

既定:
- template: `quisp/networks/omnetpp.ini`
- config: `EntanglementSwapping_Linear_FIVE_MM_Test`
- backend: `graph_state`
- sim-time-limit: `12.0s`
- 発光成功確率: `1.0`

期待される表示:
- `1-2-3-4-5` のラインタイポロジ
- `Monitor` でのアクティブなノード／エッジヒート
- bell-pair バーストと終端 key moments
- `bellpair_generated_count`
- `bellpair_generation_rate_per_s`
- `bellpair_inventory_peak`

GUI 自体を検証したいときに 2 番目に使ってください。

### 3. `verify_qutip_backend`

目的:
- リポジトリ内 QuTiP 環境の配線を確認
- `qutip_density_matrix` バックエンドが import 失敗なく起動することを確認
- `graph_state` より遅いバックエンドでもダッシュボード起動経路が動くことを確認

既定:
- template: `quisp/simulations/two_nodes.ini`
- config: `two_node_MIM`
- backend: `qutip_density_matrix`
- sim-time-limit: `4.0s`
- request rate: `0.5 Hz`

期待される表示:
- `qutip` バックエンドが選択された状態でクリーンに起動
- `request_submitted_count`
- `request_setup_success_count`
- `ModuleNotFoundError: No module named 'qutip'` が出ないこと

QuTiP の実行経路を確認したいときに、最初の 2 つのプロファイルの後に使ってください。
