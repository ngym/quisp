#include "QutipBackend.h"

#include <algorithm>
#include <cctype>
#include <map>
#include <set>
#include <cstdlib>
#include <fstream>
#include <sstream>
#include <stdexcept>

#include <nlohmann/json.hpp>

#include "omnetpp.h"
#include <unistd.h>

namespace quisp::modules::backend {

namespace {

std::string lowerString(std::string value) {
  std::transform(value.begin(), value.end(), value.begin(), [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });
  return value;
}

std::string upperString(std::string value) {
  std::transform(value.begin(), value.end(), value.begin(), [](unsigned char ch) { return static_cast<char>(std::toupper(ch)); });
  return value;
}

nlohmann::json qubitHandleToJson(const QubitHandle& qubit) {
  return nlohmann::json({{"node_id", qubit.node_id}, {"qnic_index", qubit.qnic_index}, {"qnic_type", qubit.qnic_type}, {"qubit_index", qubit.qubit_index}});
}

std::string findWorkerScript(const nlohmann::json& backend_config) {
  const auto configured = backend_config.value("qutip_worker_script", std::string());
  if (!configured.empty()) {
    std::ifstream configured_script(configured);
    if (configured_script) {
      return configured;
    }
  }

  const char* script_from_env = std::getenv("QUTIP_WORKER_SCRIPT");
  if (script_from_env != nullptr && std::string(script_from_env).size() > 0) {
    std::ifstream env_script(script_from_env);
    if (env_script) {
      return script_from_env;
    }
  }

  const char* script_candidates[] = {"scripts/qutip_worker.py", "../scripts/qutip_worker.py", "../../scripts/qutip_worker.py"};
  for (const auto* candidate : script_candidates) {
    std::ifstream exists(candidate);
    if (exists) {
      return candidate;
    }
  }
  return "scripts/qutip_worker.py";
}

std::string shellEscape(const std::string& value) {
  if (value.find(' ') == std::string::npos) {
    return value;
  }
  return '"' + value + '"';
}

std::string pythonExecutable() {
  const char* env = std::getenv("QUTIP_PYTHON_EXECUTABLE");
  if (env != nullptr && std::string(env).size() > 0) {
    return env;
  }
  return "python3";
}

nlohmann::json operationToJson(const PhysicalOperation& operation) {
  nlohmann::json op;
  op["kind"] = operation.kind;
  op["targets"] = nlohmann::json::array();
  op["controls"] = nlohmann::json::array();
  op["ancillary_modes"] = operation.ancillary_modes;
  op["duration"] = operation.duration;
  op["params"] = operation.params;
  op["basis"] = operation.basis;
  op["payload"] = operation.payload;

  for (const auto& handle : operation.targets) {
    op["targets"].push_back(qubitHandleToJson(handle));
  }
  for (const auto& control : operation.controls) {
    op["controls"].push_back(qubitHandleToJson(control));
  }
  return op;
}

std::string contextToJson(const BackendContext& ctx, const PhysicalOperation& operation, const nlohmann::json& backend_config) {
  nlohmann::json request;
  request["backend_type"] = ctx.backend_name;
  request["scenario_id"] = ctx.scenario_id;
  request["seed"] = ctx.seed;
  request["time"] = ctx.now.dbl();
  request["operation"] = operationToJson(operation);
  request["operation"]["payload"]["backend_name"] = ctx.backend_name;
  request["backend_config"] = backend_config;
  return request.dump();
}

std::string normalizedGateName(const std::string& gate) {
  std::string value = gate;
  std::transform(value.begin(), value.end(), value.begin(), [](char ch) { return static_cast<char>(std::toupper(static_cast<unsigned char>(ch))); });
  return value;
}

MeasureBasis parseBasis(const PhysicalOperation& operation) {
  std::string basis = operation.basis;
  if (basis.empty() && operation.payload.contains("basis") && operation.payload["basis"].is_string()) {
    basis = operation.payload["basis"].get<std::string>();
  }
  basis = upperString(basis);
  if (basis == "X") {
    return MeasureBasis::X;
  }
  if (basis == "Y") {
    return MeasureBasis::Y;
  }
  if (basis == "BELL" || basis == "BELL_BASIS") {
    return MeasureBasis::Bell;
  }
  return MeasureBasis::Z;
}

std::string parseGateFromPayload(const PhysicalOperation& operation) {
  if (operation.payload.contains("gate") && operation.payload["gate"].is_string()) {
    return operation.payload["gate"].get<std::string>();
  }
  if (operation.payload.contains("kind") && operation.payload["kind"].is_string()) {
    return operation.payload["kind"].get<std::string>();
  }
  return "";
}

std::string parseNoiseFromPayload(const PhysicalOperation& operation) {
  if (operation.payload.contains("noise_kind") && operation.payload["noise_kind"].is_string()) {
    return lowerString(operation.payload["noise_kind"].get<std::string>());
  }
  if (operation.payload.contains("kind") && operation.payload["kind"].is_string()) {
    return lowerString(operation.payload["kind"].get<std::string>());
  }
  return "dephasing";
}

bool validateQubitHandle(const QubitHandle& qubit) {
  return qubit.node_id >= 0 && qubit.qnic_index >= 0 && qubit.qnic_type >= 0 && qubit.qubit_index >= 0;
}

bool hasValidTargets(const std::vector<QubitHandle>& targets) {
  if (targets.empty()) {
    return false;
  }
  for (const auto& target : targets) {
    if (!validateQubitHandle(target)) {
      return false;
    }
  }
  return true;
}

bool hasValidControls(const std::vector<QubitHandle>& controls) {
  for (const auto& control : controls) {
    if (!validateQubitHandle(control)) {
      return false;
    }
  }
  return true;
}

std::string normalizeBackendTypeLabel(const std::string& backend_type) {
  const auto lowered = lowerString(backend_type);
  if (lowered == "qutip" || lowered == "qutip_density_matrix") return "qutip_density_matrix";
  if (lowered == "qutip_sv" || lowered == "qutip_state_vector") return "qutip_state_vector";
  return lowered;
}

std::string normalizeKind(std::string kind) {
  std::transform(kind.begin(), kind.end(), kind.begin(), [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });
  return kind;
}

std::string normalizeAdvancedKind(const std::string& kind) {
  auto normalized = normalizeKind(kind);
  for (auto& ch : normalized) {
    if (ch == '-') {
      ch = '_';
    }
    if (ch == ' ') {
      ch = '_';
    }
  }
  while (normalized.find("__") != std::string::npos) {
    const auto pos = normalized.find("__");
    normalized.replace(pos, 2, "_");
  }
  const std::map<std::string, std::string> aliases = {
      {"no_op", "noop"},
      {"hominterference", "hom_interference"},
      {"measure", "measurement"},
      {"kerreffect", "kerr"},
      {"kerr_effect", "kerr"},
      {"kerr_effects", "kerr"},
      {"cross_kerring", "cross_kerr"},
      {"cross_kerr_effect", "cross_kerr"},
      {"crosskerr", "cross_kerr"},
      {"amplitude_damping", "amplitude_damping"},
      {"amplitudedamping", "amplitude_damping"},
      {"bit_flip", "bitflip"},
      {"phase_flip", "phaseflip"},
      {"depolarizing_channel", "depolarizing"},
      {"thermal_relaxation", "thermal_relaxation"},
      {"polarization_rotation", "polarization_rotation"},
      {"polarizationrotation", "polarization_rotation"},
      {"polarization_decoherence", "polarization_decoherence"},
      {"polarizationdecoherence", "polarization_decoherence"},
      {"mode_coupling", "mode_coupling"},
      {"loss_mode", "loss_mode"},
      {"two_mode_squeezing", "two_mode_squeezing"},
      {"two_modes_squeezing", "two_mode_squeezing"},
      {"fock_loss", "fock_loss"},
      {"photon_number_cutoff", "photon_number_cutoff"},
      {"hom", "hom_interference"},
      {"twophoton_interference", "hom_interference"},
      {"two_photon_interference", "hom_interference"},
      {"bs_interference", "hom_interference"},
      {"bsinterference", "hom_interference"},
      {"source_multiphoton", "source_multiphoton"},
      {"multiphoton_source", "source_multiphoton"},
      {"multi_photon_source", "source_multiphoton"},
      {"photon_source", "source_multiphoton"},
      {"crosskerr", "cross_kerr"},
      {"beamsplitter", "beam_splitter"},
      {"phaseshift", "phase_shift"},
      {"phaseshifter", "phase_shift"},
      {"phase_shifter", "phase_shift"},
      {"channel_dispersion", "dispersion"},
      {"fibre_dispersion", "dispersion"},
      {"fiber_dispersion", "dispersion"},
      {"phase_mod", "phase_modulation"},
      {"phase_modulator", "phase_modulation"},
      {"self_phase_mod", "self_phase_modulation"},
      {"self_phase_modulator", "self_phase_modulation"},
      {"cross_phase_mod", "cross_phase_modulation"},
      {"cross_phase_modulator", "cross_phase_modulation"},
      {"dephase", "dephasing"},
      {"decay", "decoherence"},
      {"timingjitter", "timing_jitter"},
      {"timing_jitter", "timing_jitter"},
      {"time_jitter", "timing_jitter"},
      {"timejitter", "timing_jitter"},
      {"jitter", "timing_jitter"},
      {"dark_count", "detection"},
      {"detector", "detection"},
      {"heraldedentanglement", "heralded_entanglement"},
  };
  const auto found = aliases.find(normalized);
  if (found != aliases.end()) {
    return found->second;
  }
  return normalized;
}

bool hasTargetCountMismatchForKind(const std::string& kind, const std::vector<QubitHandle>& targets) {
  if (kind == "measurement" || kind == "noise") {
    return targets.size() != 1;
  }
  return targets.empty();
}

std::string targetCountMismatchMessage(const std::string& kind, size_t target_count) {
  std::ostringstream stream;
  if (kind == "measurement") {
    stream << "qutip backend measurement operation expects exactly one target, target_count=" << target_count;
    return stream.str();
  }
  if (kind == "noise") {
    stream << "qutip backend noise operation expects exactly one target, target_count=" << target_count;
    return stream.str();
  }
  stream << "qutip backend operation is missing target(s), target_count=" << target_count;
  return stream.str();
}

const std::set<std::string> kSupportedAdvancedKinds{
    "kerr",
    "cross_kerr",
    "beam_splitter",
    "phase_shift",
    "phase_modulation",
    "self_phase_modulation",
    "cross_phase_modulation",
    "decoherence",
    "dephasing",
    "nonlinear",
    "detection",
    "delay",
    "hamiltonian",
    "lindblad",
    "heralded_entanglement",
    "timing_jitter",
    "dispersion",
    "multiphoton",
    "source_multiphoton",
    "hom_interference",
    "squeezing",
    "loss",
    "reset",
    "jitter",
    "attenuation",
    "amplitude_damping",
    "thermal_relaxation",
    "bitflip",
    "phaseflip",
    "depolarizing",
    "polarization_rotation",
    "polarization_decoherence",
    "mode_coupling",
    "loss_mode",
    "two_mode_squeezing",
    "fock_loss",
    "photon_number_cutoff",
};

nlohmann::json collectFromBackendModule(const omnetpp::cModule& module) {
  nlohmann::json params = {
      {"backend_name", "qutip_density_matrix"},
      {"python_executable", pythonExecutable()},
      {"qutip_backend_class", "qutip_density_matrix"},
      {"qutip_max_register_qubits", 8},
      {"qutip_max_hilbert_dim", 4},
      {"qutip_solver", "mesolve"},
      {"qutip_truncation", 5.0},
      {"qutip_worker_timeout_ms", 1000},
      {"qutip_worker_script", "scripts/qutip_worker.py"},
  };

  if (module.hasPar("qutip_python_executable")) {
    const auto value = module.par("qutip_python_executable").stdstringValue();
    if (!value.empty()) {
      params["python_executable"] = value;
    }
  }
  if (module.hasPar("qutip_backend_class")) {
    const auto value = module.par("qutip_backend_class").stdstringValue();
    if (!value.empty()) {
      params["qutip_backend_class"] = value;
    }
  }
  if (module.hasPar("qutip_max_register_qubits")) {
    params["qutip_max_register_qubits"] = module.par("qutip_max_register_qubits").intValue();
  }
  if (module.hasPar("qutip_max_hilbert_dim")) {
    params["qutip_max_hilbert_dim"] = module.par("qutip_max_hilbert_dim").intValue();
  }
  if (module.hasPar("qutip_solver")) {
    params["qutip_solver"] = module.par("qutip_solver").stdstringValue();
  }
  if (module.hasPar("qutip_truncation")) {
    params["qutip_truncation"] = module.par("qutip_truncation").doubleValue();
  }
  if (module.hasPar("qutip_worker_timeout_ms")) {
    params["qutip_worker_timeout_ms"] = module.par("qutip_worker_timeout_ms").intValue();
  }
  if (module.hasPar("qutip_worker_script")) {
    const auto value = module.par("qutip_worker_script").stdstringValue();
    if (!value.empty()) {
      params["qutip_worker_script"] = value;
    }
  }

  return params;
}

omnetpp::cModule* getBackendModuleFromContext() {
  auto* sim = omnetpp::cSimulation::getActiveSimulation();
  if (sim == nullptr) {
    return nullptr;
  }

  for (auto* module = sim->getContextModule(); module != nullptr; module = module->getParentModule()) {
    if (auto* backend = module->findModuleByPath("backend")) {
      return backend;
    }
    if (module->hasPar("qutip_backend_class") || module->hasPar("qutip_python_executable") || module->hasPar("qutip_max_register_qubits") ||
        module->hasPar("qutip_max_hilbert_dim") || module->hasPar("qutip_solver") || module->hasPar("qutip_truncation") || module->hasPar("qutip_worker_timeout_ms") ||
        module->hasPar("qutip_worker_script")) {
      return module;
    }
  }

  if (sim->getSystemModule() != nullptr && sim->getSystemModule()->hasSubmodule("backend")) {
    return sim->getSystemModule()->getSubmodule("backend");
  }
  return nullptr;
}

}  // namespace

QutipBackend::QutipBackend(IQuantumBackend* backend, std::string backend_type)
    : backend_(backend), backend_type_(std::move(backend_type)) {}

uint32_t QutipBackend::capabilities() const {
  return static_cast<uint32_t>(BackendCapability::SupportsLegacyErrorModel) | static_cast<uint32_t>(BackendCapability::SupportsDenseOperator) |
         static_cast<uint32_t>(BackendCapability::SupportsAdvancedOperation);
}

OperationResult QutipBackend::unsupported(const std::string& reason) const {
  return {false, 1.0, false, false, false, false, reason};
}

bool QutipBackend::checkQutipRuntimeAvailable() const {
  if (qutip_runtime_checked_) {
    return qutip_runtime_available_;
  }

  qutip_runtime_checked_ = true;
  const auto backend_config = collectBackendParameters();
  const auto python = shellEscape(backend_config.value("python_executable", pythonExecutable()));
  const auto command = python + " -c \"import qutip, qutip_qip, qutip.qip\"";
  const int status = std::system(command.c_str());
  if (status == 0) {
    qutip_runtime_available_ = true;
    return true;
  }

  std::ostringstream reason;
  reason << "qutip backend dependency check failed: " << command << " (status=" << status << ") [category=qutip_import]";
  qutip_runtime_check_error_ = reason.str();
  qutip_runtime_available_ = false;
  return false;
}

nlohmann::json QutipBackend::collectBackendParameters() const {
  nlohmann::json params = {
      {"backend_name", normalizeBackendTypeLabel(backend_type_)},
      {"python_executable", pythonExecutable()},
      {"qutip_backend_class", normalizeBackendTypeLabel(backend_type_)},
      {"qutip_max_register_qubits", 8},
      {"qutip_max_hilbert_dim", 4},
      {"qutip_solver", "mesolve"},
      {"qutip_truncation", 5.0},
      {"qutip_worker_timeout_ms", 1000},
  };

  auto* backend_module = getBackendModuleFromContext();
  if (backend_module == nullptr) {
    return params;
  }

  params = collectFromBackendModule(*backend_module);
  params["backend_name"] = normalizeBackendTypeLabel(backend_type_);
  if (params.value("qutip_backend_class", "").empty()) {
    params["qutip_backend_class"] = normalizeBackendTypeLabel(backend_type_);
  }

  return params;
}

bool QutipBackend::isAdvancedOperation(const std::string& kind) const {
  const auto normalized = normalizeAdvancedKind(kind);
  return kSupportedAdvancedKinds.count(normalized) > 0;
}

OperationResult QutipBackend::runUnitary(const BackendContext& ctx, const std::string& gate, const std::vector<QubitHandle>& qubits, const std::string& context) const {
  if (gate.empty()) {
    return unsupported("qutip backend unitary request missing gate");
  }
  if (qubits.empty()) {
    return unsupported("qutip backend unitary request missing target(s)");
  }
  for (const auto& qubit : qubits) {
    if (!validateQubitHandle(qubit)) {
      return unsupported("qutip backend unitary request received invalid qubit handle");
    }
  }

  PhysicalOperation operation;
  operation.kind = "unitary";
  operation.targets = qubits;
  operation.payload = {{"kind", "unitary"}, {"gate", normalizedGateName(gate)}, {"context", context}};
  return executeQutipWorker(ctx, operation);
}

OperationResult QutipBackend::runMeasurement(const BackendContext& ctx, QubitHandle qubit, MeasureBasis basis, bool is_noiseless) const {
  if (!validateQubitHandle(qubit)) {
    return unsupported("qutip backend measurement request received invalid qubit handle");
  }

  PhysicalOperation operation;
  operation.kind = "measurement";
  operation.targets = {qubit};
  auto basis_label = std::string("Z");
  if (basis == MeasureBasis::X) {
    basis_label = "X";
  } else if (basis == MeasureBasis::Y) {
    basis_label = "Y";
  } else if (basis == MeasureBasis::Bell) {
    basis_label = "Bell";
  }
  operation.basis = basis_label;
  operation.payload = {{"basis", basis_label}, {"noiseless", is_noiseless}};
  return executeQutipWorker(ctx, operation);
}

OperationResult QutipBackend::runNoise(const BackendContext& ctx, QubitHandle qubit, const std::string& noise_kind, const nlohmann::json& noise_payload,
                                      const std::vector<double>& params) const {
  if (!validateQubitHandle(qubit)) {
    return unsupported("qutip backend noise operation received invalid qubit handle");
  }
  const auto p_from_payload = noise_payload.contains("p") && noise_payload["p"].is_number() ? noise_payload["p"].get<double>() : 0.0;
  const auto p = params.empty() ? p_from_payload : params.front();
  PhysicalOperation operation;
  operation.kind = "noise";
  operation.targets = {qubit};
  operation.payload = {
      {"kind", "noise"},
      {"noise_kind", noise_kind},
      {"p", p},
  };
  return executeQutipWorker(ctx, operation);
}

OperationResult QutipBackend::runEntanglement(const BackendContext& ctx, QubitHandle source_qubit, QubitHandle target_qubit) const {
  if (!validateQubitHandle(source_qubit) || !validateQubitHandle(target_qubit)) {
    return unsupported("qutip backend entanglement request received invalid qubit handle");
  }
  const auto first = runUnitary(ctx, "H", {source_qubit}, "entanglement");
  if (!first.success) {
    return first;
  }
  return runUnitary(ctx, "CNOT", {source_qubit, target_qubit}, "entanglement");
}

OperationResult QutipBackend::executeQutipWorker(const BackendContext& ctx, const PhysicalOperation& operation) const {
  if (!checkQutipRuntimeAvailable()) {
    return unsupported(qutip_runtime_check_error_);
  }

  const auto backend_config = collectBackendParameters();
  const auto script = findWorkerScript(backend_config);
  const std::string python_executable = backend_config.value("python_executable", pythonExecutable());
  const auto python = shellEscape(python_executable);
  const auto script_path = shellEscape(script);
  const auto request = contextToJson(ctx, operation, backend_config);

  char request_file[] = "/tmp/quisp_qutip_request_XXXXXX";
  const auto request_fd = mkstemp(request_file);
  if (request_fd < 0) {
    return unsupported("qutip backend failed to create temporary request file");
  }

  char response_file[] = "/tmp/quisp_qutip_response_XXXXXX";
  const auto response_fd = mkstemp(response_file);
  if (response_fd < 0) {
    ::close(request_fd);
    ::unlink(request_file);
    return unsupported("qutip backend failed to create temporary response file");
  }

  {
    std::ofstream request_out(request_file);
    if (!request_out) {
      ::close(request_fd);
      ::close(response_fd);
      ::unlink(request_file);
      ::unlink(response_file);
      return unsupported("qutip backend failed to open temporary request file");
    }
    request_out << request;
    request_out.close();
  }

  const std::string cmd = python + " " + script_path + " --input " + shellEscape(request_file) + " --output " + shellEscape(response_file);
  const int status = std::system(cmd.c_str());
  ::close(request_fd);
  ::close(response_fd);

  if (status != 0) {
    ::unlink(request_file);
    ::unlink(response_file);
    return unsupported(std::string("qutip worker execution failed (status=") + std::to_string(status) + ")");
  }

  std::ifstream response_in(response_file);
  if (!response_in) {
    ::unlink(request_file);
    ::unlink(response_file);
    return unsupported("qutip worker did not produce output");
  }

  nlohmann::json response;
  try {
    response_in >> response;
  } catch (const std::exception& exc) {
    ::unlink(request_file);
    ::unlink(response_file);
    return unsupported(std::string("qutip worker response parse error: ") + exc.what());
  }

  ::unlink(request_file);
  ::unlink(response_file);

  if (!response.is_object()) {
    return unsupported("qutip worker returned invalid response format");
  }

  OperationResult result;
  result.success = response.value("success", false);
  result.fidelity_estimate = response.value("fidelity_estimate", 1.0);
  result.qubit_lost = response.value("qubit_lost", false);
  result.relaxed_to_ground = response.value("relaxed_to_ground", false);
  result.excited_to_plus = response.value("excited_to_plus", false);
  result.measured_plus = response.value("measured_plus", false);
  result.message = response.value("message", "");
  return result;
}

OperationResult QutipBackend::applyNoise(const BackendContext& ctx, QubitHandle qubit) {
  if (backend_ == nullptr) {
    throw std::runtime_error("QutipBackend has no backend");
  }
  return runNoise(ctx, qubit, "dephasing", {});
}

OperationResult QutipBackend::applyGate(const BackendContext& ctx, const std::string& gate, const std::vector<QubitHandle>& qubits) {
  if (backend_ == nullptr) {
    throw std::runtime_error("QutipBackend has no backend");
  }
  return runUnitary(ctx, gate, qubits, "");
}

OperationResult QutipBackend::applyNoiselessGate(const BackendContext& ctx, const std::string& gate, const std::vector<QubitHandle>& qubits) {
  if (backend_ == nullptr) {
    throw std::runtime_error("QutipBackend has no backend");
  }
  return runUnitary(ctx, gate, qubits, "noiseless");
}

OperationResult QutipBackend::measure(const BackendContext& ctx, QubitHandle qubit, MeasureBasis basis) {
  if (backend_ == nullptr) {
    throw std::runtime_error("QutipBackend has no backend");
  }
  return runMeasurement(ctx, qubit, basis, false);
}

OperationResult QutipBackend::measureNoiseless(const BackendContext& ctx, QubitHandle qubit, MeasureBasis basis, bool forced_plus) {
  if (backend_ == nullptr) {
    throw std::runtime_error("QutipBackend has no backend");
  }
  auto result = runMeasurement(ctx, qubit, basis, true);
  if (forced_plus && result.success) {
    result.measured_plus = true;
  }
  return result;
}

OperationResult QutipBackend::generateEntanglement(const BackendContext& ctx, QubitHandle source_qubit, QubitHandle target_qubit) {
  if (backend_ == nullptr) {
    throw std::runtime_error("QutipBackend has no backend");
  }
  return runEntanglement(ctx, source_qubit, target_qubit);
}

OperationResult QutipBackend::applyOperation(const BackendContext& ctx, const PhysicalOperation& operation) {
  if (backend_ == nullptr) {
    throw std::runtime_error("QutipBackend has no backend");
  }
  if (operation.kind.empty()) {
    return unsupported("qutip backend operation.kind is empty [category=invalid_payload]");
  }

  const auto normalized_kind = normalizeAdvancedKind(operation.kind);

  (void)normalizeBackendTypeLabel(backend_type_);
  if (normalized_kind == "noop") {
    return {true, 1.0};
  }

  if (normalized_kind == "unitary") {
    const auto gate = parseGateFromPayload(operation);
    if (gate.empty()) {
      return unsupported("qutip backend unitary operation missing payload kind/gate [category=invalid_payload]");
    }
    if (hasTargetCountMismatchForKind(normalized_kind, operation.targets)) {
      return unsupported("qutip backend unitary operation missing target(s) [category=invalid_payload]");
    }
    if (!hasValidTargets(operation.targets)) {
      return unsupported("qutip backend unitary operation received invalid qubit handle [category=invalid_payload]");
    }
    return runUnitary(ctx, gate, operation.targets, operation.payload.value("context", ""));
  }

  if (normalized_kind == "measurement") {
    if (hasTargetCountMismatchForKind(normalized_kind, operation.targets)) {
      return unsupported(targetCountMismatchMessage(normalized_kind, operation.targets.size()) + " [category=invalid_payload]");
    }
    if (!hasValidTargets(operation.targets)) {
      return unsupported("qutip backend measurement operation received invalid qubit handle [category=invalid_payload]");
    }
    auto basis = parseBasis(operation);
    return runMeasurement(ctx, operation.targets.front(), basis, operation.payload.value("noiseless", false));
  }

  if (normalized_kind == "noise") {
    if (hasTargetCountMismatchForKind(normalized_kind, operation.targets)) {
      return unsupported(targetCountMismatchMessage(normalized_kind, operation.targets.size()) + " [category=invalid_payload]");
    }
    if (!hasValidTargets(operation.targets)) {
      return unsupported("qutip backend noise operation received invalid qubit handle [category=invalid_payload]");
    }
    auto noise_kind = parseNoiseFromPayload(operation);
    return runNoise(ctx, operation.targets.front(), noise_kind, operation.payload, operation.params);
  }

  if (isAdvancedOperation(normalized_kind)) {
    if (hasTargetCountMismatchForKind(normalized_kind, operation.targets)) {
      return unsupported(targetCountMismatchMessage(normalized_kind, operation.targets.size()) + " [category=invalid_payload]");
    }
    if (!hasValidTargets(operation.targets)) {
      return unsupported("qutip backend advanced operation missing/invalid target(s) [category=invalid_payload]");
    }
    if (!hasValidControls(operation.controls)) {
      return unsupported("qutip backend advanced operation invalid control handle(s) [category=invalid_payload]");
    }
    return executeQutipWorker(ctx, operation);
  }

  return unsupported("qutip backend does not support operation.kind=" + operation.kind + " [category=unsupported_kind]");
}

}  // namespace quisp::modules::backend
