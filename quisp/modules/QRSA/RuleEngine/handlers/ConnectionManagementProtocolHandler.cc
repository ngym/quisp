#include "ConnectionManagementProtocolHandler.h"

#include <functional>
#include <nlohmann/json.hpp>
#include <utility>

#include "RuleEngine.h"
#include "messages/classical_messages.h"
#include "rules/RuleSet.h"

namespace quisp::modules::handlers {

using EventType = core::events::RuleEventType;
using EventProtocol = core::events::ProtocolSpec;
using EventHandler = quisp::modules::RuleEngine::RuleEventHandler;

core::events::ProtocolSpec ConnectionManagementProtocolHandler::protocolSpec() const {
  return EventProtocol::ConnectionManagement;
}

void ConnectionManagementProtocolHandler::registerHandlers(RuleEngine& engine) {
  auto register_handler = [&engine](EventType event_type, EventProtocol protocol_spec, EventHandler handler) {
    engine.registerRuleEventHandler(event_type, protocol_spec, std::move(handler));
  };

  const auto submit_forwarded_ruleset = [&engine](const std::string& serialized_ruleset) {
    rules::RuleSet ruleset(0, 0);
    ruleset.deserialize_json(nlohmann::json::parse(serialized_ruleset));
    engine.runtimes.submitRuleSet(ruleset.construct());
  };

  register_handler(EventType::RULESET_FORWARDING, EventProtocol::ConnectionManagement, [&engine, submit_forwarded_ruleset](const core::events::RuleEvent& event) {
    auto *pkt = std::get<messages::InternalRuleSetForwarding *>(event.payload);
    auto serialized_ruleset = pkt->getRuleSet().dump();
    submit_forwarded_ruleset(serialized_ruleset);
  });

  register_handler(EventType::LINK_TOMOGRAPHY_RULESET, EventProtocol::LinkTomography,
                   [&engine, submit_forwarded_ruleset](const core::events::RuleEvent& event) {
                     auto *pk = std::get<messages::LinkTomographyRuleSet *>(event.payload);
                     auto *ruleset = pk->getRuleSet();
                     engine.runtimes.submitRuleSet(ruleset->construct());
                   });

  register_handler(EventType::RULESET_FORWARDING_APPLICATION, EventProtocol::ConnectionManagement,
                   [&engine, submit_forwarded_ruleset](const core::events::RuleEvent& event) {
                     auto *pkt = std::get<messages::InternalRuleSetForwarding_Application *>(event.payload);
                     auto application_type = pkt->getApplication_type();
                     if (application_type != 0) {
                       return;
                     }
                     auto serialized_ruleset = pkt->getRuleSet().dump();
                     submit_forwarded_ruleset(serialized_ruleset);
                   });
}

}  // namespace quisp::modules::handlers
