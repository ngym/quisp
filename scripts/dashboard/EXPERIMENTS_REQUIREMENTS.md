# QuISP Dashboard Experiment Execution Requirements

## 目的

QuISP Dashboard のシミュレーション実施導線を、単発の `Run` ボタン中心から、再現可能な実験管理へ拡張する。v1 の主対象は、研究者や開発者が curated `Experiment Profile` を選び、少数から多数の条件を batch 実行し、結果を比較し、必要な run を Monitor / Replay / Results で確認する流れである。

Monitor の再設計はこの導線の後続作業とし、本要件では「実験をどう定義し、どう投入し、どう追跡するか」を扱う。

## 主導線

1. 利用者は `Experiments workspace` を開く。
2. `Experiment Profile` を選ぶ。
3. profile の既定値を確認し、base parameters を編集する。
4. 必要に応じて profile parameter と raw override の sweep 値を追加する。
5. `Plan Preview` を実行する。
6. Dashboard は展開される run 数、seed、sim-time-limit、resolved overrides、推定 command sample、warnings を表示する。
7. 利用者が preview を確認して enqueue する。
8. Dashboard は `Campaign` を作成し、展開済み run specs を永続 queue に保存する。
9. `Campaign Tracker` は progress、status counters、run list、pause/resume/stop/retry、compare/view を表示する。
10. 利用者は個別 run から Monitor / Replay / Results を開く。

## Campaign モデル

`Campaign` は複数の simulation run を束ねる実験単位である。少なくとも以下を保持する。

- `campaign_id`: `campaign_<unixms>_<token>` 形式。
- `display_name`: UI 表示名。
- `experiment_profile_id`: 利用した profile。raw template 実行の場合は `null` を許容するが、v1 の主導線は profile 必須。
- `template_id`, `config_name`: 解決済み template/config。
- `base_parameter_values`: sweep 展開前の基準値。
- `sweeps`: profile parameter または raw override の sweep 定義。
- `fixed_overrides`: base raw overrides。
- `requested_metrics`: profile 推奨または利用者指定の metric ids。
- `run_specs`: 展開済みの実行仕様。
- `run_ids`: 実際に投入された Dashboard run ids。
- `status`: `queued | running | paused | finished | failed | cancelled`。
- `created_at`, `updated_at`, `started_at`, `finished_at`。
- counters: `total_runs`, `queued_count`, `starting_count`, `running_count`, `finished_count`, `failed_count`, `cancelled_count`.

`CampaignRunSpec` は 1 run 分の入力を表す。

- `spec_id`: campaign 内で安定な id。
- `parameter_values`: profile parameter の最終値。
- `overrides`: run.ini に反映する raw overrides。
- `seed_set`: `execution.seed_set` から解決した値。
- `sim_time_limit`: `execution.sim_time_limit_s` から解決した値。
- `run_name`: campaign 名と sweep 条件から生成した短い名前。
- `tags`: campaign id、profile id、sweep labels を含む。
- `status`: `queued | starting | running | finished | failed | cancelled`。
- `run_id`: start 済みなら Dashboard run id。
- `error_message`: start 失敗または retry 対象理由。

## Sweep 要件

- sweep は `profile_parameter` と `override` の 2 種類を扱う。
- 複数 sweep は Cartesian product で展開する。
- sweep 値が空なら base 値 1 条件として扱う。
- `execution.seed_set` は `seed_set` にマップし、raw override へは入れない。
- `execution.sim_time_limit_s` は `sim_time_limit` にマップし、raw override へは入れない。
- その他の profile parameter は既存 `resolve_experiment_request` と同じ mapping で overrides に解決する。
- raw override key は既存 `validate_run_spec_overrides` と同じ validation を使う。
- 展開後の各 run は `num_runs=1` の `SimRunStartRequest` として投入する。Campaign 側で run 数を管理するため、Campaign request の `num_runs` は使わない。
- default の最大展開数は `Q_DASH_MAX_CAMPAIGN_RUNS`、未設定時は `10000` とする。超過時は preview/create とも 400 を返す。

