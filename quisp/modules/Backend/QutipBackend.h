#pragma once

#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include <cstdint>
#include <sys/types.h>

#include "IPhysicalBackend.h"
#include "backends/interfaces/IQuantumBackend.h"

namespace quisp::modules::backend {

using quisp::backends::abstract::IQuantumBackend;

class QutipBackend : public IPhysicalBackend {
 public:
  QutipBackend(IQuantumBackend* backend, std::string backend_type = "qutip_density_matrix");
  ~QutipBackend() override;

  uint32_t capabilities() const override;

  OperationResult applyNoise(const BackendContext& ctx, QubitHandle qubit) override;
  OperationResult applyGate(const BackendContext& ctx, const std::string& gate, const std::vector<QubitHandle>& qubits) override;
  OperationResult applyNoiselessGate(const BackendContext& ctx, const std::string& gate, const std::vector<QubitHandle>& qubits) override;
  OperationResult measure(const BackendContext& ctx, QubitHandle qubit, MeasureBasis basis) override;
  OperationResult measureNoiseless(const BackendContext& ctx, QubitHandle qubit, MeasureBasis basis, bool forced_plus) override;
  OperationResult generateEntanglement(const BackendContext& ctx, QubitHandle source_qubit, QubitHandle target_qubit) override;
  OperationResult applyOperation(const BackendContext& ctx, const PhysicalOperation& operation) override;

 private:
  using EntanglementSetId = int64_t;
  using QubitKey = std::string;

  OperationResult unsupported(const std::string& reason) const;
  nlohmann::json collectBackendParameters() const;
  bool checkQutipRuntimeAvailable() const;
  OperationResult executeQutipWorker(const BackendContext& ctx, const PhysicalOperation& operation) const;
  std::string qubitKey(const QubitHandle& qubit) const;
  int64_t nextEntanglementSetId() const;
  int64_t attachEntanglementSetToTargets(const std::vector<QubitHandle>& targets, std::vector<EntanglementSetId>* merged_from = nullptr) const;
  void detachTargetFromEntanglementSet(const QubitHandle& qubit) const;
  bool isAdvancedOperation(const std::string& kind) const;
  OperationResult runUnitary(const BackendContext& ctx, const std::string& gate, const std::vector<QubitHandle>& qubits, const std::string& context) const;
  OperationResult runMeasurement(const BackendContext& ctx, QubitHandle qubit, MeasureBasis basis, bool is_noiseless) const;
  OperationResult runNoise(const BackendContext& ctx, QubitHandle qubit, const std::string& noise_kind,
                          const nlohmann::json& noise_payload = nlohmann::json::object(),
                          const std::vector<double>& params = {}) const;
  OperationResult applyErrorChannel(const BackendContext& ctx, const std::vector<QubitHandle>& qubits, const nlohmann::json& payload) const;
  OperationResult runEntanglement(const BackendContext& ctx, QubitHandle source_qubit, QubitHandle target_qubit) const;

  // Persistent-worker IPC. The Python worker holds the qutip density matrix
  // for every entanglement set across the whole simulation, so we spawn it
  // exactly once (lazily) and exchange newline-delimited JSON over stdin/stdout.
  bool ensureWorkerStarted(const nlohmann::json& backend_config) const;
  bool sendWorkerRequest(const std::string& payload) const;
  bool readWorkerResponse(int timeout_ms, std::string& line_out) const;
  void shutdownWorker() const;
  int workerTimeoutMs(const nlohmann::json& backend_config) const;

  IQuantumBackend* backend_ = nullptr;
  std::string backend_type_;

  mutable bool qutip_runtime_checked_ = false;
  mutable bool qutip_runtime_available_ = false;
  mutable std::string qutip_runtime_check_error_;

  mutable EntanglementSetId next_entanglement_set_id_ = 1;
  mutable std::unordered_map<QubitKey, EntanglementSetId> qubit_entanglement_set_map_;
  mutable std::unordered_map<EntanglementSetId, std::unordered_set<QubitKey>> entanglement_set_members_;

  mutable bool worker_started_ = false;
  mutable bool worker_first_request_done_ = false;
  mutable pid_t worker_pid_ = -1;
  mutable int worker_stdin_fd_ = -1;
  mutable int worker_stdout_fd_ = -1;
  mutable std::string worker_stdout_buffer_;
  mutable std::string worker_last_error_;
};

}  // namespace quisp::modules::backend
