/** \file StationaryQubit.cc
 *
 *  \brief StationaryQubit
 */
#include "StationaryQubit.h"

#include <algorithm>
#include <sstream>
#include <FlyingQubit_m.h>
#include <messages/classical_messages.h>
#include <omnetpp.h>
#include <set>
#include <stdexcept>
#include <vector>
#include <unsupported/Eigen/KroneckerProduct>
#include <unsupported/Eigen/MatrixFunctions>
#include "backends/interfaces/IQubit.h"
#include "modules/Backend/PhysicalServiceFacade.h"
#include "omnetpp/cexception.h"

using namespace Eigen;

using quisp::messages::FlyingQubit;
using quisp::modules::qubit_id::QubitId;
using quisp::types::EigenvalueResult;
using quisp::types::MeasurementOutcome;
using quisp::types::MeasureXResult;
using quisp::types::MeasureYResult;
using quisp::types::MeasureZResult;
using quisp::modules::backend::PhysicalServiceFacade;
using quisp::modules::backend::QubitHandle;

namespace {

QubitHandle makeHandle(const quisp::backends::IQubit* qubit);

QubitHandle makeHandle(const quisp::modules::StationaryQubit& qubit) {
  return makeHandle(qubit.getBackendQubitRef());
}

QubitHandle makeHandle(const quisp::backends::IQubit* qubit) {
  if (qubit == nullptr) throw cRuntimeError("StationaryQubit::makeHandle: null backend qubit");
  const auto* id = qubit->getId();
  if (id == nullptr) throw cRuntimeError("StationaryQubit::makeHandle: backend qubit has no id");
  const auto* qid = dynamic_cast<const quisp::modules::qubit_id::QubitId*>(id);
  if (qid == nullptr) throw cRuntimeError("StationaryQubit::makeHandle: unsupported backend qubit id type");
  return QubitHandle{qid->node_addr, qid->qnic_index, qid->qnic_type, qid->qubit_addr};
}

omnetpp::cModule* toTopLevelAddressNode(omnetpp::cModule* module) {
  omnetpp::cModule* candidate = nullptr;
  while (module != nullptr) {
    if (module->hasPar("address")) {
      candidate = module;
    }
    module = module->getParentModule();
  }
  return candidate;
}

omnetpp::cModule* firstPeerNodeAlongPath(omnetpp::cGate* gate, omnetpp::cModule* source_node) {
  std::set<omnetpp::cGate*> visited;
  while (gate != nullptr && visited.insert(gate).second) {
    gate = gate->getNextGate();
    if (gate == nullptr) {
      break;
    }
    auto* peer = toTopLevelAddressNode(gate->getOwnerModule());
    if (peer != nullptr && peer != source_node) {
      return peer;
    }
  }
  return nullptr;
}

std::string inferDestinationNodeId(quisp::modules::StationaryQubit* qubit) {
  auto* source_node = toTopLevelAddressNode(qubit);
  if (source_node == nullptr) {
    return "";
  }

  std::vector<omnetpp::cModule*> peers;
  std::set<int> seen_peer_ids;
  for (omnetpp::cModule::GateIterator gate_it(source_node); !gate_it.end(); ++gate_it) {
    auto* gate = *gate_it;
    if (gate == nullptr || gate->getType() != omnetpp::cGate::OUTPUT || !gate->isConnected()) {
      continue;
    }
    auto* peer = firstPeerNodeAlongPath(gate, source_node);
    if (peer == nullptr) {
      continue;
    }
    const auto peer_id = peer->par("address").intValue();
    if (!seen_peer_ids.insert(peer_id).second) {
      continue;
    }
    peers.push_back(peer);
  }

  if (peers.empty()) {
    return "";
  }

  std::sort(peers.begin(), peers.end(), [](const omnetpp::cModule* left, const omnetpp::cModule* right) {
    return left->par("address").intValue() < right->par("address").intValue();
  });

  if (peers.size() == 1) {
    return std::to_string(peers.front()->par("address").intValue());
  }

  const auto qnic_index = qubit->par("qnic_index").intValue();
  const auto index = qnic_index >= 0 ? static_cast<size_t>(qnic_index) % peers.size() : 0;
  return std::to_string(peers[index]->par("address").intValue());
}

std::string inferDestinationNodeIdFromCurrentPath(quisp::modules::StationaryQubit* qubit) {
  auto* source_node = toTopLevelAddressNode(qubit);
  auto* gate = qubit->gate("tolens_quantum_port");
  auto* peer = firstPeerNodeAlongPath(gate, source_node);
  if (peer != nullptr) {
    return std::to_string(peer->par("address").intValue());
  }
  return "";
}

}  // namespace

