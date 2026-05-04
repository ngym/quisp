/** \file QuantumChannel.cc
 *
 *  \brief QuantumChannel
 */
#include <omnetpp.h>

#include <cstdint>
#include <memory>
#include <stdexcept>
#include <string>

#include "FlyingQubit_m.h"
#include "backends/interfaces/IQubit.h"
#include "modules/Backend/Backend.h"
#include "modules/Backend/PhysicalServiceFacade.h"
#include "modules/QNIC/StationaryQubit/QubitId.h"
#include "omnetpp/cexception.h"

using namespace omnetpp;
using namespace quisp::messages;
using namespace quisp::backends::abstract;
using namespace quisp::modules::backend;
using namespace quisp::modules::qubit_id;
using quisp::backends::IQuantumBackend;

namespace quisp::channels {

namespace {

QubitHandle makeHandle(const IQubit* qubit) {
  if (qubit == nullptr) {
    throw cRuntimeError("QuantumChannel::makeHandle: qubit is null");
  }
  const auto* id = qubit->getId();
  if (id == nullptr) {
    throw cRuntimeError("QuantumChannel::makeHandle: qubit has no id");
  }
  const auto* qid = dynamic_cast<const QubitId*>(id);
  if (qid == nullptr) {
    throw cRuntimeError("QuantumChannel::makeHandle: unsupported qubit id type");
  }
  return {qid->node_addr, qid->qnic_index, qid->qnic_type, qid->qubit_addr};
}

omnetpp::cModule* findBackendModule() {
  auto* sim = omnetpp::cSimulation::getActiveSimulation();
  if (sim == nullptr) return nullptr;
  for (auto* module = sim->getContextModule(); module != nullptr; module = module->getParentModule()) {
    if (auto* backend_module = module->findModuleByPath("backend")) {
      return backend_module;
    }
  }
  if (sim->getSystemModule() != nullptr && sim->getSystemModule()->hasSubmodule("backend")) {
    return sim->getSystemModule()->getSubmodule("backend");
  }
  return nullptr;
}

IQuantumBackend* resolveQuantumBackend() {
  auto* backend_module = findBackendModule();
  if (backend_module == nullptr) return nullptr;
  auto* backend_container = dynamic_cast<BackendContainer*>(backend_module);
  if (backend_container == nullptr) return nullptr;
  return backend_container->getQuantumBackend();
}

double clampDouble(double value, double min_value, double max_value) {
  if (value < min_value) return min_value;
  if (value > max_value) return max_value;
  return value;
}

 nlohmann::json buildChannelErrorParams(const cDatarateChannel& channel) {
  nlohmann::json params = {
      {"channel_loss_rate", channel.par("channel_loss_rate").doubleValue()},
      {"channel_x_error_rate", channel.par("channel_x_error_rate").doubleValue()},
      {"channel_y_error_rate", channel.par("channel_y_error_rate").doubleValue()},
      {"channel_z_error_rate", channel.par("channel_z_error_rate").doubleValue()},
      {"attenuation_db_per_km", channel.par("channel_attenuation_rate_db_per_km").doubleValue()},
      {"length_km", channel.par("channel_length_km").doubleValue()},
      {"channel_length_km", channel.par("channel_length_km").doubleValue()},
      {"node_io_overhead_db", channel.par("channel_node_io_overhead_db").doubleValue()},
      {"node_count", channel.par("channel_node_count").intValue()},
      {"distance_km", channel.par("distance").doubleValue()},
      {"distance", channel.par("distance").doubleValue()},
  };
  if (channel.hasPar("channel_profile")) {
    params["channel_profile"] = channel.par("channel_profile").stringValue();
  }
  return params;
}

}  // namespace

class QuantumChannel : public cDatarateChannel {
 public:
  QuantumChannel();

 protected:
  virtual void initialize() override;
  virtual cChannel::Result processMessage(cMessage *msg, const SendOptions &options, simtime_t t) override;

