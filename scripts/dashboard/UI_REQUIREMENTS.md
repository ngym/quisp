# QuISP Dashboard UI Requirements

このドキュメントは QuISP Dashboard の **再設計の要件定義** です。実装は段階的に行いますが、画面構造・命名・表示原則の基準として参照します。

> **English readers**: this document is intentionally kept in Japanese to match the primary research audience. Pull requests welcome to add an English mirror.

## 1. ペルソナ

### 主人公: 量子ネットワーク研究者
- 教授 / ポスドク / 大学院生
- 仮説検証のためにシミュレーションを回す
- 1 件の絶対値より、複数 run の **差分・傾向** に価値を見出す
- 結果は最終的に論文・プレゼンに貼る図か数値表になる
- 「異常な run」 を見つけたらその瞬間にステップ実行で原因を突き止めたい

### 副ペルソナ
- **シミュレーションオペレータ**: 大量 sweep を回したい
- **開発者**: Replay でバグ追い
- **デモ・教育担当**: 動いている様子を一目で見せる

UI は主人公に最適化し、副ペルソナの導線は阻害しない範囲で確保する。

## 2. 概念モデル

研究者の頭の中の概念を一級オブジェクトとして扱う:

| 概念 | 意味 | 一級か |
|---|---|---|
| **Study** | 1 つの仮説 + その検証のための実験設計 | ★ 一級 |
| **Run** | 1 回のシミュレーション | ★ 一級 |
| Configuration | パラメータ 1 セット (template + config + override) | Study に内包 |
| Sweep / Campaign | パラメータ軸を振りながら回す run 集合 | Run の集合体 |
| Result | run / sweep の出力 (KPI / event log / topology) | Run の属性 |

## 3. 典型タスクとフェーズ

```
[Plan] → [Setup] → [Launch] → [Observe] → [Analyse] → (loop back)
```

| フェーズ | 研究者がやりたいこと |
|---|---|
| Plan | 仮説と実験範囲を決める |
| Setup | template と config と override を組む |
| Launch | 1 run / sweep を起動 |
| Observe | 実行中・実行直後の振る舞い確認 |
| Analyse | 複数 run の KPI 比較・異常 run のステップ実行 |

## 4. 情報アーキテクチャ

トップレベル左ナビは **タスク軸** で 4 項目:

```
Studies   → 仮説と実験設計の一覧 (デフォルト画面)
Runs      → 個別 run の履歴・検索・詳細・Replay
Library   → 再利用可能な template / profile / override
Settings  → 環境設定・QuISP バイナリ・出力先
```

### 4.1 Studies 画面

```
Study: <name>
  仮説: <短い要約>
  ────────────────────────────────────────
  [Setup]  [Sweep]  [Runs]  [Results]  [Notes]
```

- **Setup**: configuration builder (template / config / override 一画面)
- **Sweep**: parameter × seed のマトリクス
- **Runs**: この study に紐づく run の一覧と一行 KPI サマリ
- **Results**: sweep 単位の KPI 集計表 + プロット
- **Notes**: 仮説・観察の自由記述 (Markdown)

### 4.2 Run 詳細画面

個別 run の深掘り。Studies の Runs タブから来るのが主導線。

```
Run: <name> #<id-suffix>
  Study: ... | Status: ...
  ────────────────────────────────────────
  KPI summary (常時固定)
  ────────────────────────────────────────
  [Topology]  [Replay]  [Events]  [Config]
```

ここでは **データの見方軸** のタブで OK。run という単一対象の見方の違いだから。

### 4.3 旧 Monitor タブの扱い
旧 Monitor タブ専用画面は **廃止**。`status === running` の run を Run 詳細で開いたとき、Topology タブが自動でライブモードになる。

## 5. 表示原則 (全画面共通)

### 5.1 ヘルプ
- フィールドラベルは短く (例: `Seed Set`)
- 説明は **`(?)` icon の hover ツールチップ** に格納する。常時表示しない
- 例示は input の `placeholder` で
- 長文ヘルプは `Advanced inputs` を開いたときのみ・または別 Help ページに

