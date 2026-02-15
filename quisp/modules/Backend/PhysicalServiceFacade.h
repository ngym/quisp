#pragma once

#include <memory>
#include <string>
#include <vector>
#include "IPhysicalBackend.h"
#include "backends/interfaces/IQubit.h"
#include "backends/interfaces/IQuantumBackend.h"

namespace quisp::modules::backend {

using quisp::backends::abstract::EigenvalueResult;
using quisp::backends::abstract::IQuantumBackend;

class ErrorBasisBackend;

class PhysicalServiceFacade {
 public:
  explicit PhysicalServiceFacade(IQuantumBackend* backend);
  explicit PhysicalServiceFacade(std::unique_ptr<IPhysicalBackend> backend);

  OperationResult applyNoise(QubitHandle qubit);
  OperationResult applyGate(const std::string& gate, const std::vector<QubitHandle>& qubits);
  OperationResult applyNoiselessGate(const std::string& gate, const std::vector<QubitHandle>& qubits);
  OperationResult measure(QubitHandle qubit, MeasureBasis basis);
  OperationResult measureNoiseless(QubitHandle qubit, MeasureBasis basis, bool forced_plus);
  OperationResult generateEntanglement(QubitHandle source_qubit, QubitHandle target_qubit);

  EigenvalueResult measureX(QubitHandle qubit);
  EigenvalueResult measureY(QubitHandle qubit);
  EigenvalueResult measureZ(QubitHandle qubit);

 private:
  BackendContext makeContext() const;
  std::unique_ptr<IPhysicalBackend> backend_;
};

}  // namespace quisp::modules::backend
