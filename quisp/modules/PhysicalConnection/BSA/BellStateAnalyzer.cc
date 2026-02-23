/** \file BellStateAnalyzer.cc
 *
 *  \brief BellStateAnalyzer
 */
#include "BellStateAnalyzer.h"

#include <cctype>
#include <omnetpp/cexception.h>
#include <stdexcept>
#include <string>
#include <vector>

#include "modules/Backend/PhysicalServiceFacade.h"
#include "modules/QNIC/StationaryQubit/QubitId.h"

using namespace omnetpp;
using namespace quisp::messages;
using namespace quisp::physical::types;
using quisp::modules::backend::PhysicalServiceFacade;
using quisp::modules::backend::QubitHandle;

namespace quisp::modules {

namespace {
QubitHandle makeHandle(const quisp::backends::IQubit* qubit) {
  if (qubit == nullptr) throw std::runtime_error("BellStateAnalyzer::makeHandle: null qubit");
  const auto* id = qubit->getId();
  if (id == nullptr) throw std::runtime_error("BellStateAnalyzer::makeHandle: qubit has no id");
  const auto* qid = dynamic_cast<const quisp::modules::qubit_id::QubitId*>(id);
  if (qid == nullptr) throw std::runtime_error("BellStateAnalyzer::makeHandle: unsupported qubit id type");
  return QubitHandle{qid->node_addr, qid->qnic_index, qid->qnic_type, qid->qubit_addr};
}
}  // namespace

/** @class BellStateAnalyzer BellStateAnalyzer.cc
 *
 *  @brief BellStateAnalyzer
 */
Define_Module(BellStateAnalyzer);

BellStateAnalyzer::BellStateAnalyzer() : provider(utils::ComponentProvider{this}) {}

void BellStateAnalyzer::initialize() {
  state = BSAState::Idle;
  darkcount_probability = par("darkcount_probability").doubleValue();
  detection_efficiency = par("detection_efficiency").doubleValue();
  indistinguishability_window = SimTime(par("indistinguishable_time_window").doubleValue() * 1000, SIMTIME_PS);
  collection_efficiency = par("collection_efficiency").doubleValue();
  backend = provider.getQuantumBackend();
  validateProperties();
}

/**
 * @brief Handle the flying photonic qubits coming in to the BSA.
 * If the two photons arrive at the same time (within indistinguishable time window),
 * it will be entangled. We assume that we can distinguish between Psi+/- while
 * we cannot Phi+/- cannot be distinguished. Gate operations will be applied on the photons.
 *
 * @param msg must be of type PhotonicQubit message
 */
void BellStateAnalyzer::handleMessage(cMessage *msg) {
  auto photon = getPhotonRecordFromMessage(static_cast<PhotonicQubit *>(msg));
  delete msg;

  // clang-format off
  if ((state == BSAState::Idle && !photon.is_first) ||
      (state == BSAState::AcceptingFirstPort && photon.from_port == PortNumber::Second) ||
      (state == BSAState::AcceptingSecondPort && photon.from_port == PortNumber::First)) {
    discardPhoton(photon);
    return;
  }
  // clang-format on
  if (photon.is_first) {
    if (state == BSAState::Idle && photon.from_port == PortNumber::First) {
      state = BSAState::FirstPortArrive;
    } else if (state == BSAState::Idle && photon.from_port == PortNumber::Second) {
      state = BSAState::SecondPortArrive;
    } else if (state == BSAState::FirstPortArrive && photon.from_port == PortNumber::Second) {
      state = BSAState::Accepting;
      send(new CancelBSMTimeOutMsg(), "to_bsa_controller");
    } else if (state == BSAState::SecondPortArrive && photon.from_port == PortNumber::First) {
      state = BSAState::Accepting;
      send(new CancelBSMTimeOutMsg(), "to_bsa_controller");
    } else if (state == BSAState::AcceptingFirstPort && photon.from_port == PortNumber::First) {
      send(new CancelBSMTimeOutMsg(), "to_bsa_controller");
    } else if (state == BSAState::AcceptingSecondPort && photon.from_port == PortNumber::Second) {
      send(new CancelBSMTimeOutMsg(), "to_bsa_controller");
    } else {
      throw cRuntimeError("This should not happen; BSA state isn't set correctly.");
    }
  }

  if (photon.from_port == PortNumber::First)
    first_port_records.emplace_back(photon);
  else
    second_port_records.emplace_back(photon);

  if (!photon.is_last) {
    return;
  }

  if (state == BSAState::AcceptingFirstPort || state == BSAState::AcceptingSecondPort) {  // must be last photon
    state = BSAState::Idle;
    processPhotonRecords();
    return;
  }

  if (photon.from_port == PortNumber::First)
    state = BSAState::AcceptingSecondPort;
  else
    state = BSAState::AcceptingFirstPort;
}

void BellStateAnalyzer::processPhotonRecords() {
  auto *batch_click_msg = new BatchClickEvent();
  int number_of_possible_pairs = std::min(first_port_records.size(), second_port_records.size());
  for (int i = 0; i < number_of_possible_pairs; i++) {
    auto p = first_port_records[i];
    auto q = second_port_records[i];

    if (fabs(p.arrival_time - q.arrival_time) < indistinguishability_window) {
      batch_click_msg->appendClickResults(processIndistinguishPhotons(p, q));
    } else {
      batch_click_msg->appendClickResults({.success = false, .correction_operation = PauliOperator::I});
      discardPhoton(p);
      discardPhoton(q);
    }
  }
  first_port_records.clear();
  second_port_records.clear();
  send(batch_click_msg, "to_bsa_controller");
}

PhotonRecord BellStateAnalyzer::getPhotonRecordFromMessage(PhotonicQubit *photon_msg) {
  PhotonRecord photon{.qubit_ref = photon_msg->getQubitRefForUpdate(),
                      .arrival_time = photon_msg->getArrivalTime(),
                      .from_port = (photon_msg->arrivedOn("quantum_port$i", 0)) ? PortNumber::First : PortNumber::Second,
                      .is_first = photon_msg->isFirst(),
                      .is_last = photon_msg->isLast()};

  return photon;
}

BSAClickResult BellStateAnalyzer::processIndistinguishPhotons(PhotonRecord &p, PhotonRecord &q) {
  ++pair_count;
  ++indistinguishable_pair_count;

  auto p_handle = makeHandle(p.qubit_ref);
  auto q_handle = makeHandle(q.qubit_ref);
  PhysicalServiceFacade service{backend};

  const auto hom_result = service.applyHomInterference({p_handle, q_handle},
                                                      {{"collection_efficiency", collection_efficiency},
                                                       {"detection_efficiency", detection_efficiency},
                                                       {"darkcount_probability", darkcount_probability}});
  if (!hom_result.success) {
    discardPhoton(p);
    discardPhoton(q);
    return {false, PauliOperator::I};
  }

  const auto detection_result = service.applyDetection(
      {p_handle, q_handle},
      {{"efficiency", detection_efficiency * collection_efficiency}, {"dark_count", darkcount_probability}, {"visibility", detection_efficiency}});
  auto pattern = normalizeOutcomePattern(detection_result.outcome_pattern);
  if (pattern.empty()) {
    pattern = detection_result.measured_plus ? "d1,d3" : "none";
  }
  pattern_count[pattern]++;

  const auto click_result = determineClickResult(pattern);
  discardPhoton(p);
  discardPhoton(q);
  return click_result;
}

std::string BellStateAnalyzer::normalizeOutcomePattern(const std::string& pattern) const {
  std::string normalized;
  normalized.reserve(pattern.size());
  for (char ch : pattern) {
    if (std::isspace(static_cast<unsigned char>(ch))) {
      continue;
    }
    normalized.push_back(std::tolower(static_cast<unsigned char>(ch)));
  }
  return normalized;
}

BSAClickResult BellStateAnalyzer::determineClickResult(const std::string& pattern) {
  if (pattern == "d1,d3" || pattern == "d3,d1" || pattern == "success" || pattern == "click") {
    return {true, PauliOperator::X};
  }
  if (pattern == "d0" || pattern == "d2") {
    return {true, PauliOperator::Z};
  }
  return {false, PauliOperator::I};
}

void BellStateAnalyzer::resetState() {
  state = BSAState::Idle;
  first_port_records.clear();
  second_port_records.clear();
}

void BellStateAnalyzer::validateProperties() {
  // currently we only allow 2 port BSA
  if (this->gateSize("quantum_port") != 2) {
    throw std::runtime_error("BellStateAnalyzer::parameter validation fail; BSA doesn't have 2 input quantum ports");
  }
  // validating parameters
  if (darkcount_probability < 0 || darkcount_probability > 1)
    throw std::runtime_error("BellStateAnalyzer::parameter validation fail; darkcount_probability does not in the [0, 1] range");
  if (detection_efficiency < 0 || detection_efficiency > 1)
    throw std::runtime_error("BellStateAnalyzer::parameter validation fail; detection_efficiency does not in the [0, 1] range");
  if (indistinguishability_window < 0) throw std::runtime_error("BellStateAnalyzer::parameter validation fail; indistinguishability_window cannot be lower than 0");
  if (collection_efficiency < 0 || collection_efficiency > 1)
    throw std::runtime_error("BellStateAnalyzer::parameter validation fail; collection_efficiency does not in the [0, 1] range");
}

void BellStateAnalyzer::finish() {
  std::cout << "BSA Statistics (pattern):\n";
  std::cout << "  pairs=" << pair_count << "\n";
  std::cout << "  indistinguishable_pairs=" << indistinguishable_pair_count << "\n";
  std::cout << "  pattern_counts:\n";
  for (const auto& pattern_pair : pattern_count) {
    std::cout << "    " << pattern_pair.first << ": " << pattern_pair.second << "\n";
  }
}

void BellStateAnalyzer::discardPhoton(PhotonRecord &photon) { photon.qubit_ref->relaseBackToPool(); };

}  // namespace quisp::modules
