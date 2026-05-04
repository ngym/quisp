# Bell State Analyzer

In QuISP, we assume that there is an implicit mechanism for repeaters and end nodes to signal the BSA module about the beginning and the end of the photon trains (e.g., strong light pulse before and after each train).
We achieve this in QuISP using the `STATIONARY_PULSE_XXX` flag where `<XXX>` can be `BEGIN`, `END`, or `BOUND`.

Note: In this vNext design, OMNeT message flags are not used for quantum error/loss state.
Arrival/loss and BSA click outcome are handled by the backend and returned as classical result data.

The BSA component in QuISP comprises two modules, the BellStateAnalyzer and the BSAController.
BellStateAnalyzer is the physical module where it only concerns itself with measuring the photons coming from the two ports.
BSAController on the other hand, handles the messaging and signalling of neighbour QNode(s), sending measurement results and telling them when the first photon should arrive.

The BSA can be inside a QNIC (referred to as QNIC_R or QNIC receiver) which lives inside a QNode, or inside a stand-alone node (BSANode).
Its functionality stays the same whether it lives inside a QNIC or a BSANode.
The only difference between internal (inside QNode) and external (inside BSANode) is the initialization phase inside the BSAController.
The module hierarchy traversal to find the incoming channel and which nodes this BSAController should talk to is different.

## How BellStateAnalyzer Module works

The BellStateAnalyzer manages its behaviour using a state machine. It has 4 states namely; `idle`, `accepting`, `accepting_left`, and `accepting_right`.
Currently, it caches all the photons coming in from both sides until the last photons from both sides arrive.
Then it compiles the results in batches and signals the BSAController which then sends it to QNodes.

In QuISP, we assume that the BSA can distinguish between $\ket{\Psi^+}$ and $\ket{\Psi^-}$ state while it cannot distinguish between $\ket{\Phi^+}$ and $\ket{\Phi^-}$.
This leads to a success probability of only 50% even if all the lossy parameters are set to be ideal (no loss, no error, no false positive click).

Pseudocode for BSA:

The parameters
```python
record_left = []
record_right = []
state = 'idle' | 'accepting_left' | 'accepting_right' | 'accepting'
indistinguish_time_period = 'positive number in (ns)'
# backend.detect(p_handle, q_handle) returns
#   {outcome_pattern: 'dAh,dAv'|'dBh,dBv'|'dAh,dBv'|'dAv,dBh'|'dAh'|'dAv'|'dBh'|'dBv'|'none'|..., detection_click_count: int, ...}
# pattern strings are compared strictly (no normalization).
# success patterns:
#   ψ+: dAh,dAv or dBh,dBv
#   ψ−: dAh,dBv or dAv,dBh
# failure patterns:
#   dAh, dAv, dBh, dBv, none
# dAh = detector A, horizontal polarization branch
# dAv = detector A, vertical polarization branch
# dBh = detector B, horizontal polarization branch
# dBv = detector B, vertical polarization branch
# Backend contract for optical BSA model:
#   hom_interference -> HOM-like 50:50 mixing on two input modes
#   detection -> PBS + 4-detector readout
#   ψ+: dAh,dAv or dBh,dBv
#   ψ−: dAh,dBv or dAv,dBh
```

State management part
```python
def processArrivalPhotons(photon):
    if (state == 'accepting right' and photon.from_left) \
        or (state == 'accepting left' and photon.from_right) \
        or (state == 'idle' and not photon.first):
        discardPhoton(photon)
        return

    if state == 'idle':
        state = 'accepting'

    if photon.from_left:
        record_left.append(photon)
    else:
        record_right.append(photon)

    if photon.last and state == 'accepting':
        if photon.from_left:
            state = 'accepting right'
        else:
            state = 'accepting left'
    elif photon.last:
        state = 'idle'
        processRecords()
```

Processing of the cache results
```python
def processRecords():
    results_list = []
    for left_photon, right_photon in zip(record_left, record_right):
        if abs(left_photon.arrive_time - right_photon.arrive_time) <= indistinguish_time_period:
            results_list.append(process_indistinguish_photons(left_photon, right_photon))
        else:
            results_list.append('fail')
```

If both the photons should arrive within the indistinguishability time window
```python
def process_indistinguish_photons(p, q):
    # Bell-state and detection are fully executed by the backend.
    # OMNeT logic only consumes the classical outcome pattern.
    detection = backend_detection(p, q)

    if detection.outcome_pattern in {'dAh,dAv', 'dBh,dBv'}:
        # ψ+ outcome
        # Pauli-X correction
        return 'success', 'Phi+'
    if detection.outcome_pattern in {'dAh,dBv', 'dAv,dBh'}:
        # ψ− outcome
        # Pauli-Y correction
        return 'success', 'Phi+'
    return 'fail'
```

### BSA correction convention
Memory-photon entanglement on each side is prepared as $\ket{\Phi^+} = (\ket{00}+\ket{11})/\sqrt{2}$ via H + CNOT. The swap-test identity then gives
$$\ket{\Phi^+}_{M_A P_A} \otimes \ket{\Phi^+}_{M_B P_B} = \tfrac{1}{2}\sum_\beta \ket{\beta}_{M_A M_B}\otimes\ket{\beta}_{P_A P_B},$$
so projecting the two photons onto Bell state $\ket{\beta}$ leaves the two memories in $\ket{\beta}$. Tomography compares against $\ket{\Phi^+}$, so the right-side memory is steered back to $\ket{\Phi^+}$:

| Detection pattern | Photon Bell state | Memories left in | Correction (right side) |
| --- | --- | --- | --- |
| `dAh,dAv` or `dBh,dBv` | $\ket{\psi^+}$ | $\ket{\psi^+}$ | $X$  ($X_B\ket{\psi^+} = \ket{\Phi^+}$) |
| `dAh,dBv` or `dAv,dBh` | $\ket{\psi^-}$ | $\ket{\psi^-}$ | $Y$  ($Y_B\ket{\psi^-} = -i\ket{\Phi^+}$) |
| `dAh`, `dAv`, `dBh`, `dBv`, `none` | $\phi$-like / single | indistinguishable in linear optics | failure |
