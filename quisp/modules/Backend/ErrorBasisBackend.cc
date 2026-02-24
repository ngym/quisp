#include "ErrorBasisBackend.h"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <memory>
#include <stdexcept>
#include <sstream>
#include <vector>

#include "backends/interfaces/IQubit.h"

namespace quisp::modules::backend {

namespace {
constexpr const char* kCutoffReason = "expired";
constexpr const char* kPhotonLossReason = "photon_loss";

OperationResult failureResult(const std::string& reason) {
  OperationResult result;
  result.success = false;
  result.message = reason;
  return result;
}

std::string keyFromHandle(const QubitHandle& qubit) {
  std::ostringstream stream;
  stream << qubit.node_id << "/" << qubit.qnic_index << "/" << qubit.qnic_type << "/" << qubit.qubit_index;
  return stream.str();
}

double clampProbability(double value) {
  if (!std::isfinite(value)) return 0.0;
  if (value < 0.0) return 0.0;
  if (value > 1.0) return 1.0;
  return value;
}

std::uint64_t mixSeed(std::uint64_t value) {
  value ^= value >> 30;
  value *= 0xbf58476d1ce4e5b9;
  value ^= value >> 27;
  value *= 0x94d049bb133111eb;
  value ^= value >> 31;
  return value;
}

std::string normalizeErrorProfile(const std::string& profile) {
  std::string normalized = profile;
  normalized.erase(std::remove_if(normalized.begin(), normalized.end(), [](unsigned char ch) { return std::isspace(ch); }), normalized.end());
  std::transform(normalized.begin(), normalized.end(), normalized.begin(), [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });
  normalized.erase(std::remove(normalized.begin(), normalized.end(), '_'), normalized.end());
  normalized.erase(std::remove(normalized.begin(), normalized.end(), '-'), normalized.end());
  return normalized;
}

double extractProfileProbability(const nlohmann::json& payload, const std::initializer_list<const char*> keys, double default_value = 0.0) {
  for (const auto* key : keys) {
    const auto it = payload.find(key);
    if (it == payload.end()) {
      continue;
    }
    if (it->is_number_float()) {
      return clampProbability(it->get<double>());
    }
    if (it->is_number_integer()) {
      return clampProbability(static_cast<double>(it->get<int>()));
    }
    if (it->is_boolean()) {
      return it->get<bool>() ? 1.0 : 0.0;
    }
    if (it->is_string()) {
      try {
        return clampProbability(std::stod(it->get<std::string>()));
      } catch (...) {
      }
    }
  }
  return clampProbability(default_value);
}
}  // namespace

ErrorBasisBackend::ErrorBasisBackend(IQuantumBackend* backend) : backend_(backend) {}

uint32_t ErrorBasisBackend::capabilities() const {
  return static_cast<uint32_t>(BackendCapability::SupportsLegacyErrorModel);
}

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

OperationResult ErrorBasisBackend::applyOperation(const BackendContext& ctx, const PhysicalOperation& operation) {
  if (operation.kind == "unitary") {
    const auto gate_entry = operation.payload.find("gate");
    if (!operation.targets.empty() && gate_entry != operation.payload.end() && gate_entry->is_string()) {
      return applyGate(ctx, gate_entry->get<std::string>(), operation.targets);
    }
    return failureResult("missing gate payload or targets");
  }
  if (operation.kind == "measurement") {
    if (operation.targets.empty()) {
      return failureResult("measurement target missing");
    }
    MeasureBasis basis = MeasureBasis::Z;
    auto basis_label = operation.basis;
    if (basis_label.empty() && operation.payload.contains("basis") && operation.payload["basis"].is_string()) {
      basis_label = operation.payload["basis"].get<std::string>();
    }
    if (basis_label == "X") {
      basis = MeasureBasis::X;
    } else if (basis_label == "Y") {
      basis = MeasureBasis::Y;
    }
    return measure(ctx, operation.targets.at(0), basis);
  }
  if (operation.kind == "noise") {
    if (operation.targets.empty()) {
      return failureResult("noise target missing");
    }
    return applyNoise(ctx, operation.targets.at(0));
  }
  if (operation.kind == "error_channel") {
    if (operation.targets.empty()) {
      return failureResult("error_channel target missing");
    }
    return applyErrorChannel(ctx, operation);
  }
  if (operation.kind == "hom_interference") {
    return applyHomInterference(operation);
  }
  if (operation.kind == "detection") {
    return applyDetection(ctx, operation);
  }
  return failureResult("unsupported operation kind: " + operation.kind);
}

backends::IQubit* ErrorBasisBackend::resolveQubit(QubitHandle qubit) {
  if (qubit.node_id == -1 && qubit.qnic_index == -1 && qubit.qnic_type == -1) {
    if (backend_ == nullptr) {
      return nullptr;
    }
    try {
      return backend_->getShortLiveQubit();
    } catch (...) {
      return nullptr;
    }
  }
  auto id = std::make_unique<qubit_id::QubitId>(qubit.node_id, qubit.qnic_index, qubit.qnic_type, qubit.qubit_index);
  try {
    return backend_->getQubit(id.get());
  } catch (...) {
    return nullptr;
  }
}

std::string ErrorBasisBackend::keyFor(const QubitHandle& qubit) const {
  return keyFromHandle(qubit);
}

ErrorBasisBackend::GraphErrorState& ErrorBasisBackend::metadataFor(const QubitHandle& qubit) {
  return error_states_[keyFor(qubit)];
}

ErrorBasisBackend::GraphErrorState* ErrorBasisBackend::metadataPtr(const QubitHandle& qubit) const {
  const auto key = keyFor(qubit);
  const auto it = error_states_.find(key);
  if (it == error_states_.end()) return nullptr;
  return const_cast<GraphErrorState*>(&it->second);
}

OperationResult ErrorBasisBackend::applyErrorChannel(const BackendContext& ctx, const PhysicalOperation& operation) {
  if (operation.targets.empty()) {
    return failureResult("error_channel target missing");
  }
  (void)ctx;
  auto profile = normalizeErrorProfile(operation.payload.value("channel_profile", std::string("loss_channel")));
  if (profile.empty() || profile == "errorchannel") {
    profile = "loss_channel";
  }
  if (profile == "losschannel" || profile == "loss") {
    const auto loss_probability = computeLossProbability(operation.payload);
    bool has_management_discard = false;
    bool has_photon_loss = false;
    for (const auto& target : operation.targets) {
      auto& state = metadataFor(target);
      if (state.discarded) {
        has_management_discard = true;
        continue;
      }
      if (state.photon_lost) {
        has_photon_loss = true;
        continue;
      }
      if (eventOccurs(ctx.seed, keyFor(target) + "/loss", loss_probability)) {
        state.photon_lost = true;
        state.discard_reason = kPhotonLossReason;
        has_photon_loss = true;
      }
    }
    const auto has_event = has_management_discard || has_photon_loss;
    auto result = OperationResult{
        true,
        1.0,
        has_management_discard,
        false,
        false,
        false,
        has_event ? std::string("none") : std::string("pass"),
        0,
        {0, 0, 0, 0},
        nlohmann::json::object(),
        has_management_discard ? std::string(kCutoffReason) : (has_photon_loss ? std::string(kPhotonLossReason) : std::string()),
        has_event ? std::string("loss_channel") : std::string(),
    };
    result.message = has_event ? "loss_channel" : std::string();
    result.photon_lost = has_photon_loss;
    return result;
  }

  if (profile == "flipchannel" || profile == "xerror" || profile == "bitflip" || profile == "xflip" || profile == "biterror") {
    const auto x_probability = extractProfileProbability(operation.payload, {"channel_x_error_rate", "legacy_channel_x_error_rate", "x_error_rate", "flip_probability", "p"}, 0.0);
    for (const auto& target : operation.targets) {
      auto& state = metadataFor(target);
      if (!state.discarded && !state.photon_lost && eventOccurs(ctx.seed, keyFor(target) + "/flip", x_probability)) {
        state.x_error = !state.x_error;
      }
    }
    OperationResult result;
    result.success = true;
    result.message = "flip applied";
    result.detector_histogram = {0, 0, 0, 0};
    return result;
  }

  if (profile == "phaseflipchannel" || profile == "zerror" || profile == "phaseflip" || profile == "phaseerror") {
    const auto z_probability = extractProfileProbability(operation.payload, {"channel_z_error_rate", "legacy_channel_z_error_rate", "z_error_rate", "phase_probability"}, 0.0);
    for (const auto& target : operation.targets) {
      auto& state = metadataFor(target);
      if (!state.discarded && !state.photon_lost && eventOccurs(ctx.seed, keyFor(target) + "/phase", z_probability)) {
        state.z_error = !state.z_error;
      }
    }
    OperationResult result;
    result.success = true;
    result.message = "phaseflip applied";
    result.detector_histogram = {0, 0, 0, 0};
    return result;
  }

  if (profile == "depolarizingchannel" || profile == "depolarizing") {
    const auto depolarizing_probability = extractProfileProbability(
        operation.payload, {"channel_depolarizing_rate", "channel_error_rate", "depolarizing_probability", "depolarizing_error_rate", "p"}, 0.0);
    if (depolarizing_probability <= 0.0) {
      OperationResult result;
      result.success = true;
      result.message = "depolarizing skipped";
      return result;
    }
    for (const auto& target : operation.targets) {
      auto& state = metadataFor(target);
      if (state.discarded || state.photon_lost) {
        continue;
      }
      const auto key_seed = mixSeed(ctx.seed ^ std::hash<std::string>{}(keyFor(target) + "/depolarizing"));
      std::mt19937_64 rng{key_seed};
      std::uniform_real_distribution<double> distribution(0.0, 1.0);
      const auto sample = distribution(rng);
      if (sample >= depolarizing_probability) {
        continue;
      }
      const auto branch = distribution(rng) / depolarizing_probability;
      if (branch < (1.0 / 3.0)) {
        state.x_error = !state.x_error;
      } else if (branch < (2.0 / 3.0)) {
        state.z_error = !state.z_error;
      } else {
        state.x_error = !state.x_error;
        state.z_error = !state.z_error;
      }
    }
    OperationResult result;
    result.success = true;
    result.message = "depolarizing applied";
    result.detector_histogram = {0, 0, 0, 0};
    return result;
  }

  return failureResult("unsupported error_channel profile: " + profile);
}

OperationResult ErrorBasisBackend::applyHomInterference(const PhysicalOperation& operation) {
  if (operation.targets.size() < 2) {
    return failureResult("hom_interference requires at least two targets");
  }
  bool has_discarded = false;
  bool has_photon_lost = false;
  bool has_event = false;
  std::string discard_reason = kCutoffReason;
  for (const auto& target : operation.targets) {
    const auto* state = metadataPtr(target);
    if (state == nullptr) {
      continue;
    }
    if (state->discarded) {
      has_discarded = true;
      has_event = true;
      if (!state->discard_reason.empty()) {
        discard_reason = state->discard_reason;
      }
      break;
    }
    if (state->photon_lost) {
      has_photon_lost = true;
      has_event = true;
      discard_reason = state->discard_reason.empty() ? kPhotonLossReason : state->discard_reason;
      break;
    }
  }
  auto result = OperationResult{
      true,
      1.0,
      has_discarded,
      false,
      false,
      false,
      has_event ? "hom_interference skipped due to unavailable qubit" : "hom_interference success",
      0,
      {0, 0, 0, 0},
      {},
      has_discarded ? discard_reason : (has_photon_lost ? discard_reason : std::string()),
      has_event ? "hom_interference skipped due to unavailable qubit" : "hom_interference success",
  };
  result.message = has_event ? "hom_interference skipped due to unavailable qubit" : "hom_interference success";
  result.photon_lost = has_photon_lost;
  return result;
}

OperationResult ErrorBasisBackend::applyDetection(const BackendContext& ctx, const PhysicalOperation& operation) {
  if (operation.targets.empty()) {
    return failureResult("detection requires target(s)");
  }

  const auto efficiency = clampProbability(extractProfileProbability(operation.payload, {"efficiency", "eta", "detection_efficiency"}, 1.0));
  const auto dark_count = clampProbability(extractProfileProbability(operation.payload, {"dark_count", "darkcount", "detector", "detector_dark_count"}, 0.0));
  const auto visibility = clampProbability(extractProfileProbability(operation.payload, {"visibility", "visibility_factor"}, 1.0));
  const auto target_count = operation.targets.size();

  if (target_count == 1) {
    const auto& target = operation.targets.at(0);
    const auto* state = metadataPtr(target);
    const bool is_discarded = state != nullptr && state->discarded;
    const bool is_photon_lost = state != nullptr && state->photon_lost;
    const bool is_unavailable = is_discarded || is_photon_lost;
    std::string discard_reason = is_unavailable && state != nullptr && !state->discard_reason.empty() ? state->discard_reason : std::string();
    if (discard_reason.empty() && is_photon_lost) {
      discard_reason = kPhotonLossReason;
    }
    const auto clicked = eventOccurs(ctx.seed, keyFor(target) + "/detection1", is_unavailable ? 0.0 : (efficiency + dark_count - efficiency * dark_count));
    std::vector<int> histogram = {0, 0, 0, 0};
    std::string pattern = "none";
    if (clicked) {
      histogram[0] = 1;
      pattern = "d0";
    }
    auto result = OperationResult{
      true,
      1.0,
      is_discarded,
      false,
      false,
      clicked,
      pattern,
      clicked ? 1 : 0,
      histogram,
      {{"profile", "detection"},
      {"visibility", visibility}},
      is_discarded ? (discard_reason.empty() ? kCutoffReason : discard_reason) : (is_photon_lost ? discard_reason : std::string()),
      is_unavailable ? "detection skipped due to unavailable qubit" : std::string("detection success"),
    };
    result.message = is_unavailable ? "detection skipped due to unavailable qubit" : std::string("detection success");
    result.photon_lost = is_photon_lost;
    return result;
  }

  bool has_discarded = false;
  bool has_photon_lost = false;
  bool has_event = false;
  std::string discard_reason = kCutoffReason;
  for (const auto& target : operation.targets) {
    const auto* state = metadataPtr(target);
    if (state == nullptr) {
      continue;
    }
    if (state->discarded) {
      has_discarded = true;
      has_event = true;
      if (!state->discard_reason.empty()) {
        discard_reason = state->discard_reason;
      }
      break;
    }
    if (state->photon_lost) {
      has_photon_lost = true;
      has_event = true;
      discard_reason = state->discard_reason.empty() ? kPhotonLossReason : state->discard_reason;
      break;
    }
  }

  std::vector<int> histogram = {0, 0, 0, 0};
  int click_count = 0;
  std::string pattern = "none";
  bool measured_plus = false;
  if (!has_event) {
    if (eventOccurs(ctx.seed, "detection_dark", dark_count)) {
      pattern = "none";
    } else if (eventOccurs(ctx.seed, "detection_vis", visibility)) {
      click_count = 2;
      measured_plus = true;
      pattern = "d1,d3";
      histogram[1] = 1;
      histogram[3] = 1;
    } else if (eventOccurs(ctx.seed, "detection_alt", 1.0)) {
      click_count = 2;
      pattern = "d0,d2";
      histogram[0] = 1;
      histogram[2] = 1;
    }
  }

  auto result = OperationResult{
      true,
      1.0,
      has_discarded,
      false,
      false,
      measured_plus,
      pattern,
      has_event ? 0 : click_count,
      has_event ? std::vector<int>{0, 0, 0, 0} : histogram,
      {{"profile", "detection"}, {"target_count", static_cast<int>(target_count)}},
      has_discarded ? discard_reason : (has_photon_lost ? discard_reason : std::string()),
      has_event ? "detection skipped due to unavailable qubit" : std::string("detection success"),
  };
  result.message = has_event ? "detection skipped due to unavailable qubit" : std::string("detection success");
  result.photon_lost = has_photon_lost;
  return result;
}

double ErrorBasisBackend::extractProbability(const nlohmann::json& payload, std::initializer_list<const char*> keys, double default_value) const {
  for (const auto* key : keys) {
    auto it = payload.find(key);
    if (it == payload.end()) continue;
    if (it->is_number_float()) return clampProbability(it->get<double>());
    if (it->is_number_integer()) return clampProbability(static_cast<double>(it->get<int>()));
    if (it->is_boolean()) return it->get<bool>() ? 1.0 : 0.0;
    if (it->is_string()) {
      try {
        return clampProbability(std::stod(it->get<std::string>()));
      } catch (...) {
      }
    }
  }
  return clampProbability(default_value);
}

bool ErrorBasisBackend::eventOccurs(uint64_t seed, const std::string& key, double probability) {
  if (probability <= 0.0) return false;
  if (probability >= 1.0) return true;
  std::mt19937_64 rng{mixSeed(seed ^ std::hash<std::string>{}(key))};
  std::bernoulli_distribution dist(probability);
  return dist(rng);
}

double ErrorBasisBackend::computeLossProbability(const nlohmann::json& payload) const {
  const double legacy = clampProbability(extractProbability(payload, {"legacy_channel_loss_rate", "channel_loss_rate"}, 0.0));
  const double attenuation = clampProbability(extractProbability(payload, {"attenuation_db_per_km", "channel_attenuation_db_per_km"}, 0.0));
  const double node_overhead = clampProbability(extractProbability(payload, {"node_io_overhead_db", "channel_node_io_overhead_db"}, 0.0));
  const int node_count = std::max(
      0, static_cast<int>(std::llround(extractProbability(payload, {"node_count", "channel_node_count"}, 0.0))));

  double length_km = extractProbability(payload, {"channel_length_km", "length_km", "distance_km", "distance"}, 0.0);
  if (length_km < 0.0) length_km = 0.0;

  double transmission = 1.0;
  if (attenuation > 0.0 || length_km > 0.0 || node_count > 0 || node_overhead > 0.0) {
    const double eta_fiber = (attenuation <= 0.0 || length_km <= 0.0) ? 1.0 : std::pow(10.0, -(attenuation * length_km) / 10.0);
    const double eta_node = (node_overhead <= 0.0 || node_count <= 0) ? 1.0 : std::pow(10.0, -(node_overhead * node_count) / 10.0);
    transmission = clampProbability(eta_fiber * eta_node);
  } else if (legacy > 0.0) {
    transmission = clampProbability(1.0 - legacy);
  }
  return clampProbability(1.0 - transmission);
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
