#pragma once

#include <cstddef>
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

  OperationResult applyNoise(const BackendContext& ctx, QubitHandle qubit) override;
  OperationResult applyGate(const BackendContext& ctx, const std::string& gate, const std::vector<QubitHandle>& qubits) override;
  OperationResult applyNoiselessGate(const BackendContext& ctx, const std::string& gate, const std::vector<QubitHandle>& qubits) override;
  OperationResult measure(const BackendContext& ctx, QubitHandle qubit, MeasureBasis basis) override;
  OperationResult measureNoiseless(const BackendContext& ctx, QubitHandle qubit, MeasureBasis basis, bool forced_plus) override;
  OperationResult generateEntanglement(const BackendContext& ctx, QubitHandle source_qubit, QubitHandle target_qubit) override;

 private:
  backends::IQubit* resolveQubit(QubitHandle qubit);
  OperationResult measureAt(const BackendContext& ctx, QubitHandle qubit, MeasureBasis basis);
  OperationResult measureNoiselessAt(const BackendContext& ctx, QubitHandle qubit, MeasureBasis basis, bool forced_plus);
  IQuantumBackend* backend_;
};

}  // namespace quisp::modules::backend
