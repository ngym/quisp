#include "PhysicalServiceFacade.h"

#include <memory>

#include <stdexcept>

#include "ErrorBasisBackend.h"
#include "omnetpp.h"

namespace quisp::modules::backend {

PhysicalServiceFacade::PhysicalServiceFacade(IQuantumBackend* backend) {
  backend_ = std::make_unique<ErrorBasisBackend>(backend);
}

PhysicalServiceFacade::PhysicalServiceFacade(std::unique_ptr<IPhysicalBackend> backend) : backend_(std::move(backend)) {}

BackendContext PhysicalServiceFacade::makeContext() const {
  BackendContext context;
  context.seed = 0;
  context.now = omnetpp::simTime();
  context.scenario_id = "";
  return context;
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
