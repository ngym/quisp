#include "MSMProtocolHandler.h"

#include <functional>
#include <utility>

#include "RuleEngine.h"
#include "messages/classical_messages.h"

namespace quisp::modules::handlers {

using EventType = core::events::RuleEventType;
using EventProtocol = core::events::ProtocolSpec;
using EventHandler = quisp::modules::RuleEngine::RuleEventHandler;

core::events::ProtocolSpec MSMProtocolHandler::protocolSpec() const { return EventProtocol::MSM_v1; }

void MSMProtocolHandler::registerHandlers(RuleEngine& engine) {
  auto register_handler = [&engine](EventType event_type, EventProtocol protocol_spec, EventHandler handler) {
    engine.registerRuleEventHandler(event_type, protocol_spec, std::move(handler));
  };

  register_handler(EventType::EPPS_TIMING, EventProtocol::MSM_v1, [&engine](const core::events::RuleEvent& event) {
    auto *notification_packet = std::get<messages::EPPSTimingNotification *>(event.payload);
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

  register_handler(EventType::EMIT_PHOTON_REQUEST, EventProtocol::Unknown, [&engine](const core::events::RuleEvent& event) {
    auto *pk = std::get<messages::EmitPhotonRequest *>(event.payload);
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

  register_handler(EventType::SINGLE_CLICK_RESULT, EventProtocol::MSM_v1, [&engine](const core::events::RuleEvent& event) {
    engine.handleSingleClickResult(std::get<messages::SingleClickResult *>(event.payload));
  });

  register_handler(EventType::MSM_RESULT, EventProtocol::MSM_v1, [&engine](const core::events::RuleEvent& event) {
    engine.handleMSMResult(std::get<messages::MSMResult *>(event.payload));
  });

  register_handler(EventType::STOP_EMITTING, EventProtocol::MSM_v1, [&engine](const core::events::RuleEvent& event) {
    engine.handleStopEmitting(std::get<messages::StopEmitting *>(event.payload));
  });
}

}  // namespace quisp::modules::handlers
