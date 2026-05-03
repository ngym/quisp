# EPPS モジュールと MSM リンクアーキテクチャ

> **English version**: see [README.md](README.md).

QuISP の EPPS コンポーネントは 2 つのモジュール（EntangledPhotonPairSource と EPPSController）で構成されます。EntangledPhotonPairSource は物理モジュールで、2 つのポートからもつれ光子対を放出する役割を担います。一方 EPPSController は近接 QNode へのメッセージング・シグナリングを処理し、放出パートナー情報の送信や、最初の光子が到着すべき時刻の指定を行います。

## EntangledPhotonPairSource モジュール

EntangledPhotonPairSource は EPPSController から呼ばれた際にもつれ光子対を放出するだけのシンプルなモジュールです。

## EPPSController モジュール

EPPSController は MSM Link において近接 QNode へのメッセージング・シグナリングを管理します。また、放出パートナー情報を近接 QNode へ送信し、最初の光子が到着すべき時刻を指定します。

## 使い方

MSM Link を使うには NED ファイル中でいくつかのパラメータを設定する必要があります。以下に MIM Link との比較を伴う簡単な例を示します。

```ned
// MIM Link
    submodules:
        EndNode1: QNode
        EndNode2: QNode
        BSA: BSANode
    connections:
        EndNode1.port++ <--> ClassicalChannel {  distance = 0.5km; } <--> BSA.port++;
        BSA.port++      <--> ClassicalChannel {  distance = 0.5km; } <--> EndNode2.port++;
        EndNode1.quantum_port++ <--> QuantumChannel {  distance = 0.5km; } <--> BSA.quantum_port++;
        BSA.quantum_port++      <--> QuantumChannel {  distance = 0.5km; } <--> EndNode2.quantum_port++;

// MSM Link
    submodules:
        EndNode1: QNode
        EndNode2: QNode
        EPPS: EPPSNode
    connections:
        EndNode1.port++ <--> ClassicalChannel {  distance = 0.5km; } <--> EPPS.port++;
        EPPS.port++      <--> ClassicalChannel {  distance = 0.5km; } <--> EndNode2.port++;
        EndNode1.quantum_port_receiver_passive++ <--> QuantumChannel {  distance = 0.5km; } <--> EPPS.quantum_port++;
        EPPS.quantum_port++      <--> QuantumChannel {  distance = 0.5km; } <--> EndNode2.quantum_port_receiver_passive++;
```

記述は MIM Link に類似します。BSANode を EPPSNode に、QNode の `quantum_port` を `quantum_port_receiver_passive` に置き換えるだけです。

## EPPS モジュールに関わる MSM Link の詳細

EPPS controller は近接 QNode へ EPPSTimingNotification を送信します。次に EntangledPhotonPairSource は EPPSTimingNotification で指定された時刻と間隔で各 QNode へもつれ光子を送ります。RuleSet で指定された必要数のキュービットが生成されると、各 QNode は光子放出を停止し、StopEPPSEmission を EPPSController に送ります。EPPSController がこのメッセージを受信すると、EntangledPhotonPairSource からの連続放出も終了します。
