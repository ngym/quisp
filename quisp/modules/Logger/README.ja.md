# Logging

> **English version**: see [README.md](README.md).

Logger クラスはシミュレーションに関連するデータのロギングを担当します。

## 使い方

```cpp

using quisp::modules::Logger::LoggerBase

class SomeModule: public cSimpleModule, public LoggerBase {
    void initialize() override {
        // logger の初期化を忘れずに
        // どの logger を使うかは LoggerModule で定義される
        initializeLogger(provider);
    }

    void handleMessage(cMessage* msg) override {
        // LoggerBase で定義された logPacket メソッドを使える
        // msg は指定された logger の方法でログ出力される。既定は JsonLogger。
        logPacket("a label for the packet", msg);
    }
};

```

構造化イベントは `logEvent` で出力できます。

```cpp
logEvent("unknown_rule_event", "{\"simtime\": 1.0, \"event_type\": \"UNKNOWN\", \"msg_name\": \"raw\"}");
```

### このスコープで使う logEvent の契約

- 共通の構造化フィールド（payload レベル）:
  - `simtime` (float)
  - `event_number` (integer)
  - `module` (string)
  - `qnode_addr` (integer、利用可能な場合)
  - `parentAddress` (integer、利用可能な場合)
- `RuleEventBus` / `RuleEngine` のイベント payload は次を含む必要がある:
  - `msg_name`
  - `msg_type`
  - `protocol_spec`
  - `execution_path`
  - `protocol_raw_value`
- `Runtime` のイベント payload は次を含む必要がある:
  - `runtime_error`、`runtime_uncaught_error`、`runtime_debug_state`、`runtime_debug_source`、`runtime_debug_string`、`runtime_debug_qubit`、`runtime_debug_reg`
  - これらに加えて runtime 固有のキー（`message`、`instruction`、`return_code` など）
- `ConnectionManager` の unknown-control payload は次を含む必要がある:
  - `event_channel`
  - `is_self_message`
  - `known_qnic_index`
  - `msg_full_name`
  - `msg_class_name`

プロトコルベースの rule ディスパッチでは、ログ payload にプロトコル / パスのメタデータを含めます:

```cpp
logEvent("unknown_rule_protocol",
         "{\"simtime\": 1.0, \"event_number\": 123, \"event_type\": \"PURIFICATION_RESULT\", "
         "\"protocol_spec\": \"Unknown\", \"execution_path\": \"EntanglementLifecycle\", "
         "\"protocol_raw_value\": \"999\", \"msg_name\": \"pur_result\", \"msg_type\": \"purification::PurificationResult\"}");
```

`ConnectionManager` の unknown control message:

```cpp
logEvent("connection_manager_unknown_control_message",
         "{\"simtime\": 10.0, \"event_number\": 12, \"event_channel\": \"ProtocolMessage\", "
         "\"qnode_addr\": 5, \"parentAddress\": 5, \"is_self_message\": false, "
         "\"known_qnic_index\": -1, \"msg_full_name\": \"Unknown\", \"msg_class_name\": \"omnetpp::cMessage\"}");
```

プロトコルメタデータ値の例:

- `\"protocol_spec\": \"MIM Protocol v1\"`
- `\"protocol_spec\": \"MSM Protocol v1\"`

Runtime イベント契約（コアイベント種別）:

- `runtime_error`: `{ "message": string, "instruction": string }`
- `runtime_uncaught_error`: `{ "return_code": "3", "program_name": string }`
- `runtime_debug_state`: `{ "runtime state dump" }`
- `runtime_debug_source`: `{ "program source dump" }`
- `runtime_debug_qubit`: `{ "qubit_id": int, "found": bool, ... }`
- `runtime_debug_string`: `{ "message": string }`
- `runtime_debug_reg`: `{ "register": int, "value": int }`
