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

  // All quantum mutations/noise/measurement are forwarded to backend; OMNeT side uses only classical outputs.
  OperationResult applyNoise(QubitHandle qubit);
  // channel_profile + params are interpreted only by backend implementations.
  OperationResult applyErrorChannel(const std::vector<QubitHandle>& qubit_ids, const std::string& channel_profile_name,
                                   const nlohmann::json& params);
  // Returns BSA-era classical outcome (e.g., outcome_pattern) in OperationResult.
  OperationResult applyHomInterference(const std::vector<QubitHandle>& qubit_ids, const nlohmann::json& params = {});
  OperationResult applyDetection(const std::vector<QubitHandle>& qubit_ids, const nlohmann::json& params = {});
  OperationResult applyNoiselessGate(const std::string& gate, const std::vector<QubitHandle>& qubits);
  OperationResult applyGate(const std::string& gate, const std::vector<QubitHandle>& qubits);
  OperationResult applyOperation(const PhysicalOperation& operation);
  OperationResult measure(QubitHandle qubit, MeasureBasis basis);
  OperationResult measureNoiseless(QubitHandle qubit, MeasureBasis basis, bool forced_plus);
  OperationResult generateEntanglement(QubitHandle source_qubit, QubitHandle target_qubit);
  // Reset bookkeeping for a stationary qubit slot that QuISP is recycling
  // (e.g. after a failed BSA attempt or after ES has consumed the pair).
  // Forwarded to the underlying backend; only the qutip backend needs to do
  // anything beyond the C++-side OMNeT bookkeeping the caller already did.
  void releaseQubit(QubitHandle qubit);

  uint32_t capabilities() const;
  const std::string& backendName() const { return backend_name_; }

  EigenvalueResult measureX(QubitHandle qubit);
  EigenvalueResult measureY(QubitHandle qubit);
  EigenvalueResult measureZ(QubitHandle qubit);

  // Drop every cached backend instance. Call from the OMNeT++ Backend module
  // when a new simulation run starts so the previous run's QutipBackend (and
  // its persistent worker) is torn down before the underlying graph_state
  // backend pointer is invalidated.
  static void clearBackendCache();

 private:
  BackendContext makeContext() const;
  std::string resolveBackendTypeFromContext() const;

  std::string backend_name_;
  // Either we own the backend (legacy unique_ptr ctor / tests), or we point to
  // a process-wide cached instance that survives many facades. Caching is the
  // critical fix that lets the QutipBackend keep its persistent Python worker
  // alive across operations: the facade itself is constructed per call site.
  std::unique_ptr<IPhysicalBackend> owned_backend_;
  IPhysicalBackend* backend_ = nullptr;
};

}  // namespace quisp::modules::backend
