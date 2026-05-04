#pragma once

#include <cstddef>
#include <random>
#include <unordered_map>
#include <string>
#include <vector>

#include "IPhysicalBackend.h"
#include "backends/interfaces/IQuantumBackend.h"
#include "modules/QNIC/StationaryQubit/QubitId.h"

namespace quisp::modules::backend {

using quisp::backends::IQuantumBackend;

class ErrorBasisBackend : public IPhysicalBackend {
 public:
  explicit ErrorBasisBackend(IQuantumBackend* backend);

  uint32_t capabilities() const override;

  OperationResult applyNoise(const BackendContext& ctx, QubitHandle qubit) override;
  OperationResult applyGate(const BackendContext& ctx, const std::string& gate, const std::vector<QubitHandle>& qubits) override;
  OperationResult applyNoiselessGate(const BackendContext& ctx, const std::string& gate, const std::vector<QubitHandle>& qubits) override;
  OperationResult measure(const BackendContext& ctx, QubitHandle qubit, MeasureBasis basis) override;
  OperationResult measureNoiseless(const BackendContext& ctx, QubitHandle qubit, MeasureBasis basis, bool forced_plus) override;
  OperationResult generateEntanglement(const BackendContext& ctx, QubitHandle source_qubit, QubitHandle target_qubit) override;
  OperationResult applyOperation(const BackendContext& ctx, const PhysicalOperation& operation) override;

 private:
  backends::IQubit* resolveQubit(QubitHandle qubit);
  // Metadata-only state; OMNeT messages keep no error/loss flags.
  // discarded: 管理系discard. photon_lost: 物理消失.
  struct GraphErrorState {
    bool discarded = false;
    bool photon_lost = false;
    std::string discard_reason;
  };
  std::string keyFor(const QubitHandle& qubit) const;
  GraphErrorState& metadataFor(const QubitHandle& qubit);
  GraphErrorState* metadataPtr(const QubitHandle& qubit) const;
  double extractProbability(const nlohmann::json& payload, std::initializer_list<const char*> keys, double default_value = 0.0) const;
  static bool eventOccurs(uint64_t seed, const std::string& key, double probability);
  double computeLossProbability(const nlohmann::json& payload) const;
  OperationResult applyErrorChannel(const BackendContext& ctx, const PhysicalOperation& operation);
  OperationResult applyHomInterference(const PhysicalOperation& operation);
  OperationResult applyDetection(const BackendContext& ctx, const PhysicalOperation& operation);

  OperationResult measureAt(const BackendContext& ctx, QubitHandle qubit, MeasureBasis basis);
  OperationResult measureNoiselessAt(const BackendContext& ctx, QubitHandle qubit, MeasureBasis basis, bool forced_plus);
  IQuantumBackend* backend_;
  mutable std::unordered_map<std::string, GraphErrorState> error_states_;
};

}  // namespace quisp::modules::backend
