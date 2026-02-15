# Term audit commands (documentation check)

Run these checks before submitting protocol/link vocabulary-related changes:

```bash
# 1) Link/protocol naming conflict that should not appear
rg -n "MIM Protocol v1 Link|MSM Protocol v1 Link" doc quisp/modules --glob '!term-audit.md'

# 2) ProtocolType string expectations for logging
rg -n -P '(?:\\\"|")protocol_spec(?:\\\"|")\\s*:\\s*(?:\\\"|")(MIM Protocol v1|MSM Protocol v1|Purification|Swapping|LinkTomography|ConnectionManagement|Maintenance|Unknown)' doc quisp/modules
rg -n -P '(?:\\\"|")protocol_spec(?:\\\"|")\\s*:\\s*(?:\\\"|")[^\"]*Link' doc quisp/modules

# 3) Ensure MSM link reference exists
rg -n "MSM_Link\\.md" doc
```

Optional: add to CI as a dedicated static-doc check job for changed documentation files.

## Logging observability audit (this plan scope)

```bash
rg -n "std::cout|std::cerr" quisp/runtime quisp/modules/QRSA/ConnectionManager quisp/core/events --glob '*.{cc,h,cxx,hpp}'
rg -n "runtime_source_debug|runtime_debug_source|runtime_debug_state|runtime_debug_string|runtime_debug_reg|runtime_debug_qubit|runtime_error|runtime_uncaught_error" quisp
```
