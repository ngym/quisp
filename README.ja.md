# QUISP（日本語版）

[![Codacy Badge](https://app.codacy.com/project/badge/Grade/83c96c45f2684211a8cef800b1d07f81)](https://www.codacy.com/gh/sfc-aqua/quisp/dashboard?utm_source=github.com&amp;utm_medium=referral&amp;utm_content=sfc-aqua/quisp&amp;utm_campaign=Badge_Grade)
[![Coverage Status](https://coveralls.io/repos/github/sfc-aqua/quisp/badge.svg?branch=master)](https://coveralls.io/github/sfc-aqua/quisp?branch=master)
![github workflow](https://github.com/sfc-aqua/quisp/actions/workflows/main.yml/badge.svg)
<a href="https://aqua-quisp.slack.com/" rel="nofollow"><img src="https://img.shields.io/badge/join-us%20on%20slack-gray.svg?colorB=red&amp;logo=slack&amp;longCache=true" alt="Slack Widget"></a>

Quantum Internet Simulation Package (QuISP) は、来たる量子インターネットの基盤となる量子リピータネットワークをイベント駆動でシミュレーションするためのパッケージです。QuISP の目標は、最大 100 ネットワーク × 各 100 ノード規模の完全な量子インターネットをシミュレーションすることにあります。物理層を可能な限り現実に即して扱いつつ、大規模で異種混在なネットワークにおけるプロトコル設計と創発的挙動の解析に焦点を置いています。

QuISP は慶應義塾大学湘南藤沢キャンパス（藤沢市）の Rodney Van Meter 教授が率いる Advancing Quantum Architecture (AQUA) 研究グループのプロダクトです。詳しくは [http://aqua.sfc.wide.ad.jp](http://aqua.sfc.wide.ad.jp) および [Authors.md](Authors.md) をご覧ください。

> **English version**: see [README.md](README.md).

## 研究上の問い

シミュレータは「タイムマシン」「X 線装置」「望遠鏡」のいずれか（もしくは複数）として機能します。未来や過去を覗くこと、対象内部のアクセスし得ない部分を見ること、研究室では構築できない巨大スケールの対象を観察すること——QuISP は中でも特に「望遠鏡」として、大規模量子ネットワークおよび究極的には量子インターネットを観察するためのものです。同時に、プロトコルのミクロな（局所）挙動も観察します。

QuISP で答えたい研究上の問い:

* 創発的挙動
    - 古典ネットワークでは _輻輳崩壊 (congestion collapse)_ が観測されるが、量子ネットワークでも同種の現象は起きるか？
    - 大規模ネットワークの動的挙動が、ナイーブなモデルでは到達可能と思える条件下でも end-to-end 接続を阻害することはあるか？
    - 大規模ネットワークで他に予期せぬ挙動はあるか？
* プロトコル設計
    - 詳細なプロトコル設計が正しく動作するかの検証
    - 古典部と量子部の相互作用は存在するか？
* 接続アーキテクチャと性能予測
    - 提案されている 3 世代いずれの量子ネットワークも、現実的なパラメータ下では解析的な性能予測が困難な複雑挙動を示す。シミュレーション側でも妥当性検証は最大限の努力を要する。
* 動的挙動
    - 条件変化に対しネットワークは安定か？
    - トポロジ変更時のプロトコルの応答は？
    - トラフィックは動的に変化するため、多重化やリソース管理プロトコルは新規接続を妥当な時間内に処理し、既存接続にも期待水準を維持できるか？

## シミュレータの目標

長期的には次を狙います:

* 物理・論理双方の階層で、ネットワーク境界や異種混在を含む複雑なトポロジを扱えること
* 1G・2G・3G の量子ネットワーク（誤り処理に purify-and-swap (1G) もしくは量子誤り訂正 (QEC) (2G/3G) を使用）に対応
* 異なるリンク方式: メモリ間 (MM)、中点干渉 (MIM)、中点ソース (MSM)、スニーカーネット、衛星
* 異なる種類のネットワーク同士をつなぐ内部ネットワーキングプロトコル
* 複雑なトラフィックパターンで動作する各種アプリケーション

これらのプロトコルは単一のもつれ状態に数百キュービットを含み、システム全体では 100 万キュービットに達することがあります。物理ハミルトニアンレベル、もしくはユニタリ（ゲート、例: CNOT）レベルでさえもシミュレーションは現実的でなく、状態の完全な密度行列を計算・保持することはできません。そのため QuISP は大規模量子誤り訂正シミュレータと同様、主に _誤り基底 (error basis)_ で動作し、状態の完全表現ではなく状態が被った誤りの記述を保持します。ただし多くの QEC シミュレータと違い、QuISP は非 Pauli 誤りを限定的にサポートします。

QuISP の設定可能性はほぼ無制限で、ネットワーク内のリンクごとに長さを変えるだけでなく、個々のキュービットごとにゲート誤り率やメモリ寿命を設定することもできます。現在のリリースで部分的に対応している非 Pauli 誤りには、キュービット損失、基底状態への緩和、励起状態への遷移、完全混合などがあります。

研究文献や用語に不慣れな場合は下記「[さらに学ぶには](#さらに学ぶには)」を参照してください。

加えて、QuISP では人間が達成可能な範囲で _完全な再現性 (completely reproducible)_ を目指しています。リリース名・依存ソフトウェアのバージョン番号・`.ini` ファイル・変更した `.ned` ファイル・疑似乱数生成器のシードがあれば、第三者が結果を検証できます。

## 現状

_インフラ_ の大部分は動作しますが、実行できる実験（興味深いシミュレーション）の集合はまだ限定的です。

動いているインフラ:

* OMNeT++ の基本機能全般（イベント、可視化、ロギング、解析など）
* リンクごとのパラメータ（長さ、チャネル誤り率、量子メモリ数、ゲート誤り率など）を含む複雑なトポロジ定義（同梱のデモネットワークでドキュメントから確認可）
* リピータの内部ソフトウェアアーキテクチャを完全モデル化（コネクションマネージャ、RuleSet 実行エンジン、量子状態のリアルタイム追跡など）
* 複数の物理層バックエンド——従来の `graph_state` バックエンドと、Python の QuTiP ワーカーに状態発展を委譲する `qutip_density_matrix` バックエンド
* `scripts/dashboard/` 配下の Web ダッシュボード（QuISP の起動、Canvas UI でのライブ可視化、実験サマリ集約）

設定の自由度に加え、実装済みの主要量子プロトコル:

* RuleSet 生成・配布の基本
* 各種 *純化プロトコル*: 1 ラウンドの X 純化、X/Z 交互純化など。既定はもつれスワップ 1 ラウンドあたり 1 ラウンドの純化。独自の純化プロトコルへ拡張するのも比較的容易
* *トモグラフィ*: シミュレーション起動時、各リンク両端のソフトウェアはリンクについて _何も_ 知らないと仮定し、まずリンクのトモグラフィを行う（収束に時間がかかるためブートアップが長くなる問題があり、事前計算しトモグラフィの含有を選択可能にする方向で作業中）
* *もつれスワップ*
* リンクアーキテクチャ: メモリ間 (MM)、中点干渉 (MIM)、中点ソース (MSM)

ネットワーキング層の現状:

* 完全ブロッキング型回線交換
* ランダムなペアワイズトラフィック（一様分布）

仕掛中:

* もつれスワップは比較的新しい機能であり、関連データ収集はまだ未完成
* コネクション完了時の teardown はまだ少し手入れが必要
* デモネットワーク群は調整中

近い将来のリリースで予定:

* より一般的なリソース割当・多重化
* より一般的なトラフィックパターン構築機構
* リンク層のグラフ状態
* アプリケーション層の多者間状態

中長期で予定:

* 2G ネットワーク（特に Jiang 方式）
* 完全な量子インターネットワーキング

## インストール要件

完全な手順は [Wiki](https://github.com/sfc-aqua/quisp/wiki) に記載されています。主に必要なツール:

* [OMNeT++](https://omnetpp.org/) と
* 外部 C++ ライブラリ [Eigen](http://eigen.tuxfamily.org/)
* Python 系ツールを使う場合は事前に依存をインストール: `python3 -m pip install -r requirements.txt`
* QuISP に貢献するなら [git](https://git-scm.com/) の基礎にも触れておく
* ソースコードコメント表示には [Doxygen](http://www.doxygen.nl/) 推奨（ドキュメントをビルドしないなら必須ではない）

ローカル環境と用途に応じて、C++ コンパイラ、make、X Window サーバ、Docker、動画作成用 ffmpeg などが追加で必要です。詳細はインストールノートを参照。

依存導入後に `qutip` と `qutip.qip` が import 可能か確認するには:

```bash
python3 scripts/check_qutip_import.py
```

高忠実度ワーカーのスモークチェックは:

```bash
python3 scripts/qutip_worker_smoke.py
```

または:

```bash
python3 -c "import qutip, qutip_qip, qutip.qip; print('ok')"
```

## モジュールテスト（OMNeT++ テスト）の実行

モジュールテストは `module_tests/runtest` で駆動され、以下のように実行します:

```bash
# OMNeT++ ランタイム環境
export PATH="/path/to/omnetpp/bin:$PATH"
export PYTHONPATH="/path/to/omnetpp/python:$PYTHONPATH"
export OMNETPP_CONFIGFILE="/path/to/omnetpp/Makefile.inc"

# 任意: 制限環境で ccache の一時ファイル権限問題を避ける
export CCACHE_DIR=/tmp/ccache
export CCACHE_TEMPDIR=/tmp/ccache

cd /path/to/quisp
make lib-debug
CCACHE_DISABLE=1 make run-module-test
```

`module_tests/runtest` は `--no-deep-includes` 非対応の古い OMNeT++/make 環境にもフォールバックします。

## Web ダッシュボード

QuISP には `scripts/dashboard/` 配下に Web ダッシュボードが同梱されており、UI から QuISP を起動・ライブ可視化し、実験サマリの集計まで行えます。詳細は [`scripts/dashboard/README.ja.md`](scripts/dashboard/README.ja.md)（日本語） / [`scripts/dashboard/README.md`](scripts/dashboard/README.md)（English）を参照してください。

推奨セットアップはリポジトリ内 QuTiP 仮想環境を使う方法です:

```bash
# リポジトリのルートで
make qutip-env       # .venv-qutip を作成し QuTiP 依存をインストール
make qutip-check     # .venv-qutip から qutip / qutip_qip が import できるか確認
make dashboard-backend
```

`make dashboard-backend` は QuISP バイナリ（`quisp/quisp`）をビルドし、QuTiP バックエンドを `.venv-qutip/bin/python` に向け、ダッシュボードを `http://127.0.0.1:8765/` で起動します。ホスト・ポート・ログディレクトリ・監査ログ・ワークスペースルート・バイナリパスは Makefile 変数（`DASHBOARD_HOST`、`DASHBOARD_PORT`、`DASHBOARD_LOG_DIR`、`DASHBOARD_AUDIT_LOG`、`DASHBOARD_WORKSPACE_ROOT`、`DASHBOARD_QUISP_BINARY`）で上書きできます。

## 物理層バックエンドの設定

バックエンドは `Backend` モジュールの NED パラメータ（`quisp/modules/Backend/Backend.ned`）で選択します。既定は密度行列 QuTiP モード（`physical_backend_type = "qutip_density_matrix"`）で、互換のために `graph_state` も引き続き利用可能です:

```ini
*.backend.physical_backend_type = "qutip"                  # qutip_density_matrix のエイリアス
*.backend.physical_backend_type = "qutip_density_matrix"   # 現在の既定
*.backend.physical_backend_type = "graph_state"            # 互換 / 高速
```

`Backend` で利用できる QuTiP 関連の任意チューニングパラメータ:

```ini
*.backend.qutip_backend_class = "qutip_density_matrix"  # もしくは qutip_state_vector
*.backend.qutip_python_executable = "python3"
*.backend.qutip_worker_script = "scripts/qutip_worker.py"
*.backend.qutip_max_register_qubits = 8
*.backend.qutip_max_hilbert_dim = 4
*.backend.qutip_solver = "mesolve"
*.backend.qutip_truncation = 5
*.backend.qutip_worker_timeout_ms = 1000
*.backend.qutip_profile = "standard_light"
*.backend.qutip_profile_overrides = ""
```

`qutip_profile` は全 operation に共通適用される単一プロファイルです。

- `standard_light`: `dim=2`（既定）
- `standard_qutrit`: `dim=4`
- `high_fidelity`: `dim=6`
- `custom`: `qutip_profile_overrides` で `dim`, `leakage_enabled`, `truncation` を JSON で指定
- `custom` では `dim` / `truncation` の最小値は `2` です。未対応値は `error_category="invalid_profile"` で失敗します。
- `leakage_enabled` は `true`/`false` の他、`1`/`0`, `"on"`/`"off"`, `"yes"`/`"no"` も受理します。

例:

```ini
*.backend.qutip_profile = "custom"
*.backend.qutip_profile_overrides = "{\"dim\":5,\"leakage_enabled\":true,\"truncation\":9}"
```

`standard_light` は既定互換 (`2`準位) を保持します。`qutip_profile` に不明な名前や `qutip_profile_overrides` の不正 JSON / 型違反が含まれた場合は `error_category="invalid_profile"` を返して `success=false` となります。

### プロファイル別の推奨INI例

A寄り（既定2準位）:

```ini
*.backend.qutip_profile = "standard_light"
*.backend.qutip_profile_overrides = "{}"
```

B寄り（4準位）:

```ini
*.backend.qutip_profile = "standard_qutrit"
```

高忠実度寄り（必要時のみ）:

```ini
*.backend.qutip_profile = "custom"
*.backend.qutip_profile_overrides = '{"dim":6, "leakage_enabled":true, "truncation":12}'
```

`custom`では、`qutip_profile_overrides` の `truncation` は内部のカットオフ値として参照されます。必要に応じて `dim` を 2〜6 の範囲で切り替える運用を想定しています。

QuTiP ワーカーは応答ごとに「直接的な operation model」を返します:

- `operation_model` ∈ `{"unitary","kraus","sampled_kraus","formula","unsupported"}`
  - `unitary`: ユニタリ発展（または他の直接的な演算子更新）
  - `kraus`: Kraus / CP 写像更新（非サンプリング）
  - `sampled_kraus`: サンプリング結果分岐（例: `measurement`, `detection`）
  - `formula`: 近似 / コンパクトなパラメータ化更新
  - `unsupported`: カテゴリ付きエラーで拒否

完全な kind カバレッジとマッピングは [`doc/PhysicalLayerBackendPlan-qutip-kinds.md`](doc/PhysicalLayerBackendPlan-qutip-kinds.md) で追跡しています。

QuTiP ワーカーで現在サポートしている主な kind の例: `kerr`、`cross_kerr`、`beam_splitter`、`hamiltonian`、`lindblad`、`amplitude_damping`、`thermal_relaxation`、`bitflip`、`phaseflip`、`depolarizing`、トップレベル `unitary` ゲート（`X`, `Y`, `Z`, `H`, `S`, `T`, `I`, `RX`, `RY`, `RZ`, `SQRT_X`, `SQRTX`, `CX`, `CNOT`）、`phase_shift`、`phase_modulation`、`self_phase_modulation`、`cross_phase_modulation`、`nonlinear`、`decoherence`、`dephasing`、`detection`、`loss`、`attenuation`、`polarization_rotation`、`polarization_decoherence`、`delay`、`timing_jitter`、`reset`、`hom_interference`。未対応・不明な kind は明示的なカテゴリ（例: `[category=unsupported_kind]`）で fail-fast します。

## Web で試す

基本サンプルだけ覗きたいだけであれば、[WebAssembly](https://webassembly.org) でビルドされた Web 版（[こちら](https://aqua.sfc.wide.ad.jp/quisp-online/master/)）でお試しいただけます。現在 Wasm 版は事前構成されたシミュレーションの実行のみ対応で、独自トポロジのアップロードはまだ対応中です。OMNeT++ と QuISP 自体の負荷の都合上、ローカル実行に比べてかなり遅くなります。

## ローカルでのビルドと実行

まず [Wiki](https://github.com/sfc-aqua/quisp/wiki) を参照し、その後下記の手順に従ってください。

CI と同等の OMNeT++ バージョンは `.omnetpp-version`（現状 `omnetpp-6.3.0`）に記録されています。CI と一致させたい開発作業では、devcontainer もしくは `ghcr.io/sfc-aqua/quisp-ci:latest` イメージの利用を推奨します。`make check-omnetpp` でローカルのツールチェインを確認できます。OMNeT++ のバージョンを切り替えた後は再ビルド前に `make clean` を実行してください。

QuISP の操作には主に二通りあります。OmNET++ の Eclipse ライク GUI を使う方法（[Building QuISP with OMNeT IDE](https://github.com/sfc-aqua/quisp/wiki/Building-QuISP-with-OMNeT-IDE) 参照）と、`Makefile` と GNU make を使う方法（[Building QuISP with GNU Make (wiki)](https://github.com/sfc-aqua/quisp/wiki/Building-QuISP-with-GNU-Make) 参照）です。一部の操作は Makefile にだけ実装されており、GUI からの説明はありません。

## 実用的な作業へ

ここまで来たら、[基本的なデモ](https://github.com/sfc-aqua/quisp/wiki/Running-Basic-QuISP-Demos)を実行できます。次は独自テストネットワークの作成方法、ソースコード拡張の方法を学びます。

貢献を始められるようになったら、[私たちが行ったように](https://github.com/sfc-aqua/quisp/wiki/Code-Spelunking)コードを読み解いていくと良いでしょう。

合わせて、[ソフトウェア設計ドキュメント](doc/software-design.md)も参照してください。

## 開発ツール

開発を少し楽にするツール群（主にスクリプト）が `bin` フォルダにあります。

## QuISP は自分に合っているか？

QuISP の本質は「ネットワークは単なる point-to-point 接続以上のものである」という点にあります。

システムやネットワークの挙動を知りたい、単純な解析式では捉えきれない（特にリンクあたり複数キュービットを持つような）リンク挙動を研究したい、ネットワークプロトコル設計に貢献したい——そういう用途には QuISP が向いています。検出器のウィンドウタイミング対もつれ忠実度の調整、空洞の Q 値の計算、ファイバ分散の理解といった用途には不向きかもしれません。

## さらに学ぶには

[references](doc/References.md) を参照してください。

## 貢献するには

まず [QuISP Slack](https://join.slack.com/t/aqua-quisp/shared_invite/zt-rwyggp6t-_4TaXE0g7PlUnRNSPU~g2w) に参加してください。

[code of conduct](CODE_OF_CONDUCT.md) と [Contributing guide](.github/CONTRIBUTING.md) も合わせてご確認ください。

## ライセンス

QuISP は 2020 年 4 月 5 日に初公開され、[3-Clause BSD License](https://opensource.org/licenses/BSD-3-Clause) の下で[ライセンス](LICENSE)されています。

QuISP は OMNeT++ 上に構築されています。OMNeT++ 自身は [独自ライセンス](https://omnetpp.org/intro/license)で、オープンソースかつ学術利用は無償ですが、商用組織にはライセンス料が必要です。線形代数ライブラリ Eigen も必要で、こちらは MPL2 のため[基本的に問題ない](http://eigen.tuxfamily.org/index.php?title=Main_Page#License)はずです。
