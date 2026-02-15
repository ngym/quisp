#include "ConnectionManagementProtocolHandler.h"

#include <functional>
#include <utility>

#include "../RuleEngine.h"
#include "../RuleProtocolExecutionContext.h"
#include "messages/classical_messages.h"

namespace quisp::modules::handlers {

using EventType = core::events::RuleEventKind;
using EventProtocol = core::events::ProtocolType;
using EventHandler = quisp::modules::RuleEngine::RuleEventHandler;

core::events::ProtocolType ConnectionManagementProtocolHandler::protocolSpec() const {
  return EventProtocol::ConnectionManagement;
}

void ConnectionManagementProtocolHandler::registerHandlers(RuleEngine& engine) {
  auto register_handler = [&engine](EventType event_type, EventProtocol protocol_spec, EventHandler handler) {
    engine.registerRuleEventHandler(event_type, protocol_spec, std::move(handler));
  };

  register_handler(
      EventType::RULESET_FORWARDING, EventProtocol::ConnectionManagement, [&engine](const core::events::RuleEvent& event) {
    auto *pkt = std::get<messages::InternalRuleSetForwarding *>(event.payload);
    engine.protocolExecutionContext().handleRuleSetForwarding(pkt);
  });

  register_handler(EventType::LINK_TOMOGRAPHY_RULESET, EventProtocol::LinkTomography,
                   [&engine](const core::events::RuleEvent& event) {
                     auto *pk = std::get<messages::LinkTomographyRuleSet *>(event.payload);
                     engine.protocolExecutionContext().handleLinkTomographyRuleSet(pk);
                   });

  register_handler(EventType::RULESET_FORWARDING_APPLICATION, EventProtocol::ConnectionManagement,
                   [&engine](const core::events::RuleEvent& event) {
                     auto *pkt = std::get<messages::InternalRuleSetForwarding_Application *>(event.payload);
                     engine.protocolExecutionContext().handleRuleSetForwardingApplication(pkt);
                   });
}

}  // namespace quisp::modules::handlers
