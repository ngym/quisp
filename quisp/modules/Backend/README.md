# Backend Interface Contract (vNext)

> **日本語版**: [README.ja.md](README.ja.md) を参照してください。

This document specifies the rules of responsibility separation between the
OMNeT side and the physical backend.

## 1) Principles
- Quantum state operations, noise, and measurement are, in principle,
  executed by the backend; the OMNeT side handles **classical information
  only**.
- `QuantumChannel` does not update state directly — it just calls
  `applyErrorChannel(...)` once.
- `BellStateAnalyzer` likewise decides outcomes from the results of
  `hom_interference` and `detection` (`outcome_pattern`) and does not
  inspect the quantum state directly.

## 2) Meaning of `OperationResult`
The `OperationResult` defined in
`quisp/modules/Backend/IPhysicalBackend.h` is both classical information
and the execution result.

- `success`: whether the backend call itself succeeded
- `discarded`: discard from a management event (expired / cutoff)
  - **a lifetime / resource-reclamation event decided by the OMNeT /
    scheduler side**
  - does not represent physical photon loss
- `photon_lost`: loss as a physical phenomenon (channel attenuation /
  loss)
  - **a physical-loss flag decided by the backend**
- `discard_reason`: e.g. `"expired"`, `"cutoff"`, `"photon_loss"`
- `outcome_pattern`: detection-pattern result of the BSA etc. (e.g.
  `dAh,dAv` / `dBh,dBv` / `dAh,dBv` / `dAv,dBh` / `dAh` / `dAv` / `dBh` /
  `dBv` / `none`)
- `detection_click_count` / `detector_histogram` / `classical_payload`:
  auxiliary information used in BSA analysis

### Terminology clarifications

- `discarded` and `photon_lost` can overlap but are distinct concepts.
  - `discarded=true` means "operationally, do not reference any further".
  - `photon_lost=true` means "quantum information is physically
    unreachable / lost".
- OMNeT-side logic does not run state transitions / noise; it basically
  uses both flags only for reading purposes.

- `outcome_pattern` uses a strict comparison without string
  normalization.
  - It does not accept legacy `d0`-style strings or reordered
    representations.

## 3) Representative APIs
- `applyErrorChannel(qubit_ids, channel_profile_name, params)`
- `applyHomInterference(qubit_ids, params)`
- `applyDetection(qubit_ids, params)`

### Expected interpretations
- BSA-side modules decide qubit arrival / success solely from
  `outcome_pattern`.
- `discarded` / `photon_lost` are used as supplementary signals for the
  decision.
  - `discarded`: management-side lifetime / disconnect, etc.
  - `photon_lost`: physical propagation loss

## 4) Position of the GraphState backend (`ErrorBasisBackend`)
- Pauli noise is applied directly to the stabilizer state via real
  `noiselessX`/`noiselessZ` gates; no error flags are tracked.
- `discarded`, `photon_lost` are kept only as backend-internal metadata.
- The OMNeT-side `PhotonicQubit` messages do not read error flags.

## 5) qutip profile contract (vNext)
- `qutip_density_matrix` operates with a single `qutip_profile`
  configuration.
- `qutip_node_profile` / `qutip_link_profile` are unsupported
  (`invalid_profile`).
- `qutip_profile_overrides` accepts only `dim`, `leakage_enabled`,
  `truncation`.
- `entanglement_set_id` is shared across all operations; there is no
  separation by `mode`.
