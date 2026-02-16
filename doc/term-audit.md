# Term audit commands (documentation check)

## Logging observability contract (source of truth)

The following list is the logging contract adopted for this logging-improvement scope.

- Common structured fields must be included in every log payload:
  - `simtime`
  - `event_number`
  - `event_type` (internal payload hint; for `unknown_*` etc in payload-level trace)
  - `module`
  - `qnode_addr`（該当時）
  - `parentAddress`（該当時）
- `RuleEngine`/`RuleEventBus` payload must include:
  - `msg_name`
  - `msg_type`
  - `protocol_spec`
  - `execution_path`
  - `protocol_raw_value`
- `Runtime` payload must include event-specific keys (at least one of):
  - `runtime_error`, `runtime_uncaught_error`, `runtime_debug_state`,
    `runtime_debug_source`, `runtime_debug_qubit`, `runtime_debug_reg`
- `ConnectionManager` unknown-control payload must include:
  - `event_channel`
  - `is_self_message`
  - `known_qnic_index`
  - `msg_full_name`
  - `msg_class_name`

Run these checks before submitting protocol/link vocabulary-related changes:

```bash
# 1) Link/protocol naming conflict that should not appear
rg -n "MIM Protocol v1 Link|MSM Protocol v1 Link" doc quisp/modules --glob '!term-audit.md'

# 2) ProtocolType string expectations for logging
rg -n -P '(?:\"|")protocol_spec(?:\"|")\s*:\s*(?:\"|")(MIM Protocol v1|MSM Protocol v1|Purification|Swapping|LinkTomography|ConnectionManagement|Maintenance|Unknown)' doc quisp/modules
rg -n -P '(?:\"|")protocol_spec(?:\"|")\s*:\s*(?:\"|")[^\"]*Link' doc quisp/modules

# 3) Ensure MSM link reference exists
rg -n "MSM_Link\\.md" doc
```

Optional: add to CI as a dedicated static-doc check job for changed documentation files.

## Logging observability audit (this plan scope)

### Logging contract (required payload fields)

- Common required fields for structured events:
  - `event_type`
  - `simtime`
  - `event_number`
  - `module`
  - `qnode_addr`（該当時）
  - `parentAddress`（該当時）
- `RuleEventBus` / `RuleEngine` required fields:
  - `msg_name`, `msg_type`, `protocol_spec`, `execution_path`, `protocol_raw_value`
- `Runtime` required fields:
  - `runtime_error`, `runtime_uncaught_error`, `runtime_debug_state`,
    `runtime_debug_source`, `runtime_debug_qubit`, `runtime_debug_reg`
- `ConnectionManager` required fields:
  - `connection_manager_unknown_control_message` event must contain
    `event_channel`, `is_self_message`, `known_qnic_index`,
    `msg_full_name`, `msg_class_name`

### Audit commands

```bash
rg -n "std::cout|std::cerr" quisp/modules/QRSA/RuleEngine quisp/runtime quisp/core/events quisp/modules/QRSA/ConnectionManager --glob '*.{cc,h,cxx,hpp}'
rg -n "runtime_error|runtime_uncaught_error|runtime_debug_state|runtime_debug_source|runtime_debug_qubit|runtime_debug_reg|unknown_rule_event|unknown_rule_protocol|connection_manager_unknown_control_message" quisp
rg -n "protocol_spec|execution_path|protocol_raw_value|event_number|msg_name|msg_type" quisp/core/events quisp/modules/QRSA quisp/modules/Logger
```

# Logging policy checks to prevent old terms from reappearing

```bash
# 1) Link/protocol naming mix that should not remain
rg -n "MIM Protocol v1 Link|MSM Protocol v1 Link" quisp doc

# 2) Logging metadata and event contract checks
rg -n "runtime_error|runtime_uncaught_error|runtime_debug_state|runtime_debug_source|runtime_debug_qubit|runtime_debug_reg|unknown_rule_event|unknown_rule_protocol|connection_manager_unknown_control_message" quisp
rg -n "protocol_spec|execution_path|protocol_raw_value|event_number|event_type|event_type\":|msg_name|msg_type|qnode_addr|parentAddress" quisp/core/events quisp/modules/QRSA quisp/modules/Logger quisp/runtime
```
