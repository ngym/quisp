#include "Backend.h"
#include <memory>
#include <algorithm>
#include <cctype>
#include "backends/QubitConfiguration.h"

namespace quisp::modules::backend {

namespace {
std::string toLower(std::string value) {
  std::transform(value.begin(), value.end(), value.begin(), [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });
  return value;
}

std::string normalizeBackendType(std::string value) {
  const auto lowered = toLower(value);
  if (value.empty() || lowered == "graphstatebackend" || lowered == "error_basis" || lowered == "errorbasis") {
    return "GraphStateBackend";
  }
  if (lowered == "qutip" || lowered == "qutip_density_matrix") {
    return "qutip";
  }
  if (lowered == "qutip_sv" || lowered == "qutip_state_vector") {
    return "qutip_sv";
  }
  return lowered;
}
}  // namespace

BackendContainer::BackendContainer() {}

BackendContainer::~BackendContainer() {}

void BackendContainer::initialize() {
  auto backend_type = getSelectedBackendType();
  backend = createBackend(backend_type);
}

std::string BackendContainer::getSelectedBackendType() const {
  if (hasPar("physical_backend_type")) {
    return normalizeBackendType(par("physical_backend_type").stringValue());
  }

  if (hasPar("backend_type")) {
    return normalizeBackendType(std::string(par("backend_type").stringValue()));
  }

  return "GraphStateBackend";
}

std::unique_ptr<IQuantumBackend> BackendContainer::createBackend(const std::string& backend_type) {
  const auto normalized = normalizeBackendType(backend_type);
  if (normalized == "GraphStateBackend" || normalized == "error_basis" || normalized == "qutip" || normalized == "qutip_density_matrix" || normalized == "qutip_state_vector" ||
      normalized == "qutip_sv") {
    auto config = getDefaultQubitErrorModelConfiguration();
    return std::make_unique<GraphStateBackend>(std::make_unique<RNG>(this), std::move(config), static_cast<GraphStateBackend::ICallback*>(this));
  }
  throw omnetpp::cRuntimeError(
      "Unknown backend type: %s. Supported types are: GraphStateBackend, error_basis, qutip, qutip_density_matrix, qutip_state_vector, qutip_sv",
      backend_type.c_str());
}

std::unique_ptr<StationaryQubitConfiguration> BackendContainer::getDefaultQubitErrorModelConfiguration() {
  auto conf = std::make_unique<StationaryQubitConfiguration>();
  conf->measurement_x_err_rate = par("x_measurement_error_rate").doubleValue();
  conf->measurement_y_err_rate = par("y_measurement_error_rate").doubleValue();
  conf->measurement_z_err_rate = par("z_measurement_error_rate").doubleValue();

  conf->h_gate_err_rate = par("h_gate_error_rate").doubleValue();
  conf->h_gate_x_err_ratio = par("h_gate_x_error_ratio").doubleValue();
  conf->h_gate_y_err_ratio = par("h_gate_y_error_ratio").doubleValue();
  conf->h_gate_z_err_ratio = par("h_gate_z_error_ratio").doubleValue();

  conf->x_gate_err_rate = par("x_gate_error_rate").doubleValue();
  conf->x_gate_x_err_ratio = par("x_gate_x_error_ratio").doubleValue();
  conf->x_gate_y_err_ratio = par("x_gate_y_error_ratio").doubleValue();
  conf->x_gate_z_err_ratio = par("x_gate_z_error_ratio").doubleValue();

  conf->z_gate_err_rate = par("z_gate_error_rate").doubleValue();
  conf->z_gate_x_err_ratio = par("z_gate_x_error_ratio").doubleValue();
  conf->z_gate_y_err_ratio = par("z_gate_y_error_ratio").doubleValue();
  conf->z_gate_z_err_ratio = par("z_gate_z_error_ratio").doubleValue();

  conf->cnot_gate_err_rate = par("cnot_gate_error_rate").doubleValue();
  conf->cnot_gate_iz_err_ratio = par("cnot_gate_iz_error_ratio").doubleValue();
  conf->cnot_gate_zi_err_ratio = par("cnot_gate_zi_error_ratio").doubleValue();
  conf->cnot_gate_zz_err_ratio = par("cnot_gate_zz_error_ratio").doubleValue();
  conf->cnot_gate_ix_err_ratio = par("cnot_gate_ix_error_ratio").doubleValue();
  conf->cnot_gate_xi_err_ratio = par("cnot_gate_xi_error_ratio").doubleValue();
  conf->cnot_gate_xx_err_ratio = par("cnot_gate_xx_error_ratio").doubleValue();
  conf->cnot_gate_iy_err_ratio = par("cnot_gate_iy_error_ratio").doubleValue();
  conf->cnot_gate_yi_err_ratio = par("cnot_gate_yi_error_ratio").doubleValue();
  conf->cnot_gate_yy_err_ratio = par("cnot_gate_yy_error_ratio").doubleValue();

  conf->memory_x_err_rate = par("memory_x_error_rate").doubleValue();
  conf->memory_y_err_rate = par("memory_y_error_rate").doubleValue();
  conf->memory_z_err_rate = par("memory_z_error_rate").doubleValue();
  conf->memory_excitation_rate = par("memory_energy_excitation_rate").doubleValue();
  conf->memory_relaxation_rate = par("memory_energy_relaxation_rate").doubleValue();
  conf->memory_completely_mixed_rate = par("memory_completely_mixed_rate").doubleValue();

  return conf;
}

void BackendContainer::willUpdate(GraphStateBackend& backend) { backend.setSimTime(omnetpp::simTime()); }
void BackendContainer::finish() {}

IQuantumBackend* BackendContainer::getQuantumBackend() {
  if (backend == nullptr) {
    throw omnetpp::cRuntimeError("Backend is not initialized");
  }
  return backend.get();
}

}  // namespace quisp::modules::backend
