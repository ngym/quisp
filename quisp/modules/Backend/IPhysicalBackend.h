#pragma once

#include <cstdint>
#include <cstddef>
#include <string>
#include <vector>
#include <omnetpp/simtime_t.h>

namespace quisp::modules::backend {

using omnetpp::SimTime;

struct BackendContext {
  uint64_t seed = 0;
  SimTime now;
  std::string scenario_id;
};

struct QubitHandle {
  int node_id;
  int qnic_index;
  int qnic_type;
  int qubit_index;
};

enum class MeasureBasis { Z, X, Y, Bell };

struct OperationResult {
  bool success = false;
  double fidelity_estimate = 1.0;
  bool qubit_lost = false;
  bool relaxed_to_ground = false;
  bool excited_to_plus = false;
  bool measured_plus = false;
};

class IPhysicalBackend {
 public:
  virtual ~IPhysicalBackend() = default;
  virtual OperationResult applyNoise(const BackendContext& ctx, QubitHandle qubit) = 0;
  virtual OperationResult applyGate(const BackendContext& ctx, const std::string& gate, const std::vector<QubitHandle>& qubits) = 0;
  virtual OperationResult applyNoiselessGate(const BackendContext& ctx, const std::string& gate, const std::vector<QubitHandle>& qubits) = 0;
  virtual OperationResult measure(const BackendContext& ctx, QubitHandle qubit, MeasureBasis basis) = 0;
  virtual OperationResult measureNoiseless(const BackendContext& ctx, QubitHandle qubit, MeasureBasis basis, bool forced_plus) = 0;
  virtual OperationResult generateEntanglement(const BackendContext& ctx, QubitHandle qubit_a, QubitHandle qubit_b) = 0;
};

}  // namespace quisp::modules::backend
