# QuISP ドキュメント・ヒッチハイカーズ・ガイド

> **English version**: see [README.md](README.md).

## 目次

* [ユーザガイド](#ユーザガイド)
  * [導入とインストール](#導入とインストール)
  * [科学と工学](#科学と工学)
* [コントリビュータガイド](#コントリビュータガイド)
  * [ハードウェア](#ハードウェア)
  * [ソフトウェア](#ソフトウェア)
* [MetaQuISP](#metaquisp)


## ユーザガイド

[インストール (GitHub Wiki)](https://github.com/sfc-aqua/quisp/wiki)

### 科学と工学

* [研究上の問い](Research%20Questions.md)
* [量子状態の表現](Quantum%20State%20Representations.md)
* [数学: Operator Sum](OperatorSum.md)
* [数学: 誤りモデル](ErrorModels.md)
* [量子インターネットの主要設計判断](Major%20Design%20Decisions.md)
* [Rule Sets](RuleSet.md)
* [量子エンドノードアーキテクチャ](EndNode%20Architecture.md)
* [Path Setup](Path%20Setup.md)
* [Flat Path（単一ネットワーク）セットアップ処理](FlatPathSetup%20Processing.md)
* [Path セットアップ応答メッセージの内容](FlatPathSetupReturn%20Message%20Contents.md)
* [再帰的なパスセットアップ: 内部ネットワーキング事例](Recursive%20Path%20Setup.md)
* [MIM Link](MIM_Link.md)
* [MSM Link](MSM_Link.md)
* [もつれの生成](Making_Entanglement.md)
* [リソース割当](Resource_Allocation.md)
* [リンクのシミュレーション例](SimLink.md)
* [研究上の問い: 「Standalone Path Performance」](Standalone%20Path%20Performance.md)
* [qDijkstra: purify-and-swap 網の SPF](qDijkstra.md)
* [分散トモグラフィと状態モニタリング](Distributed%20Tomography%20and%20State%20Monitoring.md)
* [研究上の問い: 「Unconnectable」](Unconnectable.md)

## コントリビュータガイド

### ハードウェア

* [ネットワーク非依存の運用挙動](Repeater%20Operation.md)
* [Bell State Analyzer (BSA) ノード (Bnode)](BSA%20Node.md)
* [Beam splitter](Beam_splitter.md)
* [Classical Chassis Control Card (C4)](Classical%20Chassis%20Control%20Card%20(C4).md)
* [God Channel](God%20Channel.md)
* **ハードウェア要素**
  * [ハードウェア要素: もつれ光子対源 (EPPS)](HE_EPPS.md)
  * [ハードウェア要素: メモリ](HE_Memory.md)
  * [ハードウェア要素: Optical Bell State Analyzer (OBSA)](HE_OBSA.md)
  * [ハードウェア要素: 光物理チャネル](HE_OptChannel.md)
  * [ハードウェア要素: 光スイッチ](HE_OptSwitch.md)
  * [ハードウェア要素のシミュレーション](Hardware%20Element%20Simulation.md)
  * [ハードウェア要素](Hardware%20Elements.md)
* [QNIC: ハードウェアとソフトウェア](QNIC.md)
* [QNIC コントローラのメソッド](QNIC_Methods.md)
* [リアルタイムハードウェアコントローラ](Real-Time%20Hardware%20Controller.md)
* [Repeater](Repeater.md)
* [量子ルータアーキテクチャ](Router%20Architecture.md)

### ソフトウェア

* [研究上の問い: 輻輳崩壊 (Congestion Collapse)](Congestion%20Collapse.md)
* [接続生成](Connection%20Creation.md)
* [Connection Manager](Connection%20Manager.md)
* [マルチホップパスの確立: Dur-Briegel ケース](Dur-Briegel%20Path%20Setup.md)
* [Dur-Briegel RuleSet 生成](Dur-Briegel_Example_RuleSets.md)
* [Fowler 2G ネットワーク向け RuleSet](Fowler%20Example%20RuleSets.md)
* [パスのセットアップ: Fowler ケース](Fowler%20Path%20Setup.md)
* [Hardware Configuration Manager のメソッド](HardwareConfigManager_Methods.md)
* [Jiang Example RuleSets](Jiang%20Example%20RuleSets.md)
* [主要機能コンポーネントの仕様（緩い形）](Major%20Functionality%20Descriptions.md)
* [対応する量子リピータネットワークの種類](Network%20Types.md)
* [量子リピータアーキテクチャ](Repeater%20Architecture.md)
* [量子ルータ（リピータ）ソフトウェアアーキテクチャ](Router%20Software%20Architecture.md)
* [Routing Daemon](Routing%20Daemon.md)
* [接続のためのルーティング](Routing.md)
* [Rule Engine](Rule%20Engine.md)
* [コードスペランキング: 最初の探索](code-spelunking.md)
* [QuISP のソフトウェア設計](software-design.md)

## MetaQuISP

* [よくある質問 (FAQ)](FAQ.md)
* [初期要件・判断](InitialRequirements.md)
* [References](References.md)
* [Role Assignment](Role_Assignment.md)
* [用語集](Terminology.md)
* [Workloads](Workloads.md)
