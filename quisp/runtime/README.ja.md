# Runtime

> **English version**: see [README.md](README.md).

Runtime は RuleSet を実行するための環境です。
この Runtime 抽象により、RuleSet ベースの量子ネットワークに関する研究の中で、RuleSet 実行の挙動を解析できます。Runtime はシンプルなレジスタベースのマシンであり、シンプルな key-value メモリストアを持ちます。中間表現 (IR) で書かれた RuleSet を実行し、パートナーともつれ状態にあるアサイン済みキュービット、一時値（レジスタとメモリ）、フラグといった状態を管理する責任を持ちます。現在の Runtime 設計は、1) 実装とデバッグの容易さ、2) 命令の調整の柔軟さ、を重視しています。
@ref quisp::runtime も参照してください。

## 中間表現 (IR)

IR は Intel 構文に近く、「メモリ上の _KEY_ の値をレジスタ _REG0_ にロード」を `LOAD REG0 KEY` と書けます。デスティネーション (_REG0_) とソース (_KEY_) の順序に注意してください。IR はラベル付きのシンプルなアセンブリ言語のようなものです。Rule の Action と Condition は IR で記述され、その振る舞いを表現します。jump や branch 命令で制御フローを記述します。実装とデバッグの単純さのため、言語に if-else 文や for-loop 構文はありません。以下はランダム測定アクションの擬似コードと、その C++ 表現です。

```plaintext
  // メモリから "count" キーの値をレジスタにロード
  LOAD count "count"

  // partner_addr ともつれた n 番目のリソースキュービットへのポインタを q0 に得る。
  // キュービットは現在の Rule への割当順に並んでいる。
  // 見つからなければ qubit_found フラグを false にする。
  GET_QUBIT q0 partner_addr qubit_resource_index

  // qubit_found フラグが true なら QUBIT_FOUND ラベルへジャンプ
  BRANCH_IF_QUBIT_FOUND QUBIT_FOUND

  // 回復不能なエラーを発生させ実行停止
  RET ReturnCode::ERROR

QUBIT_FOUND: // ラベル

  // キュービット q0 を測定し結果を "outcome" キーに格納
  MEASURE_RANDOM "outcome" q0

  // count レジスタをインクリメント
  INC count

  // count レジスタの値をメモリの "count" キーに格納
  STORE "count" count

  // q0 を RuleSet から解放し、キュービットから q0 名を外す
  FREE_QUBIT q0

  // partner_addr にリンクトモグラフィの測定結果を送信
  SEND_LINK_TOMOGRAPHY_RESULT partner_addr count "outcome" max_count
```

C++ 表現の形式は `INSTR_{命令名}_{引数1の型}_{引数2の型}_` です。
これらは @ref Instruction テンプレートクラスのエイリアスで、`INSTR_ADD_RegId_RegId_int_{{REG0, REG1, 7}}` のように波カッコによる C++ 初期化子リストでインスタンス化できます。

```cpp
  // キュービットを扱うための qubit id を準備
  QubitId q0{0};
  // レジスタ 0 を count と命名
  auto count = RegId::REG0;
  int max_count = 1000;
  QNodeAddr partner_addr{3};
  auto qubit_resource_index = 0;
  simtime_t start_time = simTime();
  Label qubit_found_label{"qubit_found"};
  MemoryKey count_key{"count"};
  MemoryKey outcome_key{"outcome"};
  return Program{
      "Tomography",
      {
          // clang-format off
INSTR_LOAD_RegId_MemoryKey_{{count, count_key}},
INSTR_GET_QUBIT_QubitId_QNodeAddr_int_{{q0, partner_addr, qubit_resource_index}},
INSTR_BRANCH_IF_QUBIT_FOUND_Label_{qubit_found_label},
INSTR_RET_ReturnCode_{{ReturnCode::ERROR}},
INSTR_MEASURE_RANDOM_MemoryKey_QubitId_{{outcome_key, q0}, qubit_found_label},
INSTR_INC_RegId_{count},
INSTR_STORE_MemoryKey_RegId_{{count_key, count}},
INSTR_FREE_QUBIT_QubitId_{q0},
INSTR_SEND_LINK_TOMOGRAPHY_RESULT_QNodeAddr_RegId_MemoryKey_int_Time_{{partner_addr, count, outcome_key, max_count, start_time }}
          // clang-format on
      },
  };
```

## Runtime での RuleSet 実行

@htmlonly
<div class="mermaid">
   sequenceDiagram
        participant RE as RuleEngine
        participant RT as Runtime
        participant IV as InstructionVisitor
        participant CB as ICallBack

        RE->>RT: create Runtime and assign RuleSet
        RT->>IV: initialize
        RT->> CB: initialize
        RT->>RT: analyze the given RuleSet
        RE->>RT: assign qubit
        RE->>+RT: execute RuleSet
        loop Each Program Instruction execution
            RT->>+IV: execute Instruction
            IV->>IV: handle Instruction
            IV->>RT: call Runtime methods
            RT->>CB: call the Callback
            CB->>RE: quantum operation or classical communication
        end
        alt RuleSet not terminated
            RT->>-RE: finish RuleSet execution
        else RuleSet terminated
            RT->>RE: finish RuleSet execution
            RE->>RT: delete the RuleSet and the Runtime
        end
</div>
<script src="https://unpkg.com/mermaid/dist/mermaid.min.js"></script>
<script>mermaid.initialize({startOnLoad:true});</script>
@endhtmlonly

## ストレージスコープ

Runtime には 2 種類のストレージスコープがあります。
1 つは Program スコープで、Runtime は各 Program 実行前にこのストレージを初期化し、Program だけが読み書きできます。もう 1 つは RuleSet スコープで、すべての Rule が読み書きでき、Runtime は 1 度だけ初期化します。

## ストレージの種類

Runtime は Register、Memory、Flags、Qubits の 4 種類のストレージを持ちます。

### Register

Register は Program スコープのストレージで、1 つの数値を保持できます。簡単な算術演算や、RuleSet が行った測定回数の確認、Program で利用可能なキュービット数の確認などに使えます。

### Memory

Memory は RuleSet スコープのストレージで、MemoryKey で任意の値を保持できます。通常のコンピュータメモリと違い、シンプルさと安全性のため key-value ストアの形を取ります。RuleSet は総測定数のような RuleSet 全体で使う値を Memory に保持します。Memory の値を使うにはレジスタへロードする必要があります。

### Flags（pc, should_exit, terminated, error, return_code）

Flag は Program スコープのストレージで、制御フロー用の値を保持します。
Program はこれらの値に直接アクセスできません。

### Qubits

Qubits は RuleSet スコープのストレージで、他の QNode ともつれ状態にあるキュービットを保持します。RuleEngine がもつれキュービットを検出した際に、それらを何らかの Runtime に割り当てます。Runtime は割り当てられたキュービットを RuleSet 実行のリソースとして使えます。
