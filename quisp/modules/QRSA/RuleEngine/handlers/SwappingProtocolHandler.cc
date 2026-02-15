#include "SwappingProtocolHandler.h"

#include <functional>
#include <utility>

#include "../RuleEngine.h"
#include "messages/link_generation_messages_m.h"

namespace quisp::modules::handlers {

using EventType = core::events::RuleEventType;
using EventProtocol = core::events::ProtocolSpec;
using EventHandler = quisp::modules::RuleEngine::RuleEventHandler;

core::events::ProtocolSpec SwappingProtocolHandler::protocolSpec() const { return EventProtocol::Swapping; }

void SwappingProtocolHandler::registerHandlers(RuleEngine& engine) {
  auto register_handler = [&engine](EventType event_type, EventProtocol protocol_spec, EventHandler handler) {
    engine.registerRuleEventHandler(event_type, protocol_spec, std::move(handler));
  };

  register_handler(EventType::SWAPPING_RESULT, EventProtocol::Swapping, [&engine](const core::events::RuleEvent& event) {
    engine.handleSwappingResult(std::get<messages::SwappingResult *>(event.payload));
  });
}

}  // namespace quisp::modules::handlers
