#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

#include <omnetpp/simtime_t.h>
#include <nlohmann/json.hpp>

namespace quisp::modules::backend {

using omnetpp::SimTime;

enum class BackendCapability : uint32_t {
  SupportsLegacyErrorModel = 1u << 0,
  SupportsDenseOperator = 1u << 1,
  SupportsFockMode = 1u << 2,
  SupportsAdvancedOperation = 1u << 3,
};

struct BackendContext {
  uint64_t seed = 0;
  SimTime now;
  std::string scenario_id;
  std::string backend_name;
};

struct QubitHandle {
  int node_id;
  int qnic_index;
  int qnic_type;
  int qubit_index;
};

enum class MeasureBasis { Z, X, Y, Bell };

struct OperationResult {
  // Indicates whether backend execution itself succeeded (not a physical transmission success).
  bool success = false;
  // Channel-level (state-independent) process fidelity reported by the backend.
  // Computed once per (kind, parameters) and cached on the worker side, so the
  // value is cheap to obtain and reflects the operation's intrinsic quality
  // rather than the post-collapse state of any particular invocation.
  double fidelity_estimate = 1.0;

  // Lifecycle / availability flags.
  // discarded:
  //   OMNeT-side management event (timeout / timeout-like expiry / cutoff), "クォリット側の廃棄".
  // photon_lost:
  //   Physical-layer disappearance (伝搬損失や光子消失), "物理現象としての消失".
  // These must be treated as orthogonal conditions.
  bool discarded = false;
  bool relaxed_to_ground = false;
  bool excited_to_plus = false;
  bool measured_plus = false;

  // Classical readout from quantum detection operations.
  // OMNeT-side modules should branch only on these fields and NOT read per-photon mutable flags.
  std::string outcome_pattern;
  int detection_click_count = 0;
  std::vector<int> detector_histogram;
  nlohmann::json classical_payload;

  // Optional reason for management discard/physical loss, e.g. "expired", "cutoff", "photon_loss".
  std::string discard_reason;
  std::string message;

  // Alias of the physical disappearance state; keep for compatibility with older call sites.
  // Must remain independent of discarded.
  bool photon_lost = false;
};

struct PhysicalOperation {
  std::string kind;
  std::vector<QubitHandle> targets;
  std::vector<QubitHandle> controls;
  std::vector<int> ancillary_modes;
  double duration = 0;
  std::vector<double> params;
  std::string basis;
  nlohmann::json payload = nlohmann::json::object();
  int64_t entanglement_set_id = -1;
  std::string entanglement_set_event;
};

class IPhysicalBackend {
 public:
  virtual ~IPhysicalBackend() = default;

  // Reset bookkeeping for a stationary qubit that QuISP has decided to recycle
  // (e.g. after a failed BSA attempt or after ES has consumed the pair).
  // Without this signal, the persistent qutip worker keeps the qubit in its
  // last density matrix and the next H+CNOT on the same slot grows the
  // entanglement set instead of starting from |0>.
  virtual void releaseQubit(const BackendContext& ctx, QubitHandle qubit) {
    (void)ctx;
    (void)qubit;
  }

  virtual uint32_t capabilities() const = 0;

  virtual OperationResult applyNoise(const BackendContext& ctx, QubitHandle qubit) = 0;
  virtual OperationResult applyGate(const BackendContext& ctx, const std::string& gate, const std::vector<QubitHandle>& qubits) = 0;
  virtual OperationResult applyNoiselessGate(const BackendContext& ctx, const std::string& gate, const std::vector<QubitHandle>& qubits) = 0;
  virtual OperationResult measure(const BackendContext& ctx, QubitHandle qubit, MeasureBasis basis) = 0;
  virtual OperationResult measureNoiseless(const BackendContext& ctx, QubitHandle qubit, MeasureBasis basis, bool forced_plus) = 0;
  virtual OperationResult generateEntanglement(const BackendContext& ctx, QubitHandle qubit_a, QubitHandle qubit_b) = 0;

  virtual OperationResult applyOperation(const BackendContext& ctx, const PhysicalOperation& operation) {
    (void)ctx;
    (void)operation;
    OperationResult result;
    result.message = "operation not supported";
    return result;
  }
};

}  // namespace quisp::modules::backend