## API 要件

### Preview

`POST /api/experiments/campaigns/preview`

- campaign request を受け取り、実際の simulation run は作らない。
- response は `total_runs`, `sample_runs`, `warnings`, `resolved_template_id`, `resolved_config_name`, `command_samples` を含む。
- `sample_runs` は最大 50 件。
- validation 失敗は 400。

### Create

`POST /api/experiments/campaigns`

- preview と同じ解決処理を再実行し、Campaign を永続化する。
- response status は 201。
- response は campaign summary と最初の progress counters を返す。
- scheduler は空き slot がある場合、作成直後に queued specs を開始してよい。

### Read and Control

- `GET /api/experiments/campaigns`: campaign summaries を新しい順で返す。
- `GET /api/experiments/campaigns/{campaign_id}`: campaign detail、run specs、linked run infos を返す。
- `POST /api/experiments/campaigns/{campaign_id}/pause`: 未開始 queued specs の開始を止める。
- `POST /api/experiments/campaigns/{campaign_id}/resume`: paused campaign の queue を再開する。
- `POST /api/experiments/campaigns/{campaign_id}/stop`: 未開始 specs を cancelled にし、running specs は既存 stop API と同じ graceful stop を要求する。
- `POST /api/experiments/campaigns/{campaign_id}/runs/{run_id}/retry`: failed/cancelled run spec を新しい run として再投入する。

## 永続化と再起動

- Campaign metadata は `scripts/dashboard/runs/_campaigns/{campaign_id}/campaign.json` に保存する。
- write は一時ファイルに書いてから atomic replace する。
- Dashboard 起動時に `_campaigns` を読み込み、queued/paused/running campaign を復元する。
- process handle を持たない `starting` / `running` run spec は `failed` に更新し、`error_message` に dashboard restart を記録する。
- 未開始 `queued` run spec は再開対象として残す。

## Scheduler 要件

- scheduler は既存 `SimulationRunner` を使い、`max_concurrent_runs` を超えて start しない。
- active slot は Dashboard 全体で共有し、単発 `/api/sim/runs` と Campaign run を同じ上限で数える。
- run が `finished | failed | terminated` になったら Campaign counters を更新し、空き slot があれば次の queued spec を開始する。
- campaign が `paused` の間は新規 start しない。
- campaign が `cancelled` の間は新規 start しない。
- 全 specs が terminal になったら campaign は `finished`、ただし failed が 1 件以上あれば `failed` とする。

## UI 要件

`Experiments workspace` を追加し、既存の Monitor / Replay / Results とは主導線を分離する。

- workspace root は `data-testid="experiments-workspace"` を持つ。
- Profile step:
  - profile list、description、notes、recommended metrics を表示する。
- Parameters step:
  - base parameter inputs を表示する。
  - sweep value inputs を profile parameters と raw overrides に追加できる。
- Plan Preview step:
  - `data-testid="campaign-preview-button"` で preview を実行する。
  - `data-testid="campaign-preview"` に run 数、sample、warnings を表示する。
  - preview 完了まで enqueue は無効。
- Campaign Tracker:
  - `data-testid="campaign-tracker"` を持つ。
  - progress bar、status counters、run table を表示する。
  - Pause / Resume / Stop / Retry failed / Compare selected / View run を提供する。

## 受け入れ条件

- preview は run を作成せず、展開結果だけを返す。
- campaign create は展開済み specs を永続化し、queue に登録する。
- queue は `max_concurrent_runs` を超えない。
- pause 中に新しい run は開始されない。
- resume 後に queued run が再開される。
- stop 後に未開始 specs は cancelled になる。
- retry は failed/cancelled spec から新しい run を作る。
- dashboard 再起動後、queued campaign は復元される。
- E2E で Profile -> Sweep -> Preview -> Enqueue -> Tracker -> View run の導線を確認できる。
