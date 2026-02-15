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
#include <sstream>
#include <variant>
#include <stdexcept>
#include <utility>

#include "QNicStore/QNicStore.h"
#include "RuleProtocolExecutionContext.h"
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

RuleEngine::RuleEngine()
    : provider(utils::ComponentProvider{this}),
      runtimes(std::make_unique<RuntimeCallback>(this)),
      protocol_execution_context(std::make_unique<RuleProtocolExecutionContext>(*this)) {
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
  registerRuleEventHandler(event_type, RuleEventProtocol::Unknown, std::move(handler));
}

void RuleEngine::registerRuleEventHandler(RuleEventType event_type, RuleEventProtocol protocol_spec, RuleEventHandler handler) {
  rule_event_handlers[{event_type, protocol_spec}] = std::move(handler);
}

void RuleEngine::registerRuleEventTypeFallback(RuleEventType event_type, RuleEventHandler handler) {
  rule_event_type_fallback_handlers[static_cast<int>(event_type)] = std::move(handler);
}

void RuleEngine::registerRuleEventProtocolFallback(RuleEventProtocol protocol_spec, RuleEventHandler handler) {
  rule_protocol_fallback_handlers[static_cast<int>(protocol_spec)] = std::move(handler);
}

void RuleEngine::registerRuleEventHandlers() {
  RuleProtocolHandlerRegistrar::registerDefaults(*this);
}

void RuleEngine::logUnknownRuleEvent(const core::events::RuleEvent &event) {
  if (logger == nullptr) {
    return;
  }
  std::ostringstream ss;
  ss << "\"simtime\": " << event.time << ", \"event_number\": " << event.event_number << ", \"event_type\": \"UNKNOWN\", \"protocol_spec\": \""
     << to_string(event.protocol_spec) << "\", \"execution_path\": \"" << to_string(event.execution_path) << "\", \"protocol_raw_value\": \""
     << event.protocol_raw_value << "\", \"msg_name\": \"" << event.msg_name << "\", \"msg_type\": \"" << event.msg_type << "\", \"qnode_addr\": "
     << parentAddress << ", \"parentAddress\": " << parentAddress;
  logger->logEvent("unknown_rule_event", ss.str());
}

void RuleEngine::logUnknownRuleProtocol(const core::events::RuleEvent &event) {
  if (logger == nullptr) {
    return;
  }
  std::ostringstream ss;
  ss << "\"simtime\": " << event.time << ", \"event_number\": " << event.event_number << ", \"event_type\": \""
     << static_cast<int>(event.type) << "\", \"protocol_spec\": \"" << to_string(event.protocol_spec) << "\", \"execution_path\": \""
     << to_string(event.execution_path) << "\", \"protocol_raw_value\": \"" << event.protocol_raw_value << "\", \"msg_name\": \""
     << event.msg_name << "\", \"msg_type\": \"" << event.msg_type << "\", \"qnode_addr\": " << parentAddress
     << ", \"parentAddress\": " << parentAddress;
  logger->logEvent("unknown_rule_protocol", ss.str());
}

void RuleEngine::dispatchRuleEvent(const core::events::RuleEvent &event) {
  // Unknown protocol value is tracked separately from unknown event type.
  // unknown protocol => log unknown_rule_protocol even when a handler is not found.
  const auto protocol_unknown = event.protocol_spec == RuleEventProtocol::Unknown;
  const auto should_log_unknown_protocol = protocol_unknown && event.type != core::events::RuleEventType::UNKNOWN;
  auto it = rule_event_handlers.find({event.type, event.protocol_spec});
  if (it != rule_event_handlers.end()) {
    it->second(event);
    if (should_log_unknown_protocol) {
      logUnknownRuleProtocol(event);
    }
    return;
  }

  if (const auto type_fallback_it = rule_event_type_fallback_handlers.find(static_cast<int>(event.type));
      type_fallback_it != rule_event_type_fallback_handlers.end()) {
    type_fallback_it->second(event);
    if (should_log_unknown_protocol) {
      logUnknownRuleProtocol(event);
    }
    return;
  }

  if (const auto protocol_fallback_it = rule_protocol_fallback_handlers.find(static_cast<int>(event.protocol_spec));
      protocol_fallback_it != rule_protocol_fallback_handlers.end()) {
    protocol_fallback_it->second(event);
    if (should_log_unknown_protocol) {
      logUnknownRuleProtocol(event);
    }
    return;
  }

  if (event.type == core::events::RuleEventType::UNKNOWN) {
    logUnknownRuleEvent(event);
  } else {
    logUnknownRuleProtocol(event);
  }
  return;
}

void RuleEngine::handleRuleEvent(const core::events::RuleEvent &event) {
  dispatchRuleEvent(event);
}

RuleProtocolExecutionContext& RuleEngine::protocolExecutionContext() {
  return *protocol_execution_context;
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
  protocol_execution_context->handleSingleClickResult(click_result);
}

void RuleEngine::handleMSMResult(MSMResult *msm_result) {
  protocol_execution_context->handleMSMResult(msm_result);
}

void RuleEngine::handleLinkGenerationResult(CombinedBSAresults *bsa_result) {
  protocol_execution_context->handleLinkGenerationResult(bsa_result);
}

void RuleEngine::handleStopEmitting(StopEmitting *stop_emit) {
  protocol_execution_context->handleStopEmitting(stop_emit);
}

void RuleEngine::handlePurificationResult(PurificationResult *result) {
  protocol_execution_context->handlePurificationResult(result);
}

void RuleEngine::handleSwappingResult(SwappingResult *result) {
  protocol_execution_context->handleSwappingResult(result);
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