 private:
  void validateParameters();
};

Define_Channel(QuantumChannel);

QuantumChannel::QuantumChannel() {}

void QuantumChannel::initialize() {
  cDatarateChannel::initialize();
  validateParameters();
}

cChannel::Result QuantumChannel::processMessage(cMessage *msg, const SendOptions &options, simtime_t t) {
  auto* photon = dynamic_cast<FlyingQubit *>(msg);
  if (photon == nullptr) {
    throw new cRuntimeError("something other than photonic qubit is sent through quantum channel");
  }

  IQuantumBackend* backend = resolveQuantumBackend();
  if (backend == nullptr) {
    throw cRuntimeError("QuantumChannel: quantum backend not found");
  }
  PhysicalServiceFacade service(backend);

  const auto* qubit_ref = photon->getQubitRefForUpdate();
  if (qubit_ref != nullptr) {
    const auto handle = makeHandle(qubit_ref);
    const auto profile = hasPar("channel_profile") ? std::string(par("channel_profile").stringValue()) : std::string("loss_channel");
    auto params = buildChannelErrorParams(*this);
    params["legacy_channel_loss_rate"] = params["channel_loss_rate"];
    params["legacy_channel_x_error_rate"] = params["channel_x_error_rate"];
    params["legacy_channel_z_error_rate"] = params["channel_z_error_rate"];
    params["legacy_channel_y_error_rate"] = params["channel_y_error_rate"];

    // Apply the loss/depolarizing channel selected via channel_profile first
    // (loss may discard the photon, in which case the per-Pauli passes below
    // become no-ops because the metadata is already marked photon_lost).
    service.applyErrorChannel({handle}, profile.empty() ? "loss_channel" : profile, params);

    // A real fiber link experiences loss AND independent Pauli noise. Each
    // applyErrorChannel profile is intentionally single-purpose (loss only,
    // X only, …), so when the per-link rates declare extra Pauli noise on
    // top of the primary profile, dispatch follow-up calls here.
    const auto x_rate = params.value("channel_x_error_rate", 0.0);
    const auto z_rate = params.value("channel_z_error_rate", 0.0);
    const auto y_rate = params.value("channel_y_error_rate", 0.0);
    const auto needs_extra_x = x_rate > 0.0 && profile != "flip_channel";
    const auto needs_extra_z = z_rate > 0.0 && profile != "phaseflip_channel";
    const auto needs_extra_y = y_rate > 0.0;  // there is no dedicated y-only profile
    if (needs_extra_x) service.applyErrorChannel({handle}, "flip_channel", params);
    if (needs_extra_z) service.applyErrorChannel({handle}, "phaseflip_channel", params);
    if (needs_extra_y) {
      // Y = i X Z up to a global phase; chain X then Z to model a Y-noise rate
      // without adding a redundant single-purpose profile.
      auto y_as_x = params;
      y_as_x["channel_x_error_rate"] = y_rate;
      y_as_x["legacy_channel_x_error_rate"] = y_rate;
      auto y_as_z = params;
      y_as_z["channel_z_error_rate"] = y_rate;
      y_as_z["legacy_channel_z_error_rate"] = y_rate;
      service.applyErrorChannel({handle}, "flip_channel", y_as_x);
      service.applyErrorChannel({handle}, "phaseflip_channel", y_as_z);
    }
  }

  return {false, getDelay(), 0};
}

void QuantumChannel::validateParameters() {
  const auto length_km = par("distance").doubleValue();
  const auto channel_attenuation = par("channel_attenuation_rate_db_per_km").doubleValue();
  const auto node_io_overhead_db = par("channel_node_io_overhead_db").doubleValue();
  const auto node_count = par("channel_node_count").intValue();
  const auto channel_loss_rate = par("channel_loss_rate").doubleValue();
  const auto x_error_rate = par("channel_x_error_rate").doubleValue();
  const auto y_error_rate = par("channel_y_error_rate").doubleValue();
  const auto z_error_rate = par("channel_z_error_rate").doubleValue();

  if (length_km < 0) {
    throw cRuntimeError("quantum channel has invalid length (distance in km)");
  }
  if (channel_attenuation < 0) {
    throw cRuntimeError("quantum channel has invalid attenuation rate (must be >= 0)");
  }
  if (node_io_overhead_db < 0) {
    throw cRuntimeError("quantum channel has invalid node IO overhead (must be >= 0)");
  }
  if (node_count < 0) {
    throw cRuntimeError("quantum channel has invalid node count (must be >= 0)");
  }
  if (clampDouble(channel_loss_rate, 0.0, 1.0) != channel_loss_rate) {
    throw cRuntimeError("quantum channel has invalid loss rate (must be in [0,1])");
  }
  if (clampDouble(x_error_rate, 0.0, 1.0) != x_error_rate) {
    throw cRuntimeError("quantum channel has invalid x error rate (must be in [0,1])");
  }
  if (clampDouble(y_error_rate, 0.0, 1.0) != y_error_rate) {
    throw cRuntimeError("quantum channel has invalid y error rate (must be in [0,1])");
  }
  if (clampDouble(z_error_rate, 0.0, 1.0) != z_error_rate) {
    throw cRuntimeError("quantum channel has invalid z error rate (must be in [0,1])");
  }
}

}  // namespace quisp::channels
