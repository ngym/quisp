# Bell State Analyzer

QuISP では、リピータと終端ノードが photon train の開始と終了を BSA モジュールに知らせる暗黙の機構があると仮定します（例: 各 train の前後に強い光パルスを送信する等）。
QuISP では `STATIONARY_PULSE_XXX` フラグでこれを実現しており、`<XXX>` には `BEGIN`, `END`, `BOUND` のいずれかが入ります。

注意: vNext 設計では、量子側の誤差・ロス状態を OMNeT メッセージのフラグで運ばない。
到着・ロスや BSA クリック結果はバックエンドが完結し、古典結果としてのみ返される。

QuISP の BSA は `BellStateAnalyzer` と `BSAController` の 2 モジュール構成。
`BellStateAnalyzer` は物理モジュールで、両ポートから到着する光子の測定だけを担当する。
`BSAController` は近隣 QNode との通信・シグナリングを扱い、測定結果送信や「最初の光子はいつ届くか」の通知を行う。

BSA は QNIC 内 (QNIC_R = QNIC receiver と呼ぶ) に置かれる場合と、独立ノード (BSANode) に置かれる場合がある。
QNIC 内・BSANode 内のいずれでも機能は同じ。
違うのは `BSAController` の初期化フェーズだけで、入力チャネルや通信相手の QNode を辿るためのモジュール階層トラバース方法が異なる。

## BellStateAnalyzer モジュールの動作

BellStateAnalyzer は状態機械で振る舞いを管理する。状態は `idle`, `accepting`, `accepting_left`, `accepting_right` の 4 つ。
現状は両側からの最後の光子が届くまで全光子をキャッシュし、バッチ処理で結果をまとめて BSAController にシグナルを送り、QNode へ送信する。

QuISP では、BSA は $\ket{\Psi^+}$ と $\ket{\Psi^-}$ を区別できるが $\ket{\Phi^+}$ と $\ket{\Phi^-}$ は区別できないと仮定する。
このため、ロス・誤差・暗計数すべて理想 (0) でも成功確率は 50% に制限される。

BSA の擬似コード:

パラメータ
```python
record_left = []
record_right = []
state = 'idle' | 'accepting_left' | 'accepting_right' | 'accepting'
indistinguish_time_period = 'positive number in (ns)'
# backend.detect(p_handle, q_handle) は以下を返す
#   {outcome_pattern: 'dAh,dAv'|'dBh,dBv'|'dAh,dBv'|'dAv,dBh'|'dAh'|'dAv'|'dBh'|'dBv'|'none'|..., detection_click_count: int, ...}
# パターン文字列は厳密一致 (正規化なし)。
# 成功パターン:
#   ψ+: dAh,dAv または dBh,dBv
#   ψ−: dAh,dBv または dAv,dBh
# 失敗パターン:
#   dAh, dAv, dBh, dBv, none
# dAh = 検出器 A、水平偏光ブランチ
# dAv = 検出器 A、垂直偏光ブランチ
# dBh = 検出器 B、水平偏光ブランチ
# dBv = 検出器 B、垂直偏光ブランチ
# 光学 BSA モデルのバックエンドコントラクト:
#   hom_interference -> 2 入力モードへの 50:50 HOM 相当ミキシング
#   detection -> PBS + 4 検出器読み出し
#   ψ+: dAh,dAv または dBh,dBv
#   ψ−: dAh,dBv または dAv,dBh
```

状態管理部
```python
def processArrivalPhotons(photon):
    if (state == 'accepting right' and photon.from_left) \
        or (state == 'accepting left' and photon.from_right) \
        or (state == 'idle' and not photon.first):
        discardPhoton(photon)
        return

    if state == 'idle':
        state = 'accepting'

    if photon.from_left:
        record_left.append(photon)
    else:
        record_right.append(photon)

    if photon.last and state == 'accepting':
        if photon.from_left:
            state = 'accepting right'
        else:
            state = 'accepting left'
    elif photon.last:
        state = 'idle'
        processRecords()
```

キャッシュ済み結果の処理
```python
def processRecords():
    results_list = []
    for left_photon, right_photon in zip(record_left, record_right):
        if abs(left_photon.arrive_time - right_photon.arrive_time) <= indistinguish_time_period:
            results_list.append(process_indistinguish_photons(left_photon, right_photon))
        else:
            results_list.append('fail')
```

両方の光子が識別不可能時間窓内に到着した場合
```python
def process_indistinguish_photons(p, q):
    # Bell 状態と検出はバックエンドで完結する。
    # OMNeT 側ロジックは古典 outcome pattern のみを消費する。
    detection = backend_detection(p, q)

    if detection.outcome_pattern in {'dAh,dAv', 'dBh,dBv'}:
        # ψ+ outcome
        # Pauli-X correction
        return 'success', 'Phi+'
    if detection.outcome_pattern in {'dAh,dBv', 'dAv,dBh'}:
        # ψ− outcome
        # Pauli-Y correction
        return 'success', 'Phi+'
    return 'fail'
```

### BSA correction の規約
両側のメモリ-光子もつれは H + CNOT で $\ket{\Phi^+} = (\ket{00}+\ket{11})/\sqrt{2}$ として用意される。swap-test identity より
$$\ket{\Phi^+}_{M_A P_A} \otimes \ket{\Phi^+}_{M_B P_B} = \tfrac{1}{2}\sum_\beta \ket{\beta}_{M_A M_B}\otimes\ket{\beta}_{P_A P_B}$$
が成り立つので、2 光子を Bell 状態 $\ket{\beta}$ に射影すれば 2 メモリも $\ket{\beta}$ に残る。tomography は $\ket{\Phi^+}$ を基準にするため、右側メモリを $\ket{\Phi^+}$ に補正する:

| 検出パターン | 光子 Bell 状態 | メモリの状態 | 補正 (右側) |
| --- | --- | --- | --- |
| `dAh,dAv` または `dBh,dBv` | $\ket{\psi^+}$ | $\ket{\psi^+}$ | $X$  ($X_B\ket{\psi^+} = \ket{\Phi^+}$) |
| `dAh,dBv` または `dAv,dBh` | $\ket{\psi^-}$ | $\ket{\psi^-}$ | $Y$  ($Y_B\ket{\psi^-} = -i\ket{\Phi^+}$) |
| `dAh`, `dAv`, `dBh`, `dBv`, `none` | $\phi$ 様 / 単一クリック | 線形光学では区別不能 | 失敗 |
