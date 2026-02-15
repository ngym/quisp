#include "PurificationProtocolHandler.h"

#include <functional>
#include <utility>

#include "../RuleEngine.h"
#include "../RuleProtocolExecutionContext.h"
#include "messages/purification_messages_m.h"

namespace quisp::modules::handlers {

using EventType = core::events::RuleEventKind;
using EventProtocol = core::events::ProtocolType;
using EventHandler = quisp::modules::RuleEngine::RuleEventHandler;

core::events::ProtocolType PurificationProtocolHandler::protocolSpec() const { return EventProtocol::Purification; }

void PurificationProtocolHandler::registerHandlers(RuleEngine& engine) {
  auto register_handler = [&engine](EventType event_type, EventProtocol protocol_spec, EventHandler handler) {
    engine.registerRuleEventHandler(event_type, protocol_spec, std::move(handler));
  };

  register_handler(EventType::PURIFICATION_RESULT, EventProtocol::Purification, [&engine](const core::events::RuleEvent& event) {
    engine.protocolExecutionContext().handlePurificationResult(std::get<messages::PurificationResult *>(event.payload));
  });
}

}  // namespace quisp::modules::handlers
