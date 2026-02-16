#pragma once

#include <cstdint>
#include <cstddef>
#include <string>
#include <vector>

#include <nlohmann/json.hpp>
#include <omnetpp/simtime_t.h>

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
  bool success = false;
  double fidelity_estimate = 1.0;
  bool qubit_lost = false;
  bool relaxed_to_ground = false;
  bool excited_to_plus = false;
  bool measured_plus = false;
  std::string message;
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
};

class IPhysicalBackend {
 public:
  virtual ~IPhysicalBackend() = default;

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
    return {false, 1.0, false, false, false, false, "operation not supported"};
  }
};

}  // namespace quisp::modules::backend
