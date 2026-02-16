#include "PhysicalServiceFacade.h"

#include <atomic>
#include <algorithm>
#include <cctype>
#include <cstdint>
#include <memory>
#include <stdexcept>
#include <string>

#include "ErrorBasisBackend.h"
#include "QutipBackend.h"
#include "omnetpp.h"

namespace quisp::modules::backend {

namespace {
std::string toLower(std::string value) {
  std::transform(value.begin(), value.end(), value.begin(), [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });
  return value;
}

std::string normalizeBackendType(const std::string& value) {
  const auto normalized = toLower(value);
  if (normalized.empty() || normalized == "graphstatebackend" || normalized == "errorbasis" || normalized == "error_basis") {
    return "error_basis";
  }
  if (normalized == "qutip") {
    return "qutip";
  }
  if (normalized == "qutip_density_matrix") {
    return "qutip_density_matrix";
  }
  if (normalized == "qutip_sv" || normalized == "qutip_state_vector") {
    return "qutip_state_vector";
  }
  return normalized;
}

std::unique_ptr<IPhysicalBackend> createBackendByType(const std::string& backend_name, IQuantumBackend* backend) {
  if (backend_name == "qutip" || backend_name == "qutip_density_matrix" || backend_name == "qutip_state_vector") {
    return std::make_unique<QutipBackend>(backend, backend_name);
  }
  if (backend_name.empty() || backend_name == "error_basis") {
    return std::make_unique<ErrorBasisBackend>(backend);
  }
  throw std::runtime_error("PhysicalServiceFacade: unsupported physical backend type: " + backend_name);
}
}  // namespace

PhysicalServiceFacade::PhysicalServiceFacade(IQuantumBackend* backend) {
  backend_name_ = resolveBackendTypeFromContext();
  if (backend == nullptr) {
    backend_ = nullptr;
    return;
  }
  backend_name_ = normalizeBackendType(backend_name_);
  backend_ = createBackendByType(backend_name_, backend);
}

PhysicalServiceFacade::PhysicalServiceFacade(IQuantumBackend* backend, const std::string& backend_type) {
  backend_name_ = normalizeBackendType(!backend_type.empty() ? backend_type : resolveBackendTypeFromContext());
  if (backend == nullptr) {
    backend_ = nullptr;
    return;
  }
  backend_ = createBackendByType(backend_name_, backend);
}

PhysicalServiceFacade::PhysicalServiceFacade(std::unique_ptr<IPhysicalBackend> backend, const std::string& backend_type)
    : backend_name_(normalizeBackendType(backend_type)), backend_(std::move(backend)) {}

BackendContext PhysicalServiceFacade::makeContext() const {
  static std::atomic<std::uint64_t> operation_sequence{0};
  auto* sim = omnetpp::cSimulation::getActiveSimulation();
  auto* context_module = sim != nullptr ? sim->getContextModule() : nullptr;

  BackendContext context;
  context.seed = operation_sequence.fetch_add(1, std::memory_order_relaxed) + 1;
  context.now = omnetpp::simTime();
  if (context_module != nullptr) {
    context.scenario_id = context_module->getFullPath();
  } else {
    context.scenario_id = "";
  }
  context.backend_name = backend_name_;
  return context;
}

std::string PhysicalServiceFacade::resolveBackendTypeFromContext() const {
  auto* sim = omnetpp::cSimulation::getActiveSimulation();
  if (sim == nullptr) {
    return "error_basis";
  }

  for (auto* module = sim->getContextModule(); module != nullptr; module = module->getParentModule()) {
    if (auto* backend = module->findModuleByPath("backend")) {
      if (backend->hasPar("physical_backend_type")) {
        auto value = std::string(backend->par("physical_backend_type").stringValue());
        auto normalized = normalizeBackendType(value);
        if (!normalized.empty()) return normalized;
      }
      if (backend->hasPar("backend_type")) {
        return normalizeBackendType(std::string(backend->par("backend_type").stringValue()));
      }
    }

    if (module->hasPar("physical_backend_type")) {
      auto value = std::string(module->par("physical_backend_type").stringValue());
      auto normalized = normalizeBackendType(value);
      if (!normalized.empty()) return normalized;
    }
    if (module->hasPar("backend_type")) {
      auto value = std::string(module->par("backend_type").stringValue());
      auto normalized = normalizeBackendType(value);
      if (!normalized.empty()) return normalized;
    }
  }

  return "error_basis";
}

OperationResult PhysicalServiceFacade::applyNoise(QubitHandle qubit) {
  if (!backend_) throw std::runtime_error("PhysicalServiceFacade has no backend");
  return backend_->applyNoise(makeContext(), qubit);
}

OperationResult PhysicalServiceFacade::applyGate(const std::string& gate, const std::vector<QubitHandle>& qubits) {
  if (!backend_) throw std::runtime_error("PhysicalServiceFacade has no backend");
  return backend_->applyGate(makeContext(), gate, qubits);
}

OperationResult PhysicalServiceFacade::applyNoiselessGate(const std::string& gate, const std::vector<QubitHandle>& qubits) {
  if (!backend_) throw std::runtime_error("PhysicalServiceFacade has no backend");
  return backend_->applyNoiselessGate(makeContext(), gate, qubits);
}

OperationResult PhysicalServiceFacade::measure(QubitHandle qubit, MeasureBasis basis) {
  if (!backend_) throw std::runtime_error("PhysicalServiceFacade has no backend");
  return backend_->measure(makeContext(), qubit, basis);
}

OperationResult PhysicalServiceFacade::measureNoiseless(QubitHandle qubit, MeasureBasis basis, bool forced_plus) {
  if (!backend_) throw std::runtime_error("PhysicalServiceFacade has no backend");
  return backend_->measureNoiseless(makeContext(), qubit, basis, forced_plus);
}

OperationResult PhysicalServiceFacade::generateEntanglement(QubitHandle source_qubit, QubitHandle target_qubit) {
  if (!backend_) throw std::runtime_error("PhysicalServiceFacade has no backend");
  return backend_->generateEntanglement(makeContext(), source_qubit, target_qubit);
}

OperationResult PhysicalServiceFacade::applyOperation(const PhysicalOperation& operation) {
  if (!backend_) throw std::runtime_error("PhysicalServiceFacade has no backend");
  return backend_->applyOperation(makeContext(), operation);
}

uint32_t PhysicalServiceFacade::capabilities() const {
  if (!backend_) return 0;
  return backend_->capabilities();
}

EigenvalueResult PhysicalServiceFacade::measureX(QubitHandle qubit) {
  auto result = measure(qubit, MeasureBasis::X);
  if (!result.success) {
    throw omnetpp::cRuntimeError("PhysicalServiceFacade::measureX: measurement failed");
  }
  return result.measured_plus ? EigenvalueResult::PLUS_ONE : EigenvalueResult::MINUS_ONE;
}

EigenvalueResult PhysicalServiceFacade::measureY(QubitHandle qubit) {
  auto result = measure(qubit, MeasureBasis::Y);
  if (!result.success) {
    throw omnetpp::cRuntimeError("PhysicalServiceFacade::measureY: measurement failed");
  }
  return result.measured_plus ? EigenvalueResult::PLUS_ONE : EigenvalueResult::MINUS_ONE;
}

EigenvalueResult PhysicalServiceFacade::measureZ(QubitHandle qubit) {
  auto result = measure(qubit, MeasureBasis::Z);
  if (!result.success) {
    throw omnetpp::cRuntimeError("PhysicalServiceFacade::measureZ: measurement failed");
  }
  return result.measured_plus ? EigenvalueResult::PLUS_ONE : EigenvalueResult::MINUS_ONE;
}

}  // namespace quisp::modules::backend
