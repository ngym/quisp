# Physical Layer Backend Migration Plan / 物理レイヤー・バックエンド移行計画

This document defines an implementation plan for introducing switchable
physical-layer simulation backends in QuISP while preserving current behavior.
本ドキュメントは、QuISP において既存挙動を維持しつつ、物理レイヤーの
シミュレーションバックエンドを切り替え可能にするための実装計画を定義します。

## Goals / 目的

- Keep current simulation behavior unchanged by default.
  - 既定設定では現在のシミュレーション挙動を変更しない。
- Introduce a stable backend interface for future high-fidelity models.
  - 将来の高忠実度モデルに備え、安定したバックエンドインターフェースを導入する。
- Make backend selection explicit and reproducible in scenario configuration.
  - シナリオ設定でバックエンド選択を明示し、再現可能にする。
- Deliver value in small, reviewable PRs.
  - 小さくレビュー可能な PR 単位で段階的に価値を提供する。

## Terminology for this document / 用語定義

- `MIM Link` and `MSM Link` are link architecture concepts in the simulation documents.
- `MIM Protocol v1` and `MSM Protocol v1` are protocol identifiers used by `ProtocolType` and structured logs.

Constraint: string values stored in `ProtocolType::to_string` / log payloads must remain protocol identifiers only (`MIM Protocol v1`, `MSM Protocol v1`) and must not include `"Link"`.

## Non-goals (Phase 1) / 非目標（フェーズ1）

- No adaptive runtime backend switching.
  - 実行時の適応的バックエンド切り替えは対象外。
- No cross-backend state up-conversion.
  - バックエンド間の状態アップコンバージョンは対象外。
- No performance optimization beyond avoiding regressions.
  - 回帰回避を超える性能最適化は対象外。

## Current Constraints / 現状の制約

- QuISP targets large-scale simulations where full density-matrix tracking is infeasible in general.
  - QuISP は大規模シミュレーションを対象とし、一般に密度行列の完全追跡は現実的ではない。
- Existing behavior is based on lightweight error modeling and must remain the default path.
  - 既存挙動は軽量な誤りモデルに基づいており、既定経路として維持する必要がある。
- Event ordering and reproducibility must remain consistent with OMNeT++ execution.
  - イベント順序と再現性は OMNeT++ の実行モデルと整合させる必要がある。

## Proposed Architecture / 提案アーキテクチャ

```text
Protocol/Control Modules
        |
        v
PhysicalServiceFacade
  - validates requests
  - injects RNG context
  - logs backend + params
        |
        v
IPhysicalBackend
  - applyNoise
  - applyGate
  - measure
  - generateEntanglement
        |
        +--> ErrorBasisBackend (default)
        +--> Future backends (density-matrix / external)
```

- Keep the upper layer dependent on `PhysicalServiceFacade` + `IPhysicalBackend` only.
  - 上位層は `PhysicalServiceFacade` と `IPhysicalBackend` のみに依存させる。

## Interface Contract (Initial) / インターフェース契約（初期版）

```cpp
struct BackendContext {
  uint64_t seed;
  simtime_t now;
  std::string scenario_id;
};

struct QubitHandle {
  int node_id;
  int qnic_index;
  int qnic_type;
  int qubit_index;
};

enum class MeasureBasis { Z, X, Y, Bell };

struct OperationResult {
  bool success;
  double fidelity_estimate;
  bool qubit_lost;
  bool relaxed_to_ground;
  bool excited_to_plus;
  bool measured_plus;
};

class IPhysicalBackend {
 public:
  virtual ~IPhysicalBackend() = default;
  virtual OperationResult applyNoise(const BackendContext&, QubitHandle) = 0;
  virtual OperationResult applyGate(const BackendContext&, const std::string& gate,
                                    const std::vector<QubitHandle>& qubits) = 0;
  virtual OperationResult applyNoiselessGate(const BackendContext&, const std::string& gate,
                                            const std::vector<QubitHandle>& qubits) = 0;
  virtual OperationResult measure(const BackendContext&, QubitHandle, MeasureBasis) = 0;
  virtual OperationResult measureNoiseless(const BackendContext&, QubitHandle, MeasureBasis, bool forced_plus) = 0;
  virtual OperationResult generateEntanglement(const BackendContext&, QubitHandle,
                                               QubitHandle) = 0;
};
```

