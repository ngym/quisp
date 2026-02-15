#include "MIMProtocolHandler.h"

#include <functional>
#include <utility>

#include "../RuleEngine.h"
#include "../RuleProtocolExecutionContext.h"
#include "messages/classical_messages.h"

namespace quisp::modules::handlers {

using EventType = core::events::RuleEventKind;
using EventProtocol = core::events::ProtocolType;
using EventHandler = quisp::modules::RuleEngine::RuleEventHandler;

core::events::ProtocolType MIMProtocolHandler::protocolSpec() const { return EventProtocol::MIM_v1; }

void MIMProtocolHandler::registerHandlers(RuleEngine& engine) {
  auto register_handler = [&engine](EventType event_type, EventProtocol protocol_spec, EventHandler handler) {
    engine.registerRuleEventHandler(event_type, protocol_spec, std::move(handler));
  };

  register_handler(EventType::BSM_RESULT, EventProtocol::MIM_v1, [&engine](const core::events::RuleEvent& event) {
    engine.protocolExecutionContext().handleLinkGenerationResult(std::get<messages::CombinedBSAresults *>(event.payload));
  });

  register_handler(EventType::BSM_TIMING, EventProtocol::MIM_v1, [&engine](const core::events::RuleEvent& event) {
    auto *notification_packet = std::get<messages::BSMTimingNotification *>(event.payload);
    auto type = notification_packet->getQnicType();
    auto qnic_index = notification_packet->getQnicIndex();
    engine.stopOnGoingPhotonEmission(type, qnic_index);
    engine.freeFailedEntanglementAttemptQubits(type, qnic_index);
    engine.schedulePhotonEmission(type, qnic_index, notification_packet);
  });
}

}  // namespace quisp::modules::handlers
