# Bell State Analyzer

In QuISP, we assume that there is an implicit mechanism for repeaters and end nodes to signal the BSA module about the beginning and the end of the photon trains (e.g., strong light pulse before and after each train).
We achieve this in QuISP using the `STATIONARY_PULSE_XXX` flag where `<XXX>` can be `BEGIN`, `END`, or `BOUND`.
The flag is one of the parameters of the photonic qubit we send to the BSA.

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
#   {outcome_pattern: 'd1,d3'|'d0,d2'|'none'|... , detection_click_count: int, ...}
# where 'd1,d3' and 'd0,d2' are Bell-success patterns
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

    if detection.outcome_pattern in {'d1,d3', 'd3,d1'}:
        # Pauli-X correction
        return 'success', 'Psi+' | 'Psi-'
    if detection.outcome_pattern in {'d0', 'd2', 'd2,d0'}:
        # Pauli-Z correction
        return 'success', 'Psi+' | 'Psi-'
    return 'fail'
```
