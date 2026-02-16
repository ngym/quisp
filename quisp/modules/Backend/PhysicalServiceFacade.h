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
class QutipBackend;

class PhysicalServiceFacade {
 public:
  explicit PhysicalServiceFacade(IQuantumBackend* backend);
  explicit PhysicalServiceFacade(IQuantumBackend* backend, const std::string& backend_type);
  explicit PhysicalServiceFacade(std::unique_ptr<IPhysicalBackend> backend, const std::string& backend_type = "");

  OperationResult applyNoise(QubitHandle qubit);
  OperationResult applyNoiselessGate(const std::string& gate, const std::vector<QubitHandle>& qubits);
  OperationResult applyGate(const std::string& gate, const std::vector<QubitHandle>& qubits);
  OperationResult applyOperation(const PhysicalOperation& operation);
  OperationResult measure(QubitHandle qubit, MeasureBasis basis);
  OperationResult measureNoiseless(QubitHandle qubit, MeasureBasis basis, bool forced_plus);
  OperationResult generateEntanglement(QubitHandle source_qubit, QubitHandle target_qubit);

  uint32_t capabilities() const;
  const std::string& backendName() const { return backend_name_; }

  EigenvalueResult measureX(QubitHandle qubit);
  EigenvalueResult measureY(QubitHandle qubit);
  EigenvalueResult measureZ(QubitHandle qubit);

 private:
  BackendContext makeContext() const;
  std::string resolveBackendTypeFromContext() const;

  std::string backend_name_;
  std::unique_ptr<IPhysicalBackend> backend_;
};

}  // namespace quisp::modules::backend