### 5.2 数値・ID 軸の区別
| 軸 | 表記 |
|---|---|
| simulation time | `t=12.000s` |
| OMNeT++ scheduler event id | `sim event #11432` (prefix 必須) |
| dashboard cursor / JSON event index | `cursor 3472` / `visible event N / M` |

同じカードに 2 軸並ぶときは別段に組む。

### 5.3 時刻表示
- 実時刻: 直近 60 分は `Xm ago`、それ以前は `MM/DD HH:mm:ss` 短縮、tooltip でフル日時
- sim 時間: 秒+小数 6 桁固定 `12.000000s`

### 5.4 状態色
| level | 用途 |
|---|---|
| `ok` (緑) | 完了・正常 |
| `warn` (黄) | 終わったけど怪しい (no output / emission_success_probability=1 等) |
| `bad` (赤) | failed / terminated / error |
| `idle` (灰) | 未選択 |
| `live` (青パルス) | running 中だけ |

### 5.5 比較ファースト
- 単一 run の絶対値の前に「期待される範囲か」 が分かる文脈を添える
- ベースライン値が手元に無い段階では、ユーザが手動で sweep を組んで比較できる Sweep view を最低ラインとして提供する

### 5.6 言語
- UI ラベル・操作系ボタン: **日本語**
- 量子・OMNeT++ 用語は英語のまま (`BellPair`, `Fidelity`, `RuleSet`, `cursor`, `sim_time`)
- 1 ボタン内で日英を交ぜない

### 5.7 物理モデルの仮定を常に見せる
- 「理想モデル」 バナーを Setup と Results の両方で表示する
- 物理パラメータが現実値からどれだけ離れているかを Setup 画面で図示

## 6. データ可視化原則

| 種類 | 用途 | x 軸 / y 軸 |
|---|---|---|
| Topology canvas | 物理リンクと quantum link を色とアニメーションで識別 | xy 座標 |
| Time series | bin 秒ごとの ev/sim-s | sim_time / 件数 |
| Sweep plot | parameter 軸 vs metric | parameter / metric (seeds が分散) |
| Histogram | Fidelity / setup latency 分布 | metric / 件数 |

時間軸はデフォルトで **sim_time**(researcher は実時刻でなく sim_time が知りたい)。

## 7. Performance / リアルタイム性要件

| 項目 | 要件 |
|---|---|
| Activity スナップショット遅延 | 最大 1 秒 |
| Sweep KPI 集計 (100 runs) | 5 秒以内 |
| Topology 描画 ノード数上限 | 500 ノード(視野内)。超えたら zoom + viewport culling |

WebSocket 化は必須要件ではない。同時実行 sweep の進捗一括監視を作る段階で再評価する。

## 8. 実装フェーズ

### Phase 1 (このブランチで完了)
- 表示原則の整備: ID 軸、ラベル統一、ジッタ OFF、警告バナー、hover tooltip
- KPI ラベルのモード間固定
- silent fail (no output) 検出
- ID 軸の prefix 表示

### Phase 2 (次の作業)
- **Sweep / 比較 UI を中途以上に作り込む** (最重要)
  - 現 `Compare Runs` と `Campaign batch execution` を統合
  - Sweep parameter × metric のプロット
- ヘルプの tooltip 化 (常時表示の説明文を整理)
- Run 詳細を単独画面に切り出す
- Library 相当のパネル化 (template / config / override 整理)

### Phase 3 (中期)
- `Studies` トップ画面を新設
- 仮説 + Setup + Sweep + Runs リスト + Results を 1 画面に
- Monitor タブを Run 詳細の Topology ライブモードに吸収して廃止

### Phase 4 (長期)
- Sweep プロット (parameter vs metric) の高度化 (エラーバー / 複数 metric)
- Comparison view の拡張 (統計検定)
- Notes (仮説 / 観察) 機能
- エクスポート (CSV / PNG / 論文用テーブル)

## 9. 非目標

- パスワード認証付きの multi-user 管理は範囲外 (将来 Settings で扱う可能性)
- リアルタイム同時編集は範囲外
- mobile 表示の最適化は範囲外 (デスクトップワークステーション前提)
