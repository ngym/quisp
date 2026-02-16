# QuISP `qutip` Backend: Operation kind coverage status

This table tracks `PhysicalOperation.kind` coverage for the current `qutip` backend
implementation status.

Legend:
- `registered` = `normalizeAdvancedKind`/alias in C++ and worker
- `worker status`:
  - `supported`: request is handled and returns a response
  - `simulated`: handled via deterministic/approximate response (not full qutip operator evolution yet)
  - `unsupported`: explicit fast-fail with `[category=unsupported_kind]`
- `qutip status`:
  - `implemented`: uses concrete `qutip` solver/operator paths
  - `simulated`: deterministic approximation path
  - `none`: not implemented yet

## Coverage table

| kind | aliases | C++ status | worker status | qutip status |
| --- | --- | --- | --- | --- |
| `unitary` | `X`,`Y`,`Z`,`H`,`S`,`T`,`I`,`RX`,`RY`,`RZ`,`SQRT_X`,`SQRTX`,`CX`,`CNOT` | registered | supported | mixed (qutip when installed / stub fallback) |
| `measurement` | `X`,`Y`,`Z`,`BELL` | registered | supported | simulated |
| `noise` | `dephasing`,`loss`,`reset` | registered | supported | simulated |
| `kerr` | `kerreffect`,`kerr_effect` | registered | supported | implemented |
| `cross_kerr` | `crosskerr`,`cross_kerr_effect` | registered | supported | implemented |
| `beam_splitter` | `beamsplitter`,`beam splitter` | registered | supported | implemented |
| `phase_shift` | `phaseshift`,`phase_shifter` | registered | supported | simulated |
| `phase_modulation` | `phase_mod`,`phase_modulator` | registered | supported | simulated |
| `self_phase_modulation` | `self_phase_mod`,`self_phase_modulator` | registered | supported | simulated |
| `cross_phase_modulation` | `cross_phase_mod`,`cross_phase_modulator` | registered | supported | simulated |
| `decoherence` | `decay` | registered | supported | simulated |
| `dephasing` | `dephase` | registered | supported | simulated |
| `nonlinear` | (direct) | registered | supported | simulated |
| `detection` | `dark_count`,`detector` | registered | supported | simulated |
| `delay` | (direct) | registered | supported | simulated |
| `hamiltonian` | `expr`/`hamiltonian` | registered | supported | implemented |
| `lindblad` | `expr`/`collapse` | registered | supported | implemented |
| `heralded_entanglement` | `heralded_entanglement` | registered | supported | simulated |
| `timing_jitter` | `jitter`,`time_jitter` | registered | supported | simulated |
| `dispersion` | `channel_dispersion`,`fibre_dispersion`,`fiber_dispersion` | registered | supported | simulated |
| `multiphoton` | `source_multiphoton`, `multiphoton_source` | registered | supported | simulated |
| `squeezing` | `squeezing` | registered | supported | simulated |
| `loss` | `attenuation` | registered | supported | simulated |
| `reset` | (direct) | registered | supported | simulated |
| `amplitude_damping` | (direct) | registered | supported | implemented |
| `thermal_relaxation` | (direct) | registered | supported | implemented |
| `bitflip` | (direct) | registered | supported | implemented |
| `phaseflip` | (direct) | registered | supported | implemented |
| `depolarizing` | (direct) | registered | supported | implemented |
| `polarization_rotation` | (direct) | registered | supported | simulated |
| `polarization_decoherence` | (direct) | registered | supported | simulated |
| `mode_coupling` | (direct) | registered | supported | simulated |
| `loss_mode` | (direct) | registered | supported | simulated |
| `two_mode_squeezing` | (direct) | registered | supported | simulated |
| `fock_loss` | (direct) | registered | supported | simulated |
| `photon_number_cutoff` | (direct) | registered | supported | simulated |
| `source_multiphoton` | `multiphoton_source` | registered | supported | simulated |

## Known intentional unsupported kinds

- `heralded_entanglement` is currently simulated and does not currently perform network-protocol-level feedback from a physical source module.
- `hamiltonian`/`lindblad` require non-empty expression/collapse payload; missing payload is explicitly rejected.
- All unrecognized kinds return explicit `unsupported_kind` with deterministic message.
