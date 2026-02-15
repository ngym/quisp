# QuISPのソフトウェア設計 / Software Design for QuISP

# Software Design for QuISP

As we saw while [code spelunking](code-spelunking.md), the source code
is also [documented using doxygen](html/index.html).  You may wish to
attempt to match items from these design documents to some of the
code.

私たちが[コードを読み進める](code-spelunking.md)中に見たように、
ソースコードは[doxygen](html/index.html)でも文書化されています。
この設計ドキュメントの項目を実際のコードと照合すると、理解が深まります。

n.b.: Most of these design documents were created in a couple of
extended bursts of group work, actually quite some time ago.  After
that design work, implementation proceeded with most of the
core elements of the design intact, but we all know that a design never
survives the first attempt to implement it unaltered.  If you find
places where these docs differ from reality, we encourage you to
submit pull requests to make one conform to the other -- which way, we
will leave to your judgment.

注: これらの設計文書の多くは、比較的まとまったグループ作業の期間に作成されたもので、
作成からかなり時間が経っています。実装は当時の設計の主要要素を残したまま進められましたが、
設計はそのまま実装しても初回では必ず何らかの修正が必要になるのが常です。
もしドキュメントと実装で食い違いがあれば、どちらをどちらに合わせるかは判断に委ねつつ、
プルリクエストで整合を図ることを推奨します。

Also, these designs document a dream: the initial releases are _far_
from completing all of this!  Especially, as of this writing, only
first-generation (1G) repeaters are implemented _at all_.  2G and 3G
are Future Work.

また、これらの設計は「理想像」を記述しています。初期リリースでは、
これらがすべて実装されているわけではありません。とくに執筆時点では、
第一世代（1G）のリピータしか実装されておらず、2G/3G は今後の課題です。

# Welcome to the QUISP project.

# QUISPプロジェクトへようこそ。

Our goals are

Our goals are:

1. to determine if it is *possible* to build a
quantum Internet (defined as a global network of networks utilizing
very distinct technical approaches);
1. to assess the *robustness* of such an internetwork in the face of evolving
technology, deployment, and workload;
1. to establish some key *design decisions* that will help us build a robust, long-lived network; and
1. finally, to feed back what we have learned to the
experimental community to guide future development.

1. 非常に異なる技術アプローチを統合するグローバルネットワークとしての
量子インターネットを、*構築可能か*どうか検証すること。
2. 技術進展、導入状況、負荷の変化に対して、このようなネットワークの
*堅牢性*を評価すること。
3. 長寿命で堅牢なネットワークを実現するための重要な*設計判断*を定めること。
4. 学んだ知見を実験コミュニティへ還元し、将来の開発の指針を示すこと。

The simulator also serves as a platform for future development of
increasingly real-world source code, and for simulations of evolving
technologies and approaches.  We hope to make the simulator available
as a service via the web, and possibly to open source the simulator.

シミュレータは、より実用に近いソースコードの将来的開発基盤として、
さらに技術・手法の発展に伴うシミュレーション環境としても機能します。
将来的には、Web サービスとして利用可能にし、オープンソース化することも検討しています。

# Orientation

# オリエンテーション / Orientation

- [Research Questions / 研究課題](Research%20Questions.md)
- [Terminology / 用語](Terminology.md)
- [Quantum State Representations / 量子状態表現](Quantum%20State%20Representations.md)
- [The story for a first SIGCOMM paper / 第1回SIGCOMM論文のストーリー](The%20Story.md)

# Design Vocabulary / 用語定義

- Link architecture context: `MIM Link`, `MSM Link`.
- Protocol context: `ProtocolType` values (for event dispatch and logs) use:
  - `MIM Protocol v1`
  - `MSM Protocol v1`
  - `Purification`
  - `Swapping`
  - `LinkTomography`
  - `ConnectionManagement`
  - `Maintenance`
- RuleEngine dispatch decisions use `RuleEventKind` + `ProtocolType`.

`MIM Protocol v1` / `MSM Protocol v1` are protocol identifiers only; they should not be used as architecture names.
`MIM Link` / `MSM Link` are link architecture names.

# Decisions

- [Major Design Decisions / 主要設計方針](Major%20Design%20Decisions.md)
- [Major Functionality Descriptions / 主要機能の説明](Major%20Functionality%20Descriptions.md)

# Nodes and Links

# ノードとリンク / Nodes and Links

- [Router Architecture / ルータアーキテクチャ](Router%20Architecture.md) (with links to hardware modules)
- [Router Software Architecture / ルータソフトウェアアーキテクチャ](Router%20Software%20Architecture.md) (with links to software modules)
- [Repeater / リピータ](Repeater.md)
- [End Node / エンドノード](End%20Node.md)
- [BSA Node / BSAノード](BSA%20Node.md) (Bell State Analyzer)
- [EPPS / エンタングルド光子対光源 (EPPS)](EPPS.md) (Entangled Photon Pair Source)
- [Channel / チャネル](Channel.md)

# Networks, Protocols and Operations

# ネットワーク、プロトコル、運用 / Networks, Protocols and Operations

- [Path Setup / 経路確立](Path%20Setup.md)
- [Rule Sets / ルールセット](RuleSet.md)
- [Routing / ルーティング](Routing.md)
- [Resource Allocation / リソース割り当て](Resource%20Allocation.md)
- [Distributed Tomography and State Monitoring / 分散トモグラフィーと状態監視](Distributed%20Tomography%20and%20State%20Monitoring.md)

# Simulation

# シミュレーション / Simulation

- [SimulatorSourceStructure / シミュレータソース構成](SimulatorSourceStructure.md)
- [InitialRequirements / 初期要件](InitialRequirements.md)
- [Datasets / データセット](Datasets) we intend to collect to write papers with (reach topology and workload discussions through here)
- [Link Simulation Example / リンクシミュレーション例](SimLink.md)
- [Simulating Errors / 誤差シミュレーション](ErrorModels.md)
- [Physical Layer Backend Strategy / 物理層バックエンド戦略](PhysicalLayerBackendStrategy.md)

# Other

# その他 / Other

- [References / 参考文献](References.md)
- See also the [Open Issues](https://github.com/sfc-aqua/quisp/issues) on github.
- GitHubの[Open Issues](https://github.com/sfc-aqua/quisp/issues)も参照してください。
