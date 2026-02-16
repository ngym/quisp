#pragma once

#include <string>
#include <vector>

#include "IPhysicalBackend.h"
#include "backends/interfaces/IQuantumBackend.h"

namespace quisp::modules::backend {

using quisp::backends::abstract::IQuantumBackend;

class QutipBackend : public IPhysicalBackend {
 public:
  QutipBackend(IQuantumBackend* backend, std::string backend_type = "qutip_density_matrix");

  uint32_t capabilities() const override;

  OperationResult applyNoise(const BackendContext& ctx, QubitHandle qubit) override;
  OperationResult applyGate(const BackendContext& ctx, const std::string& gate, const std::vector<QubitHandle>& qubits) override;
  OperationResult applyNoiselessGate(const BackendContext& ctx, const std::string& gate, const std::vector<QubitHandle>& qubits) override;
  OperationResult measure(const BackendContext& ctx, QubitHandle qubit, MeasureBasis basis) override;
  OperationResult measureNoiseless(const BackendContext& ctx, QubitHandle qubit, MeasureBasis basis, bool forced_plus) override;
  OperationResult generateEntanglement(const BackendContext& ctx, QubitHandle source_qubit, QubitHandle target_qubit) override;
  OperationResult applyOperation(const BackendContext& ctx, const PhysicalOperation& operation) override;

 private:
  OperationResult unsupported(const std::string& reason) const;
  nlohmann::json collectBackendParameters() const;
  bool checkQutipRuntimeAvailable() const;
  OperationResult executeQutipWorker(const BackendContext& ctx, const PhysicalOperation& operation) const;
  bool isAdvancedOperation(const std::string& kind) const;
  OperationResult runUnitary(const BackendContext& ctx, const std::string& gate, const std::vector<QubitHandle>& qubits, const std::string& context) const;
  OperationResult runMeasurement(const BackendContext& ctx, QubitHandle qubit, MeasureBasis basis, bool is_noiseless) const;
  OperationResult runNoise(const BackendContext& ctx, QubitHandle qubit, const std::string& noise_kind,
                          const nlohmann::json& noise_payload = nlohmann::json::object(),
                          const std::vector<double>& params = {}) const;
  OperationResult runEntanglement(const BackendContext& ctx, QubitHandle source_qubit, QubitHandle target_qubit) const;

  IQuantumBackend* backend_ = nullptr;
  std::string backend_type_;

  mutable bool qutip_runtime_checked_ = false;
  mutable bool qutip_runtime_available_ = false;
  mutable std::string qutip_runtime_check_error_;
};

}  // namespace quisp::modules::backend