namespace quisp::modules {

Define_Module(StationaryQubit);

StationaryQubit::StationaryQubit() : provider(utils::ComponentProvider{this}) {}

/**
 * \brief Initialize StationaryQubit
 *
 * Omnet called method to initialize objects.
 *
 */
void StationaryQubit::initialize() {
  // read and set parameters
  emission_success_probability = par("emission_success_probability");

  // Get parameters from omnet
  stationary_qubit_address = par("stationary_qubit_address");
  node_address = par("node_address");
  qnic_address = par("qnic_address");
  qnic_type = par("qnic_type");
  qnic_index = par("qnic_index");
  emission_jittering_standard_deviation = par("emission_jittering_standard_deviation").doubleValue();

  /* e^(t/T1) energy relaxation, e^(t/T2) phase relaxation. Want to use only 1/10 of T1 and T2 in general.*/

  backend = provider.getQuantumBackend();
  initializeLogger(provider);
  auto config = prepareBackendQubitConfiguration(true);
  qubit_ref = backend->createQubit(new QubitId(node_address, qnic_index, qnic_type, stationary_qubit_address), std::move(config));
  if (qubit_ref == nullptr) throw std::runtime_error("qubit_ref nullptr error");
  setFree(false);

  // watch variables to show them in the GUI
  WATCH(emitted_time);
  WATCH(is_busy);
  WATCH(qubit_ref);
}

std::unique_ptr<IConfiguration> StationaryQubit::prepareBackendQubitConfiguration(bool overwrite) {
  auto conf = backend->getDefaultConfiguration();
  if (!overwrite) return conf;
  if (auto et_conf = dynamic_cast<backend::StationaryQubitConfiguration *>(conf.get())) {
    et_conf->measurement_x_err_rate = par("x_measurement_error_rate").doubleValue();
    et_conf->measurement_y_err_rate = par("y_measurement_error_rate").doubleValue();
    et_conf->measurement_z_err_rate = par("z_measurement_error_rate").doubleValue();

    et_conf->h_gate_err_rate = par("h_gate_error_rate").doubleValue();
    et_conf->h_gate_x_err_ratio = par("h_gate_x_error_ratio").doubleValue();
    et_conf->h_gate_y_err_ratio = par("h_gate_y_error_ratio").doubleValue();
    et_conf->h_gate_z_err_ratio = par("h_gate_z_error_ratio").doubleValue();

    et_conf->x_gate_err_rate = par("x_gate_error_rate").doubleValue();
    et_conf->x_gate_x_err_ratio = par("x_gate_x_error_ratio").doubleValue();
    et_conf->x_gate_y_err_ratio = par("x_gate_y_error_ratio").doubleValue();
    et_conf->x_gate_z_err_ratio = par("x_gate_z_error_ratio").doubleValue();

    et_conf->z_gate_err_rate = par("z_gate_error_rate").doubleValue();
    et_conf->z_gate_x_err_ratio = par("z_gate_x_error_ratio").doubleValue();
    et_conf->z_gate_y_err_ratio = par("z_gate_y_error_ratio").doubleValue();
    et_conf->z_gate_z_err_ratio = par("z_gate_z_error_ratio").doubleValue();

    et_conf->cnot_gate_err_rate = par("cnot_gate_error_rate").doubleValue();
    et_conf->cnot_gate_iz_err_ratio = par("cnot_gate_iz_error_ratio").doubleValue();
    et_conf->cnot_gate_zi_err_ratio = par("cnot_gate_zi_error_ratio").doubleValue();
    et_conf->cnot_gate_zz_err_ratio = par("cnot_gate_zz_error_ratio").doubleValue();
    et_conf->cnot_gate_ix_err_ratio = par("cnot_gate_ix_error_ratio").doubleValue();
    et_conf->cnot_gate_xi_err_ratio = par("cnot_gate_xi_error_ratio").doubleValue();
    et_conf->cnot_gate_xx_err_ratio = par("cnot_gate_xx_error_ratio").doubleValue();
    et_conf->cnot_gate_iy_err_ratio = par("cnot_gate_iy_error_ratio").doubleValue();
    et_conf->cnot_gate_yi_err_ratio = par("cnot_gate_yi_error_ratio").doubleValue();
    et_conf->cnot_gate_yy_err_ratio = par("cnot_gate_yy_error_ratio").doubleValue();

    et_conf->memory_x_err_rate = par("memory_x_error_rate").doubleValue();
    et_conf->memory_y_err_rate = par("memory_y_error_rate").doubleValue();
    et_conf->memory_z_err_rate = par("memory_z_error_rate").doubleValue();
    et_conf->memory_excitation_rate = par("memory_energy_excitation_rate").doubleValue();
    et_conf->memory_relaxation_rate = par("memory_energy_relaxation_rate").doubleValue();
    et_conf->memory_completely_mixed_rate = par("memory_completely_mixed_rate").doubleValue();
  }
  return conf;
}

void StationaryQubit::finish() {}

/**
 * \brief handle FlyingQubit generated by StatinoryQubit itself
 *
 * \param msg is the FlyingQubit message
 */
void StationaryQubit::handleMessage(cMessage *msg) {
  if (!msg->isSelfMessage()) {
    throw cRuntimeError("StationaryQubit::handleMessage: message from outside is not expected");
  }
  bubble("Got a photon!!");
  setBusy();
  double rand = dblrand();
  if (rand < (1 - emission_success_probability)) {
    auto* photon = check_and_cast<FlyingQubit *>(msg);
    auto* qubit_ref = photon->getQubitRefForUpdate();
    if (qubit_ref != nullptr) {
      PhysicalServiceFacade service{backend};
      auto handle = makeHandle(qubit_ref);
      service.applyErrorChannel({handle}, "loss_channel", {{"legacy_channel_loss_rate", 1.0}});
    }
    if (logger != nullptr) {
      logger->logEvent("flying_qubit_loss", buildPhysicalEventPayload("loss", -1, true));
    }
  }
  if (logger != nullptr) {
    logger->logEvent("flying_qubit_sent", buildPhysicalEventPayload("sent"));
  }
  send(msg, "tolens_quantum_port");
}

EigenvalueResult StationaryQubit::measureX() {
  PhysicalServiceFacade service{backend};
  auto handle = makeHandle(*this);
  return service.measureX(handle);
}

EigenvalueResult StationaryQubit::measureY() {
  PhysicalServiceFacade service{backend};
  auto handle = makeHandle(*this);
  return service.measureY(handle);
}

EigenvalueResult StationaryQubit::measureZ() {
  PhysicalServiceFacade service{backend};
  auto handle = makeHandle(*this);
  return service.measureZ(handle);
}

void StationaryQubit::gateHadamard() {
  PhysicalServiceFacade service{backend};
  auto handle = makeHandle(*this);
  auto result = service.applyGate("H", {handle});
  if (!result.success) throw cRuntimeError("StationaryQubit::gateHadamard failed");
}

void StationaryQubit::gateX() {
  PhysicalServiceFacade service{backend};
  auto handle = makeHandle(*this);
  auto result = service.applyGate("X", {handle});
  if (!result.success) throw cRuntimeError("StationaryQubit::gateX failed");
}

void StationaryQubit::gateZ() {
  PhysicalServiceFacade service{backend};
  auto handle = makeHandle(*this);
  auto result = service.applyGate("Z", {handle});
  if (!result.success) throw cRuntimeError("StationaryQubit::gateZ failed");
}

void StationaryQubit::gateY() {
  PhysicalServiceFacade service{backend};
  auto handle = makeHandle(*this);
  auto result = service.applyGate("Y", {handle});
  if (!result.success) throw cRuntimeError("StationaryQubit::gateY failed");
}

void StationaryQubit::gateS() {
  PhysicalServiceFacade service{backend};
  auto handle = makeHandle(*this);
  auto result = service.applyGate("S", {handle});
  if (!result.success) throw cRuntimeError("StationaryQubit::gateS failed");
}

void StationaryQubit::gateSdg() {
  PhysicalServiceFacade service{backend};
  auto handle = makeHandle(*this);
  auto result = service.applyGate("Sdg", {handle});
  if (!result.success) throw cRuntimeError("StationaryQubit::gateSdg failed");
}

void StationaryQubit::gateCNOT(IStationaryQubit *target_qubit) {
  auto* target = check_and_cast<StationaryQubit *>(target_qubit);
  PhysicalServiceFacade service{backend};
  auto source_handle = makeHandle(*this);
  auto target_handle = makeHandle(*target);
  auto result = service.applyGate("CNOT", {source_handle, target_handle});
  if (!result.success) throw cRuntimeError("StationaryQubit::gateCNOT failed: %s", result.message.c_str());
}

// This is invoked whenever a photon is emitted out from this particular qubit.
void StationaryQubit::setBusy() {
  is_busy = true;
  emitted_time = simTime();
  if (hasGUI()) {
    getDisplayString().setTagArg("i", 1, "red");
  }
}

// Re-initialization of this stationary qubit
// This is called at the beginning of the simulation (in initialization() above), and whenever it is reinitialized via the RealTimeController.
void StationaryQubit::setFree(bool consumed) {
  qubit_ref->setFree();
  // Tell the physical backend that this slot is being recycled. For the qutip
  // backend this partial-traces the qubit out of the persistent density matrix
  // so the next H+CNOT on this slot does not pile a new photon on top of the
  // residual state from the previous (often failed) Bell-pair attempt.
  if (backend != nullptr) {
    PhysicalServiceFacade service{backend};
    service.releaseQubit(makeHandle(*this));
  }
  is_busy = false;
  locked = false;
  locked_ruleset_id = -1;
  locked_rule_id = -1;
  action_index = -1;
  emitted_time = -1;

  EV_DEBUG << "Freeing this qubit! " << this << " at qnode: " << node_address << " qnic_type: " << qnic_type << " qnic_index: " << qnic_index << "\n";
  if (hasGUI()) {
    if (consumed) {
      bubble("Consumed!");
      getDisplayString().setTagArg("i", 1, "yellow");
    } else {
      bubble("Failed to entangle!");
      getDisplayString().setTagArg("i", 1, "blue");
    }
  }
}

/*To avoid disturbing this qubit.*/
void StationaryQubit::Lock(unsigned long rs_id, int rule_id, int action_id) {
  if (rs_id == -1 || rule_id == -1 || action_id == -1) {
    error("ruleset_id || rule_id || action_id == -1");
  }
  locked = true;
  locked_ruleset_id = rs_id;  // Used to identify what this qubit is locked for.
  locked_rule_id = rule_id;
  action_index = action_id;
  if (hasGUI()) {
    bubble("Locked!");
    getDisplayString().setTagArg("i", 1, "purple");
  }
}

void StationaryQubit::Unlock() {
  locked = false;
  locked_ruleset_id = -1;  // Used to identify what this qubit is locked for.
  locked_rule_id = -1;
  action_index = -1;
  if (hasGUI()) {
    bubble("Unlocked!");
    getDisplayString().setTagArg("i", 1, "pink");
  }
}

bool StationaryQubit::isLocked() { return locked; }

/**
 * \brief Generate photon entangled with the memory
 * \warning Shouldn't we destroy a possibly existing photon object before? <- No, I dont think so...
 */
FlyingQubit *StationaryQubit::generateEntangledPhoton() {
  Enter_Method("generateEntangledPhoton()");
  auto *photon = new FlyingQubit("Photon");
  auto *photon_ref = backend->getFlyingQubit();
  auto source_handle = makeHandle(*this);
  auto target_handle = makeHandle(photon_ref);
  PhysicalServiceFacade service{backend};
  auto result = service.generateEntanglement(source_handle, target_handle);
  if (!result.success) {
    if (!result.message.empty()) {
      throw cRuntimeError("StationaryQubit::generateEntangledPhoton failed: %s", result.message.c_str());
    }
    throw cRuntimeError("StationaryQubit::generateEntangledPhoton failed");
  }
  photon->setQubitRef(photon_ref);
  if (logger != nullptr) {
    logger->logEvent("flying_qubit_generated", buildPhysicalEventPayload("generated"));
  }
  return photon;
}

/**
 * \brief Emit photon
 *
 * \param pulse: 0 for nothing, 1 for first, 2 for last, 3 for first and last
 *
 * The stationary qubit shouldn't be already busy.
 */
void StationaryQubit::emitPhoton(int pulse) {
  Enter_Method("emitPhoton()");
  if (is_busy) {
    error("Requested a photon emission to a busy qubit... this should not happen!");
    return;
  }
  FlyingQubit *pk = generateEntangledPhoton();
  if (logger != nullptr) {
    logger->logEvent("flying_qubit_emit", buildPhysicalEventPayload("emit", pulse));
  }
  if (pulse & STATIONARYQUBIT_PULSE_BEGIN) pk->setFirst(true);
  if (pulse & STATIONARYQUBIT_PULSE_END) pk->setLast(true);
  if (pulse & STATIONARYQUBIT_PULSE_BOUND) pk->setKind(3);
  float jitter_timing = normal(0, emission_jittering_standard_deviation);
  float abso = fabs(jitter_timing);
  scheduleAt(simTime() + abso, pk);  // cannot send back in time, so only positive lag
}

backends::IQubit *StationaryQubit::getBackendQubitRef() const { return qubit_ref; }

std::string StationaryQubit::buildPhysicalEventPayload(const char* phase, int pulse, bool photon_lost) const {
  auto dst_node_id = inferDestinationNodeIdFromCurrentPath(const_cast<StationaryQubit*>(this));
  if (dst_node_id.empty()) {
    dst_node_id = inferDestinationNodeId(const_cast<StationaryQubit*>(this));
  }
  std::ostringstream os;
  os << "{";
  os << "\"node_id\": " << node_address;
  os << ", \"qnic_index\": " << qnic_index;
  os << ", \"qnic_type\": " << qnic_type;
  os << ", \"stationary_qubit_address\": " << stationary_qubit_address;
  if (!dst_node_id.empty()) {
    os << ", \"dst_node_id\": " << dst_node_id;
  }
  os << ", \"phase\": \"" << phase << "\"";
  if (pulse >= 0) {
    os << ", \"pulse\": " << pulse;
  }
  os << ", \"photon_lost\": " << (photon_lost ? "true" : "false");
  os << "}";
  return os.str();
}

MeasurementOutcome StationaryQubit::measureRandomPauliBasis() {
  auto rand = dblrand();
  auto outcome = MeasurementOutcome();
  PhysicalServiceFacade service{backend};
  auto handle = makeHandle(*this);
  if (rand < 1.0 / 3) {
    outcome.outcome_is_plus = service.measureX(handle) == EigenvalueResult::PLUS_ONE;
    outcome.basis = 'X';
  } else if (rand < 2.0 / 3) {
    outcome.outcome_is_plus = service.measureY(handle) == EigenvalueResult::PLUS_ONE;
    outcome.basis = 'Y';
  } else {
    outcome.outcome_is_plus = service.measureZ(handle) == EigenvalueResult::PLUS_ONE;
    outcome.basis = 'Z';
  }
  outcome.GOD_clean = 'F';  // need to fix this to properly track the error
  return outcome;
}

}  // namespace quisp::modules
