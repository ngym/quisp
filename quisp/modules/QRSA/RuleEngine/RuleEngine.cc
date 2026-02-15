/** \file RuleEngine.cc
 *
 *  \brief RuleEngine
 */
#include "RuleEngine.h"

#include <cassert>
#include <fstream>
#include <iostream>
#include <iterator>
#include <memory>
#include <ostream>
#include <variant>
#include <stdexcept>
#include <utility>

#include "QNicStore/QNicStore.h"
#include "RuntimeCallback.h"
#include "messages/BSA_ipc_messages_m.h"
#include "messages/QNode_ipc_messages_m.h"
#include "messages/link_generation_messages_m.h"
#include "modules/PhysicalConnection/BSA/types.h"
#include "modules/QNIC.h"
#include "RuleProtocolHandlerRegistrar.h"
#include "omnetpp/csimulation.h"
#include "omnetpp/errmsg.h"
#include "omnetpp/simtime_t.h"

namespace quisp::modules {

using namespace rules;
using namespace messages;
using qnic_store::QNicStore;
using runtime_callback::RuntimeCallback;

RuleEngine::RuleEngine() : provider(utils::ComponentProvider{this}), runtimes(std::make_unique<RuntimeCallback>(this)) {
  registerRuleEventHandlers();
}

RuleEngine::~RuleEngine() {
  for (int i = 0; i < number_of_qnics; i++) cancelAndDelete(emit_photon_timer_map[{QNIC_type::QNIC_E, i}]);
  for (int i = 0; i < number_of_qnics_r; i++) cancelAndDelete(emit_photon_timer_map[{QNIC_type::QNIC_R, i}]);
  for (int i = 0; i < number_of_qnics_rp; i++) cancelAndDelete(emit_photon_timer_map[{QNIC_type::QNIC_RP, i}]);
}

void RuleEngine::initialize() {
  // HardwareMonitor's neighbor table is checked in the initialization stage of the simulation
  // This assumes the topology never changes throughout the simulation.
  // If dynamic change in topology is required, recoding this is needed.
  hardware_monitor = provider.getHardwareMonitor();
  realtime_controller = provider.getRealTimeController();
  routingdaemon = provider.getRoutingDaemon();
  initializeLogger(provider);
  bell_pair_store.logger = logger;

  parentAddress = provider.getNodeAddr();
  number_of_qnics_all = par("total_number_of_qnics");
  number_of_qnics = par("number_of_qnics");
  number_of_qnics_r = par("number_of_qnics_r");
  number_of_qnics_rp = par("number_of_qnics_rp");
  if (qnic_store == nullptr) {
    qnic_store = std::make_unique<QNicStore>(provider, number_of_qnics, number_of_qnics_r, number_of_qnics_rp, logger);
  }
  for (int i = 0; i < number_of_qnics; i++) {
    emit_photon_timer_map[{QNIC_type::QNIC_E, i}] = new EmitPhotonRequest();
    emit_photon_timer_map[{QNIC_type::QNIC_E, i}]->setQnicType(QNIC_type::QNIC_E);
    emit_photon_timer_map[{QNIC_type::QNIC_E, i}]->setQnicIndex(i);
  }
  for (int i = 0; i < number_of_qnics_r; i++) {
    emit_photon_timer_map[{QNIC_type::QNIC_R, i}] = new EmitPhotonRequest();
    emit_photon_timer_map[{QNIC_type::QNIC_R, i}]->setQnicType(QNIC_type::QNIC_R);
    emit_photon_timer_map[{QNIC_type::QNIC_R, i}]->setQnicIndex(i);
  }
  for (int i = 0; i < number_of_qnics_rp; i++) {
    emit_photon_timer_map[{QNIC_type::QNIC_RP, i}] = new EmitPhotonRequest();
    emit_photon_timer_map[{QNIC_type::QNIC_RP, i}]->setQnicType(QNIC_type::QNIC_RP);
    emit_photon_timer_map[{QNIC_type::QNIC_RP, i}]->setQnicIndex(i);
  }
}

void RuleEngine::handleMessage(cMessage *msg) {
  executeAllRuleSets();  // New resource added to QNIC with qnic_type qnic_index.

  event_bus.publish(msg, simTime());
  bool keep_message = false;
  for (auto &&event : event_bus.drain(simTime())) {
    keep_message = keep_message || event.channel == core::events::RuleEventChannel::INTERNAL_TIMER || event.keep_source;
    handleRuleEvent(event);
  }

  for (int i = 0; i < number_of_qnics; i++) {
    ResourceAllocation(QNIC_E, i);
  }
  for (int i = 0; i < number_of_qnics_r; i++) {
    ResourceAllocation(QNIC_R, i);
  }
  for (int i = 0; i < number_of_qnics_rp; i++) {
    ResourceAllocation(QNIC_RP, i);
  }

  executeAllRuleSets();
  if (!keep_message) {
    delete msg;
  }
}

void RuleEngine::registerRuleEventHandler(RuleEventType event_type, RuleEventHandler handler) {
  rule_event_handlers[static_cast<int>(event_type)] = std::move(handler);
}

void RuleEngine::registerRuleEventHandlers() {
  RuleProtocolHandlerRegistrar::registerDefaults(*this);
}

void RuleEngine::logUnknownRuleEvent(const core::events::RuleEvent &event) {
  if (logger == nullptr) {
    return;
  }
  std::ostringstream ss;
  ss << "\"simtime\": " << event.time << ", \"event_number\": " << event.event_number << ", \"event_type\": \"UNKNOWN\", \"msg_name\": \"";
  ss << event.msg_name << "\", \"msg_type\": \"" << event.msg_type << "\", \"qnode_addr\": " << parentAddress << ", \"parentAddress\": " << parentAddress;
  logger->logEvent("unknown_rule_event", ss.str());
}

void RuleEngine::dispatchRuleEvent(const core::events::RuleEvent &event) {
  const auto event_type = static_cast<int>(event.type);
  if (const auto it = rule_event_handlers.find(event_type); it != rule_event_handlers.end()) {
    it->second(event);
    return;
  }
  logUnknownRuleEvent(event);
}

void RuleEngine::handleRuleEvent(const core::events::RuleEvent &event) {
  dispatchRuleEvent(event);
}

void RuleEngine::schedulePhotonEmission(QNIC_type type, int qnic_index, BSMTimingNotification *notification) {
  auto first_photon_emit_time = getEmitTimeFromBSMNotification(notification);
  const auto timer_it = emit_photon_timer_map.find({type, qnic_index});
  if (timer_it == emit_photon_timer_map.end() || timer_it->second == nullptr) {
    return;
  }
  auto *timer = timer_it->second;
  timer->setFirst(true);
  timer->setIntervalBetweenPhotons(notification->getInterval());
  timer->setMSM(false);
  scheduleAt(first_photon_emit_time, timer);
}

void RuleEngine::scheduleMSMPhotonEmission(QNIC_type type, int qnic_index, EPPSTimingNotification *notification) {
  auto first_photon_emit_time = notification->getFirstPhotonEmitTime();
  const auto timer_it = emit_photon_timer_map.find({type, qnic_index});
  if (timer_it == emit_photon_timer_map.end() || timer_it->second == nullptr) {
    return;
  }
  auto *timer = timer_it->second;
  timer->setFirst(true);
  timer->setIntervalBetweenPhotons(notification->getInterval());
  timer->setMSM(true);
  scheduleAt(first_photon_emit_time, timer);
}

void RuleEngine::sendEmitPhotonSignalToQnic(QNIC_type qnic_type, int qnic_index, int qubit_index, bool is_first, bool is_last) {
  int pulse = 0;
  if (is_first) pulse |= STATIONARYQUBIT_PULSE_BEGIN;
  if (is_last) pulse |= STATIONARYQUBIT_PULSE_END;
  realtime_controller->EmitPhoton(qnic_index, qubit_index, qnic_type, pulse);
  if (qnic_type != QNIC_RP) emitted_photon_order_map[{qnic_type, qnic_index}].push_back(qubit_index);
}
simtime_t RuleEngine::getEmitTimeFromBSMNotification(quisp::messages::BSMTimingNotification *notification) { return notification->getFirstPhotonEmitTime(); }

void RuleEngine::stopOnGoingPhotonEmission(QNIC_type type, int qnic_index) {
  const auto it = emit_photon_timer_map.find({type, qnic_index});
  if (it == emit_photon_timer_map.end() || it->second == nullptr) {
    return;
  }
  cancelEvent(it->second);
}

void RuleEngine::freeFailedEntanglementAttemptQubits(QNIC_type type, int qnic_index) {
  auto &emitted_indices = emitted_photon_order_map[{type, qnic_index}];
  for (auto qubit_index : emitted_indices) {
    realtime_controller->ReInitialize_StationaryQubit(qnic_index, qubit_index, type, false);
    qnic_store->setQubitBusy(type, qnic_index, qubit_index, false);
  }
  emitted_indices.clear();
}

void RuleEngine::handleSingleClickResult(SingleClickResult *click_result) {
  auto qnic_index = click_result->getQnicIndex();
  auto &msm_info = msm_info_map[qnic_index];
  auto qubit_index = msm_info.qubit_info_map[msm_info.iteration_index];
  MSMResult *msm_result = new MSMResult();
  msm_result->setQnicIndex(msm_info.partner_qnic_index);
  msm_result->setQnicType(QNIC_RP);
  msm_result->setPhotonIndex(msm_info.photon_index_counter);
  msm_result->setSuccess(click_result->getClickResult().success);
  msm_result->setCorrectionOperation(click_result->getClickResult().correction_operation);
  msm_result->setSrcAddr(parentAddress);
  msm_result->setDestAddr(msm_info.partner_address);
  msm_result->setKind(6);
  if (click_result->getClickResult().success) {
    msm_info.qubit_postprocess_info[msm_info.photon_index_counter].qubit_index = qubit_index;
    msm_info.qubit_postprocess_info[msm_info.photon_index_counter].correction_operation = click_result->getClickResult().correction_operation;
    msm_info.iteration_index++;
  } else {
    realtime_controller->ReInitialize_StationaryQubit(qnic_index, qubit_index, QNIC_RP, false);
    qnic_store->setQubitBusy(QNIC_RP, qnic_index, qubit_index, false);
  }
  send(msm_result, "RouterPort$o");
}

void RuleEngine::handleMSMResult(MSMResult *msm_result) {
  auto qnic_index = msm_result->getQnicIndex();
  auto &msm_info = msm_info_map[qnic_index];
  auto qubit_itr = msm_info.qubit_postprocess_info.find(msm_result->getPhotonIndex());
  // local: fail | partner: success/fail
  // qubit on photon index is not included in msm_info
  if (qubit_itr == msm_info.qubit_postprocess_info.end()) {
    return;
  }
  QubitInfo qubit_info = qubit_itr->second;
  auto qubit_index = qubit_info.qubit_index;
  // local: success | partner: fail
  // qubit on photon index is included in msm_info but the partner sends fail
  if (!msm_result->getSuccess()) {
    realtime_controller->ReInitialize_StationaryQubit(qnic_index, qubit_index, QNIC_RP, false);
    qnic_store->setQubitBusy(QNIC_RP, qnic_index, qubit_index, false);
  }
  // local: success | partner: success
  // qubit on photon index is included in msm_info and the partner sends success
  else {
    auto *qubit_record = qnic_store->getQubitRecord(QNIC_RP, qnic_index, qubit_index);
    // condition whether to apply Z gate or not
    bool is_phi_minus = qubit_info.correction_operation != msm_result->getCorrectionOperation();
    // restrict correction operation only on one side
    bool is_younger_address = parentAddress < msm_info.partner_address;
    if (is_phi_minus && is_younger_address) realtime_controller->applyZGate(qubit_record);
    bell_pair_store.insertEntangledQubit(msm_info.partner_address, qubit_record);
  }
}

void RuleEngine::handleLinkGenerationResult(CombinedBSAresults *bsa_result) {
  auto type = bsa_result->getQnicType();
  auto qnic_index = bsa_result->getQnicIndex();
  auto num_success = bsa_result->getSuccessCount();
  auto partner_address = bsa_result->getNeighborAddress();
  auto &emitted_indices = emitted_photon_order_map[{type, qnic_index}];
  for (int i = num_success - 1; i >= 0; i--) {
    auto emitted_index = bsa_result->getSuccessfulPhotonIndices(i);
    auto qubit_index = emitted_indices[emitted_index];
    auto *qubit_record = qnic_store->getQubitRecord(type, qnic_index, qubit_index);
    auto iterator = emitted_indices.begin();
    std::advance(iterator, emitted_index);
    bell_pair_store.insertEntangledQubit(partner_address, qubit_record);
    emitted_indices.erase(iterator);

    auto correction_operation = bsa_result->getCorrectionOperationList(i);
    if (correction_operation == PauliOperator::X) {
      realtime_controller->applyXGate(qubit_record);
    } else if (correction_operation == PauliOperator::Z) {
      realtime_controller->applyZGate(qubit_record);
    } else if (correction_operation == PauliOperator::Y) {
      realtime_controller->applyYGate(qubit_record);
    }
  }
}

void RuleEngine::handleStopEmitting(StopEmitting *stop_emit) {
  int qnic_index = stop_emit->getQnic_address();
  auto &msm_info = msm_info_map[qnic_index];
  // only do the following procedure for MSM links
  if (msm_info.photon_index_counter == 0) return;
  StopEPPSEmission *stop_epps_emission = new StopEPPSEmission();
  stop_epps_emission->setSrcAddr(parentAddress);
  stop_epps_emission->setDestAddr(msm_info.epps_address);
  send(stop_epps_emission, "RouterPort$o");
}

void RuleEngine::handlePurificationResult(PurificationResult *result) {
  auto ruleset_id = result->getRulesetId();
  auto shared_rule_tag = result->getSharedRuleTag();
  auto sequence_number = result->getSequenceNumber();
  auto measurement_result = result->getMeasurementResult();
  auto purification_protocol = result->getProtocol();
  std::vector<int> message_content = {sequence_number, measurement_result, purification_protocol};
  runtimes.assignMessageToRuleSet(ruleset_id, shared_rule_tag, message_content);
}

void RuleEngine::handleSwappingResult(SwappingResult *result) {
  auto ruleset_id = result->getRulesetId();
  auto shared_rule_tag = result->getSharedRuleTag();
  auto sequence_number = result->getSequenceNumber();
  auto correction_frame = result->getCorrectionFrame();
  auto new_partner_addr = result->getNewPartner();
  std::vector<int> message_content = {sequence_number, correction_frame, new_partner_addr};
  runtimes.assignMessageToRuleSet(ruleset_id, shared_rule_tag, message_content);
}

// Invoked whenever a new resource (entangled with neighbor) has been created.
// Allocates those resources to a particular ruleset, from top to bottom (all of it).
void RuleEngine::ResourceAllocation(int qnic_type, int qnic_index) {
  runtimes.allocateResources(bell_pair_store, static_cast<QNIC_type>(qnic_type), qnic_index);
}

void RuleEngine::executeAllRuleSets() { runtimes.exec(); }

void RuleEngine::freeConsumedResource(int qnic_index /*Not the address!!!*/, IStationaryQubit *qubit, QNIC_type qnic_type) {
  int qubit_address = qubit_index_to_address(qubit, qnic_index);
  auto *qubit_record = qnic_store->getQubitRecord(qnic_type, qnic_index, qubit_address);
  realtime_controller->ReInitialize_StationaryQubit(qubit_record, false);
  qubit_record->setBusy(false);
  if (qubit_record->isAllocated()) {
    qubit_record->setAllocated(false);
  }
  bell_pair_store.eraseQubit(qubit_record);
}

int RuleEngine::qubit_index_to_address(IStationaryQubit *qubit, int default_index) {
  if (qubit->getSimulation() == nullptr) {
    return default_index;
  }
  auto stationary_qubit_address = qubit->findPar("stationary_qubit_address");
  if (stationary_qubit_address != -1) {
    return qubit->par(stationary_qubit_address).intValue();
  }
  auto qnic_address = qubit->findPar("qnic_address");
  if (qnic_address != -1) {
    return qubit->par(qnic_address).intValue();
  }
  return default_index;
}

}  // namespace quisp::modules
