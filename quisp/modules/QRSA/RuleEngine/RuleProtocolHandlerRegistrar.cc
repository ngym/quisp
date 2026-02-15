#include "RuleProtocolHandlerRegistrar.h"

#include "handlers/RuleProtocolHandlers.h"

namespace quisp::modules {

using namespace core::events;
using EventType = RuleEventType;
using EventProtocol = ProtocolSpec;

void RuleProtocolHandlerRegistrar::registerDefaults(RuleEngine& engine) {
  for (const auto& handler : handlers::createDefaultProtocolHandlers()) {
    handler->registerHandlers(engine);
  }
  engine.registerRuleEventHandler(EventType::UNKNOWN, EventProtocol::Unknown, [&engine](const RuleEvent& event) {
    (void)event;
    engine.logUnknownRuleEvent(event);
  });
}

}  // namespace quisp::modules
