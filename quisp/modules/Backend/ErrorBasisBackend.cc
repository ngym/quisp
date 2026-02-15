#include "ErrorBasisBackend.h"

#include <memory>
#include <stdexcept>
#include <vector>

#include "backends/interfaces/IQubit.h"

namespace quisp::modules::backend {

ErrorBasisBackend::ErrorBasisBackend(IQuantumBackend* backend) : backend_(backend) {}

OperationResult ErrorBasisBackend::applyNoise(const BackendContext& ctx, QubitHandle qubit) {
  if (backend_ == nullptr) throw std::runtime_error("ErrorBasisBackend has no backend");
  (void)ctx;
  auto* target = resolveQubit(qubit);
  if (target == nullptr) return {false};
  (void)target;
  return {true};
}

OperationResult ErrorBasisBackend::applyGate(const BackendContext& ctx, const std::string& gate, const std::vector<QubitHandle>& qubits) {
  if (backend_ == nullptr) throw std::runtime_error("ErrorBasisBackend has no backend");
  (void)ctx;
  if (qubits.empty()) {
    return {false};
  }

  if (gate == "X" || gate == "x") {
    auto* target = resolveQubit(qubits.at(0));
    if (target == nullptr) return {false};
    target->gateX();
    return {true};
  }
  if (gate == "Y" || gate == "y") {
    auto* target = resolveQubit(qubits.at(0));
    if (target == nullptr) return {false};
    target->gateY();
    return {true};
  }
  if (gate == "Z" || gate == "z") {
    auto* target = resolveQubit(qubits.at(0));
    if (target == nullptr) return {false};
    target->gateZ();
    return {true};
  }
  if (gate == "H" || gate == "h") {
    auto* target = resolveQubit(qubits.at(0));
    if (target == nullptr) return {false};
    target->gateH();
    return {true};
  }
  if (gate == "S" || gate == "s") {
    auto* target = resolveQubit(qubits.at(0));
    if (target == nullptr) return {false};
    target->gateS();
    return {true};
  }
  if (gate == "Sdg" || gate == "sdg" || gate == "S_dg") {
    auto* target = resolveQubit(qubits.at(0));
    if (target == nullptr) return {false};
    target->gateSdg();
    return {true};
  }
  if (gate == "CNOT" || gate == "cnot") {
    if (qubits.size() < 2) return {false};
    auto* src = resolveQubit(qubits[0]);
    auto* dst = resolveQubit(qubits[1]);
    if (src == nullptr || dst == nullptr) return {false};
    src->gateCNOT(dst);
    return {true};
  }
  return {false};
}

OperationResult ErrorBasisBackend::applyNoiselessGate(const BackendContext& ctx, const std::string& gate, const std::vector<QubitHandle>& qubits) {
  if (backend_ == nullptr) throw std::runtime_error("ErrorBasisBackend has no backend");
  (void)ctx;
  if (qubits.empty()) {
    return {false};
  }

  if (gate == "X" || gate == "x") {
    auto* target = resolveQubit(qubits.at(0));
    if (target == nullptr) return {false};
    target->noiselessX();
    return {true};
  }
  if (gate == "Z" || gate == "z") {
    auto* target = resolveQubit(qubits.at(0));
    if (target == nullptr) return {false};
    target->noiselessZ();
    return {true};
  }
  if (gate == "H" || gate == "h") {
    auto* target = resolveQubit(qubits.at(0));
    if (target == nullptr) return {false};
    target->noiselessH();
    return {true};
  }
  if (gate == "CNOT" || gate == "cnot") {
    if (qubits.size() < 2) return {false};
    auto* src = resolveQubit(qubits[0]);
    auto* dst = resolveQubit(qubits[1]);
    if (src == nullptr || dst == nullptr) return {false};
    src->noiselessCNOT(dst);
    return {true};
  }
  return {false};
}

OperationResult ErrorBasisBackend::measure(const BackendContext& ctx, QubitHandle qubit, MeasureBasis basis) {
  return measureAt(ctx, qubit, basis);
}

OperationResult ErrorBasisBackend::measureNoiseless(const BackendContext& ctx, QubitHandle qubit, MeasureBasis basis, bool forced_plus) {
  return measureNoiselessAt(ctx, qubit, basis, forced_plus);
}

OperationResult ErrorBasisBackend::generateEntanglement(const BackendContext& ctx, QubitHandle source_qubit, QubitHandle target_qubit) {
  if (backend_ == nullptr) throw std::runtime_error("ErrorBasisBackend has no backend");
  (void)ctx;
  auto* source = resolveQubit(source_qubit);
  auto* target = resolveQubit(target_qubit);
  if (source == nullptr || target == nullptr) return {false};
  source->noiselessH();
  source->noiselessCNOT(target);
  return {true};
}

backends::IQubit* ErrorBasisBackend::resolveQubit(QubitHandle qubit) {
  auto id = std::make_unique<qubit_id::QubitId>(qubit.node_id, qubit.qnic_index, qubit.qnic_type, qubit.qubit_index);
  return backend_->getQubit(id.get());
}

OperationResult ErrorBasisBackend::measureAt(const BackendContext& ctx, QubitHandle qubit, MeasureBasis basis) {
  (void)ctx;
  auto* target = resolveQubit(qubit);
  if (target == nullptr) return {false};

  quisp::backends::EigenvalueResult result = quisp::backends::EigenvalueResult::PLUS_ONE;
  switch (basis) {
    case MeasureBasis::X:
      result = target->measureX();
      break;
    case MeasureBasis::Y:
      result = target->measureY();
      break;
    case MeasureBasis::Z:
      result = target->measureZ();
      break;
    case MeasureBasis::Bell:
      return {false};
  }

  return {true, 1.0, false, false, false, result == quisp::backends::EigenvalueResult::PLUS_ONE};
}

OperationResult ErrorBasisBackend::measureNoiselessAt(const BackendContext& ctx, QubitHandle qubit, MeasureBasis basis, bool forced_plus) {
  (void)ctx;
  auto* target = resolveQubit(qubit);
  if (target == nullptr) return {false};

  quisp::backends::EigenvalueResult result = quisp::backends::EigenvalueResult::PLUS_ONE;
  auto forced = forced_plus ? quisp::backends::EigenvalueResult::PLUS_ONE : quisp::backends::EigenvalueResult::MINUS_ONE;

  switch (basis) {
    case MeasureBasis::X:
      if (forced_plus) {
        result = target->noiselessMeasureX(forced);
      } else {
        result = target->noiselessMeasureX();
      }
      break;
    case MeasureBasis::Z:
      if (forced_plus) {
        result = target->noiselessMeasureZ(forced);
      } else {
        result = target->noiselessMeasureZ();
      }
      break;
    case MeasureBasis::Y:
    case MeasureBasis::Bell:
      return {false};
  }

  return {true, 1.0, false, false, false, result == quisp::backends::EigenvalueResult::PLUS_ONE};
}

}  // namespace quisp::modules::backend