Notes / 補足:
- Keep `OperationResult` strongly typed in core API.
  - コア API では `OperationResult` を型安全に保つ。
- If extra diagnostics are needed, emit structured logs from the facade instead of JSON-in-API fields.
  - 追加診断情報が必要な場合、API 内 JSON ではなく Facade 側の構造化ログで出力する。

## Delivery Plan (PR-by-PR) / 段階導入計画（PR単位）

### 実行状況（2026-02-15）

- `backend_type` の直文字分岐を切替器に集約し、`physical_backend_type` パラメータを追加（空文字時は既存 `backend_type` を後方互換で参照）。
- `error_basis` を `GraphStateBackend` と同値として初期化経路に採用。
- `Backend` テストで `physical_backend_type` の初期化成功/失敗ケースを追加。
- `qutip` はサブモジュール依存から外し、`requirements.txt` の `qutip` / `qutip-qip` で管理する前提へ切り替え（`qutip.qip` 利用時は `qutip-qip` が必須）。
- `IPhysicalBackend` / `PhysicalServiceFacade` / `ErrorBasisBackend` を実装し、`StationaryQubit` の `measureX/Y/Z` を `PhysicalServiceFacade` 経由に変更（挙動非変更）。
- `StationaryQubit` の `measureX/Y/Z`, `gateX/Y/Z/H/S/Sdg/CNOT`, `generateEntangledPhoton`, `measureRandomPauliBasis` を `PhysicalServiceFacade` 経由に変更（挙動非変更）。

### PR-1: Introduce seam with no behavior change / 挙動非変更で境界を導入

- Add `IPhysicalBackend` and `PhysicalServiceFacade`.
  - `IPhysicalBackend` と `PhysicalServiceFacade` を追加。
- Add `ErrorBasisBackend` adapter that delegates to current logic.
  - 現行ロジックへ委譲する `ErrorBasisBackend` アダプタを追加。
- Route one narrow call path through the facade (e.g., measurement path).
  - まずは限定経路（例: 測定処理）を Facade 経由にする。
- Add configuration key in `.ini`: `**.physical_backend_type = "error_basis"` (default fallback: empty -> `backend_type`).
  - `.ini` に設定キー `**.physical_backend_type = "error_basis"`（既定値: 空文字列なら `backend_type` を参照）を追加。

**Acceptance criteria / 受け入れ条件**
- Existing scenarios produce equivalent outcomes with default config.
  - 既定設定で既存シナリオの結果が同等であること。
- No observable behavior change when backend is `error_basis`.
  - `error_basis` 利用時に観測可能な挙動変更がないこと。

### PR-2: Expand seam coverage / 境界適用範囲を拡大

- Route remaining physical operations through the facade.
  - 残りの物理操作も Facade 経由に統一。
- Remove direct physical-operation calls from upper modules where feasible.
  - 可能な範囲で上位モジュールから物理操作の直接呼び出しを排除。
  - `StationaryQubit` の `measure`/`gate`/`generateEntanglement`、`EPPS` の `emitPhotons` は `PhysicalServiceFacade` 経由化済み（進行中）。
  - `BSA` の `measureSuccessfully` で `noiseless*` 系呼び出しを `PhysicalServiceFacade` 経由の `applyNoiselessGate`/`measureNoiseless` に置換済み。
- Add backend name + seed + key params to logs for reproducibility.
  - 再現性のため、バックエンド名・シード・主要パラメータをログ出力。

**Acceptance criteria / 受け入れ条件**
- All physical operations pass through facade/backend abstraction.
  - 全物理操作が Facade/Backend 抽象経由で実行されること。
- Reproducibility metadata visible in logs.
  - 再現性メタデータがログで確認できること。

### PR-3: Contract and determinism tests / 契約・決定性テスト

- Add backend contract tests (interface-level behavior expectations).
  - バックエンド契約テスト（インターフェース期待挙動）を追加。
- Add determinism tests using fixed seeds.
  - 固定シードでの決定性テストを追加。
