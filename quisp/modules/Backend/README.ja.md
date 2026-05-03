# Backend インタフェース契約 (vNext)

> **English version**: see [README.md](README.md).

この文書は、OMNeT 側と物理バックエンド間の責務分離ルールを明文化します。

## 1) 原則
- 量子状態の操作・ノイズ・測定は、原則としてバックエンドが実行し、OMNeT 側は**古典情報のみ**を扱います。
- `QuantumChannel` は状態を直接更新せず、`applyErrorChannel(...)` を 1 回呼び出すだけです。
- `BellStateAnalyzer` も `hom_interference` と `detection` の結果（`outcome_pattern`）から判定し、量子状態を直接参照しません。

## 2) `OperationResult` の意味
`quisp/modules/Backend/IPhysicalBackend.h` の `OperationResult` は古典情報兼実行結果です。

- `success`: バックエンド呼び出し自体の成否
- `discarded`: 管理イベント由来の廃棄（expired / cutoff）
  - **OMNeT/スケジューラ側で決まる寿命管理・資源回収イベント**
  - 物理現象の光子消失を表さない
- `photon_lost`: 物理現象としての損失（channel attenuation / loss）
  - **バックエンド側が決定する物理的消失フラグ**
- `discard_reason`: `"expired"`, `"cutoff"`, `"photon_loss"` など
- `outcome_pattern`: BSA 等の検出結果パターン（例: `dAh,dAv` / `dBh,dBv` / `dAh,dBv` / `dAv,dBh` / `dAh` / `dAv` / `dBh` / `dBv` / `none`）
- `detection_click_count` / `detector_histogram` / `classical_payload`: BSA 解析に使う補助情報

### 用語の明文化

- `discarded` と `photon_lost` は重なりうるが別概念です。
  - `discarded=true` は「運用上これ以上参照しない」扱い。
  - `photon_lost=true` は「量子情報が物理的に到達不能/消失」扱い。
- OMNeT 側ロジックは、状態遷移/ノイズの実行を行わず、基本的に両フラグを読み取り用途にのみ使います。

- `outcome_pattern` は文字列正規化しない strict 比較です。
  - 旧 `d0` 系の文字列や順序を入れ替えた表現は受け入れません。

## 3) 代表 API
- `applyErrorChannel(qubit_ids, channel_profile_name, params)`
- `applyHomInterference(qubit_ids, params)`
- `applyDetection(qubit_ids, params)`

### 期待値の解釈
- BSA 系モジュールは `outcome_pattern` でのみ量子ビット到達・成功判定を行う。
- `discarded`/`photon_lost` は判定の補助として使う。
  - `discarded`: 管理側の寿命・切断等
  - `photon_lost`: 物理伝搬損失

## 4) GraphState backend (`ErrorBasisBackend`) の位置付け
- `x_error`, `z_error`, `discarded`, `photon_lost` はバックエンド内部メタデータとしてのみ保持。
- OMNeT 側 `PhotonicQubit` メッセージからは誤差フラグを参照しない。

## 5) qutip profile contract (vNext)
- `qutip_density_matrix` は `qutip_profile` の単一設定で動作する。
- `qutip_node_profile` / `qutip_link_profile` は非対応（`invalid_profile`）。
- `qutip_profile_overrides` は `dim`, `leakage_enabled`, `truncation` のみ受理。
- `entanglement_set_id` は全 operation で共通に使い、`mode` による分離は行わない。
