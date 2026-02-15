# MSM Link #

*Note: this file is a minimal architectural pointer for terminology alignment.
For implementation details, see the corresponding hardware module docs.*

## What is MSM Link?

`MSM Link` is a link architecture where each node has an internal link module for entangled-photon mediated entanglement generation.
In this architecture, the protocol identifier used in protocol dispatching and logs is `MSM Protocol v1`
(via `ProtocolSpec::MSM_v1`).

## Related modules

- EPPS and the MSM Link module walkthrough (`quisp/modules/PhysicalConnection/EPPS/README.md`)
- MSM path in RuleEngine (`quisp/modules/QRSA/RuleEngine/README.md`)
- BSA node / link-generation context (`HE_OBSA.md`, `BSA%20Node.md`)

## Related protocol identifier

- `MSM Protocol v1` (protocol context, not link context)