- Add regression comparison test(s) against baseline scenario outputs.
  - ベースライン結果との回帰比較テストを追加。

**Acceptance criteria / 受け入れ条件**
- Contract tests pass for `ErrorBasisBackend`.
  - `ErrorBasisBackend` の契約テストが成功。
- Determinism tests pass across repeated runs with the same seed.
  - 同一シード反復実行で決定性テストが成功。

### PR-4: Experimental second backend (optional) / 実験的第2バックエンド（任意）

- Implement a minimal second backend for a limited operation set (e.g., measurement only).
  - 限定操作（例: 測定のみ）を対象に最小第2バックエンドを実装。
- Compare statistics against default backend using A/B scenario runs.
  - A/B シナリオ実行で既定バックエンドとの統計比較を行う。

**Acceptance criteria / 受け入れ条件**
- Backend selection is functional via `.ini`.
  - `.ini` によるバックエンド選択が動作すること。
- Differences are measured and documented (accuracy vs runtime).
  - 差分（精度と実行時間）が計測・文書化されること。

## File-level Task Map (initial suggestion) / ファイル単位タスク（初期案）

- New files (proposed) / 新規ファイル案:
  - `quisp/modules/Backend/IPhysicalBackend.h`
  - `quisp/modules/Backend/PhysicalServiceFacade.h`
  - `quisp/modules/Backend/PhysicalServiceFacade.cc`
  - `quisp/modules/Backend/ErrorBasisBackend.h`
  - `quisp/modules/Backend/ErrorBasisBackend.cc`

- Likely integration touch points (verify during implementation) /
  想定される統合ポイント（実装時に要確認）:
  - `quisp/modules/Backend/*`
  - `quisp/modules/QRSA/RuleEngine/*`
  - `quisp/modules/QRSA/RealTimeController/*`
  - scenario `.ini` files where backend selection is configured

## Risks and Mitigations / リスクと対策

- **Risk:** Abstraction leaks backend internals to upper layers.
  - **Mitigation:** Keep backend API operation-oriented and opaque.
  - **対策:** バックエンド API は操作指向かつ内部非公開に保つ。
- **Risk:** RNG divergence across backends hurts reproducibility.
  - **Mitigation:** Centralize seed/time context in facade.
  - **対策:** シード・時刻コンテキストを Facade で一元管理する。
- **Risk:** Python/external backend IPC overhead dominates runtime.
  - **Mitigation:** Keep external backend optional and scoped to experiments.
  - **対策:** 外部バックエンドは任意・実験用途に限定する。
- **Risk:** Event ordering issues with async execution.
  - **Mitigation:** Keep calls synchronous in OMNeT++ event context.
  - **対策:** OMNeT++ のイベント文脈で同期呼び出しを維持する。

## Dependency migration note / 依存移行メモ

- `qutip`/`qutip_qip` の供給元はサブモジュールではなく `requirements.txt` に統一する。
- `qutip` はこの時点でリポジトリ管理対象から除外し、pip 依存として扱う。
- 既定運用は `qutip >=` 指定（今後 CI で安定後に固定化）。
- 検証コマンド:
  - `python3 scripts/check_qutip_import.py`

## Definition of Done (for initial migration) / 完了条件（初期移行）

- Default path remains `error_basis` and is behavior-compatible.
  - 既定経路が `error_basis` のままで、挙動互換であること。
- Physical operations are routed via `PhysicalServiceFacade`.
  - 物理操作が `PhysicalServiceFacade` 経由になっていること。
- Backend selection via config is documented and tested.
  - 設定によるバックエンド選択が文書化・テスト済みであること。
- Determinism + regression checks are in CI or runnable locally.
  - 決定性・回帰チェックが CI またはローカルで実行可能であること。

## Reviewer Checklist / レビュアーチェックリスト

- Is the default behavior unchanged?
  - 既定挙動は不変か？
- Is the backend interface minimal but sufficient?
  - バックエンドインターフェースは最小かつ十分か？
- Are logs sufficient for reproducibility/debugging?
  - ログは再現性・デバッグに十分か？
- Are tests proving compatibility and determinism?
  - テストで互換性と決定性が示されているか？
