# QuISP `qutip` Backend: Operation kind coverage status

This table tracks `PhysicalOperation.kind` coverage for the current `qutip` backend
implementation status.

Legend:
- `registered` = `normalizeAdvancedKind`/alias in C++ and worker
- `support status`:
  - `supported`: request is handled and returns a response
  - `unsupported`: explicit fast-fail with `[category=unsupported_kind]`
- `operation_model`:
  - `unitary`: unitary/Heisenberg-like update (or equivalent exact operator map)
  - `kraus`: Kraus/CP-map update
  - `sampled_kraus`: outcome-sampled update (e.g., `detection`)
  - `formula`: compact deterministic approximation update
  - `unsupported`: request rejected

## Coverage table

| kind | aliases | C++ status | support status | operation_model |
| --- | --- | --- | --- | --- |
| `unitary` | `X`,`Y`,`Z`,`H`,`S`,`T`,`I`,`RX`,`RY`,`RZ`,`SQRT_X`,`SQRTX`,`CX`,`CNOT` | registered | supported | unitary |
| `measurement` | `X`,`Y`,`Z`,`BELL` | registered | supported | sampled_kraus |
| `noise` | `dephasing`,`loss`,`reset` | registered | supported | kraus |
| `kerr` | `kerreffect`,`kerr_effect` | registered | supported | unitary |
| `cross_kerr` | `crosskerr`,`cross_kerr_effect` | registered | supported | unitary |
| `beam_splitter` | `beamsplitter`,`beam splitter` | registered | supported | unitary |
| `phase_shift` | `phaseshift`,`phase_shifter` | registered | supported | unitary |
| `phase_modulation` | `phase_mod`,`phase_modulator` | registered | supported | unitary |
| `self_phase_modulation` | `self_phase_mod`,`self_phase_modulator` | registered | supported | unitary |
| `cross_phase_modulation` | `cross_phase_mod`,`cross_phase_modulator` | registered | supported | unitary |
| `decoherence` | `decay` | registered | supported | kraus |
| `dephasing` | `dephase` | registered | supported | kraus |
| `nonlinear` | (direct) | registered | supported | unitary |
| `detection` | `dark_count`,`detector` | registered | supported | sampled_kraus |
| `delay` | (direct) | registered | supported | formula |
| `hamiltonian` | `expr`/`hamiltonian` | registered | supported | unitary |
| `lindblad` | `expr`/`collapse` | registered | supported | kraus |
| `hom_interference` | `hom`, `twophoton_interference`, `two_photon_interference`, `bs_interference`, `bsinterference` | registered | supported | unitary |
| `timing_jitter` | `jitter`,`time_jitter` | registered | supported | formula |
| `dispersion` | `channel_dispersion`,`fibre_dispersion`,`fiber_dispersion` | registered | supported | formula |
| `multiphoton` | `source_multiphoton`, `multiphoton_source` | registered | supported | formula |
| `squeezing` | `squeezing` | registered | supported | formula |
| `loss` | `attenuation` | registered | supported | kraus |
| `reset` | (direct) | registered | supported | kraus |
| `amplitude_damping` | (direct) | registered | supported | kraus |
| `thermal_relaxation` | (direct) | registered | supported | kraus |
| `bitflip` | (direct) | registered | supported | kraus |
| `phaseflip` | (direct) | registered | supported | kraus |
| `depolarizing` | (direct) | registered | supported | kraus |
| `polarization_rotation` | (direct) | registered | supported | unitary |
| `polarization_decoherence` | (direct) | registered | supported | kraus |
| `mode_coupling` | (direct) | registered | supported | unitary |
| `loss_mode` | (direct) | registered | supported | formula |
| `two_mode_squeezing` | (direct) | registered | supported | unitary |
| `fock_loss` | (direct) | registered | supported | formula |
| `photon_number_cutoff` | (direct) | registered | supported | formula |
| `source_multiphoton` | `multiphoton_source` | registered | supported | formula |
| `photon_emission` | (direct) | registered | supported | formula |
| `photon_collect` | (direct) | registered | supported | formula |
| `photon_propagation` | `propagation`,`fiber_propagation` | registered | supported | formula |

## ノード/リンク別プロフィール運用（追加）

`Backend.ned` で以下を追加:

- `qutip_node_profile`
- `qutip_link_profile`
- `qutip_profile_overrides`

`qutip_worker.py` では、`node`/`link` 操作を次のように切り替える.

- `unitary` / `measurement` / `noise` / `reset` / `phase` 系: `qutip_node_profile`
- `hom_interference` / `dispersion` / `multiphoton` / `squeezing` など: `qutip_link_profile`

例:

- node-profile 対象: `unitary`, `measurement`, `noise`, `reset`, `phase_shift`, `phase_modulation`, `decoherence`, `dephasing`, `kerr`, `cross_kerr`, `hamiltonian`, `lindblad`, `detection` など
- link-profile 対象: `hom_interference`, `dispersion`, `multiphoton`, `squeezing`, `loss`, `attenuation`, `mode_coupling`, `loss_mode`, `fock_loss`, `photon_number_cutoff`, `two_mode_squeezing` など

既定は `standard_light` で、`qutip_profile_overrides` 未設定時は既存 2準位挙動を保持する。
`qutip_profile_overrides` の不正JSONは受け付けずではなく安全に fallback し、`error_category="invalid_profile"` を付与する運用を想定している。

### プロファイル運用テンプレート

- A寄り（既定）

```ini
*.backend.qutip_node_profile = "standard_light"
*.backend.qutip_link_profile = "standard_light"
```

- B寄り（ノード=2準位、リンク=3〜4準位）

```ini
*.backend.qutip_node_profile = "standard_light"
*.backend.qutip_link_profile = "standard_qutrit"
```

- 高忠実度寄り（必要時のみ）

```ini
*.backend.qutip_node_profile = "custom"
*.backend.qutip_link_profile = "custom"
*.backend.qutip_profile_overrides = '{"node_dim":5, "link_mode_dim":6, "leakage_enabled":true, "truncation":12}'
```

`custom`では、`node_dim` と `link_mode_dim` が実行時に `dim`/`link_mode_dim` に反映される。
`custom` の受理値は次の通り:
- `node_dim`, `link_mode_dim`, `truncation`: 最小値2、未達時は `2` にフォールバックして `invalid_profile` を付与
- `leakage_enabled`: `true`/`false`/`1`/`0`/`"on"`/`"off"`/`"yes"`/`"no"` を受理

ノード/リンクプロファイル境界:
- `qutip_link_profile` は干渉/雑音/チャネル系の操作 (例: `hom_interference`, `dispersion`, `multiphoton`, `squeezing`, `loss_mode`, ...) に適用
- `qutip_node_profile` は局所操作 (例: `unitary`, `measurement`, `noise`, `reset`, `hamiltonian` など) に適用

## Known intentional unsupported kinds

- `hamiltonian`/`lindblad` require non-empty expression/collapse payload; missing payload is explicitly rejected.
- All unrecognized kinds return explicit `unsupported_kind` with deterministic message.
