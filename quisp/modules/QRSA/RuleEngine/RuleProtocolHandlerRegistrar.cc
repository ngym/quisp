#include "RuleProtocolHandlerRegistrar.h"

#include "RuleEngine.h"
#include <nlohmann/json.hpp>
#include <functional>
#include <stdexcept>
#include <utility>

#include "messages/classical_messages.h"
#include "omnetpp.h"

namespace quisp::modules {

using namespace messages;
using namespace core::events;
using EventType = RuleEventType;
using EventProtocol = ProtocolSpec;
using EventHandler = RuleEngine::RuleEventHandler;

void RuleProtocolHandlerRegistrar::registerDefaults(RuleEngine& engine) {
  const auto submit_forwarded_ruleset = [&engine](const std::string& serialized_ruleset) {
    rules::RuleSet ruleset(0, 0);
    ruleset.deserialize_json(nlohmann::json::parse(serialized_ruleset));
    engine.runtimes.submitRuleSet(ruleset.construct());
  };

  auto register_handler = [&engine](EventType event_type, EventProtocol protocol_spec, EventHandler handler) {
    engine.registerRuleEventHandler(event_type, protocol_spec, std::move(handler));
  };

  register_handler(EventType::BSM_RESULT, EventProtocol::MIM_v1, [&engine](const RuleEvent& event) {
    engine.handleLinkGenerationResult(std::get<CombinedBSAresults *>(event.payload));
  });

  register_handler(EventType::BSM_TIMING, EventProtocol::MIM_v1, [&engine](const RuleEvent& event) {
    auto *notification_packet = std::get<BSMTimingNotification *>(event.payload);
    auto type = notification_packet->getQnicType();
    auto qnic_index = notification_packet->getQnicIndex();
    engine.stopOnGoingPhotonEmission(type, qnic_index);
    engine.freeFailedEntanglementAttemptQubits(type, qnic_index);
    engine.schedulePhotonEmission(type, qnic_index, notification_packet);
  });

  register_handler(EventType::EPPS_TIMING, EventProtocol::MSM_v1, [&engine](const RuleEvent& event) {
    auto *notification_packet = std::get<EPPSTimingNotification *>(event.payload);
    auto partner_address = notification_packet->getOtherQnicParentAddr();
    auto partner_qnic_index = notification_packet->getOtherQnicIndex();
    auto epps_address = notification_packet->getEPPSAddr();
    auto qnic_index = notification_packet->getQnicIndex();
    auto &msm_info = engine.msm_info_map[qnic_index];
    msm_info.partner_address = partner_address;
    msm_info.epps_address = epps_address;
    msm_info.partner_qnic_index = partner_qnic_index;
    msm_info.total_travel_time = notification_packet->getTotalTravelTime();
    engine.stopOnGoingPhotonEmission(QNIC_RP, qnic_index);
    engine.scheduleMSMPhotonEmission(QNIC_RP, qnic_index, notification_packet);
  });

  register_handler(EventType::EMIT_PHOTON_REQUEST, EventProtocol::Unknown, [&engine](const RuleEvent& event) {
    auto *pk = std::get<EmitPhotonRequest *>(event.payload);
    auto type = pk->getQnicType();
    auto qnic_index = pk->getQnicIndex();
    auto number_of_free_emitters = engine.qnic_store->countNumFreeQubits(type, qnic_index);
    auto qubit_index = engine.qnic_store->takeFreeQubitIndex(type, qnic_index);

    if (pk->isMSM()) {
      auto &msm_info = engine.msm_info_map[qnic_index];
      msm_info.photon_index_counter++;
      if (number_of_free_emitters != 0) {
        msm_info.qubit_info_map[msm_info.iteration_index] = qubit_index;
        engine.sendEmitPhotonSignalToQnic(type, qnic_index, qubit_index, true, true);
      } else {
        auto *msm_result = new messages::MSMResult();
        msm_result->setQnicIndex(msm_info.partner_qnic_index);
        msm_result->setQnicType(QNIC_RP);
        msm_result->setPhotonIndex(msm_info.photon_index_counter);
        msm_result->setSuccess(false);
        msm_result->setCorrectionOperation(PauliOperator::I);
        msm_result->setSrcAddr(engine.parentAddress);
        msm_result->setDestAddr(msm_info.partner_address);
        msm_result->setKind(6);
        engine.send(msm_result, "RouterPort$o");
      }
      engine.scheduleAt(simTime() + pk->getIntervalBetweenPhotons(), pk);
    } else {
      auto is_first = pk->isFirst();
      auto is_last = (number_of_free_emitters == 1);
      pk->setFirst(false);
      engine.sendEmitPhotonSignalToQnic(type, qnic_index, qubit_index, is_first, is_last);
      if (!is_last) {
        engine.scheduleAt(simTime() + pk->getIntervalBetweenPhotons(), pk);
      }
    }
  });

  register_handler(EventType::SINGLE_CLICK_RESULT, EventProtocol::MSM_v1, [&engine](const RuleEvent& event) {
    engine.handleSingleClickResult(std::get<SingleClickResult *>(event.payload));
  });

  register_handler(EventType::MSM_RESULT, EventProtocol::MSM_v1, [&engine](const RuleEvent& event) {
    engine.handleMSMResult(std::get<MSMResult *>(event.payload));
  });

  register_handler(EventType::LINK_TOMOGRAPHY_RULESET, EventProtocol::LinkTomography, [&engine](const RuleEvent& event) {
    auto *pk = std::get<LinkTomographyRuleSet *>(event.payload);
    auto *ruleset = pk->getRuleSet();
    engine.runtimes.submitRuleSet(ruleset->construct());
  });

  register_handler(EventType::PURIFICATION_RESULT, EventProtocol::Purification, [&engine](const RuleEvent& event) {
    engine.handlePurificationResult(std::get<PurificationResult *>(event.payload));
  });

  register_handler(EventType::SWAPPING_RESULT, EventProtocol::Swapping, [&engine](const RuleEvent& event) {
    engine.handleSwappingResult(std::get<SwappingResult *>(event.payload));
  });

  register_handler(EventType::RULESET_FORWARDING, EventProtocol::ConnectionManagement, [&engine, submit_forwarded_ruleset](const RuleEvent& event) {
    auto *pkt = std::get<InternalRuleSetForwarding *>(event.payload);
    auto serialized_ruleset = pkt->getRuleSet().dump();
    submit_forwarded_ruleset(serialized_ruleset);
  });

  register_handler(EventType::RULESET_FORWARDING_APPLICATION, EventProtocol::ConnectionManagement, [&engine, submit_forwarded_ruleset](const RuleEvent& event) {
    auto *pkt = std::get<InternalRuleSetForwarding_Application *>(event.payload);
    auto application_type = pkt->getApplication_type();
    if (application_type != 0) {
      return;
    }
    auto serialized_ruleset = pkt->getRuleSet().dump();
    submit_forwarded_ruleset(serialized_ruleset);
  });

  register_handler(EventType::STOP_EMITTING, EventProtocol::MSM_v1, [&engine](const RuleEvent& event) {
    engine.handleStopEmitting(std::get<StopEmitting *>(event.payload));
  });

  register_handler(EventType::UNKNOWN, EventProtocol::Unknown, [&engine](const RuleEvent& event) {
    (void)event;
    engine.logUnknownRuleEvent(event);
  });
}

}  // namespace quisp::modules
