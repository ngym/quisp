# Term audit commands (documentation check)

Run these checks before submitting protocol/link vocabulary-related changes:

```bash
# 1) Link/protocol naming conflict that should not appear
rg -n "MIM Protocol v1 Link|MSM Protocol v1 Link" doc quisp/modules --glob '!term-audit.md'

# 2) Link protocol string expectations for ProtocolSpec/logging
rg -n "\"protocol_spec\": \"MIM Protocol v1\"|\"protocol_spec\": \"MSM Protocol v1\"" doc quisp

# 3) Ensure MSM link reference exists
rg -n "MSM_Link\\.md" doc
```

Optional: add to CI as a dedicated static-doc check job for changed documentation files.
