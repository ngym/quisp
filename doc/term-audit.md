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
