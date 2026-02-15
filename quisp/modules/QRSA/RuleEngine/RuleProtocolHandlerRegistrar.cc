#include "RuleProtocolHandlerRegistrar.h"

#include "handlers/ConnectionManagementProtocolHandler.h"
#include "handlers/MIMProtocolHandler.h"
#include "handlers/MSMProtocolHandler.h"
#include "handlers/PurificationProtocolHandler.h"
#include "handlers/SwappingProtocolHandler.h"

namespace quisp::modules {

using namespace core::events;
using EventType = RuleEventType;
using EventProtocol = ProtocolSpec;

void RuleProtocolHandlerRegistrar::registerDefaults(RuleEngine& engine) {
  MIMProtocolHandler mim_protocol_handler;
  mim_protocol_handler.registerHandlers(engine);

  MSMProtocolHandler msm_protocol_handler;
  msm_protocol_handler.registerHandlers(engine);

  PurificationProtocolHandler purification_protocol_handler;
  purification_protocol_handler.registerHandlers(engine);

  SwappingProtocolHandler swapping_protocol_handler;
  swapping_protocol_handler.registerHandlers(engine);

  ConnectionManagementProtocolHandler connection_management_protocol_handler;
  connection_management_protocol_handler.registerHandlers(engine);

  engine.registerRuleEventHandler(EventType::UNKNOWN, EventProtocol::Unknown, [&engine](const RuleEvent& event) {
    (void)event;
    engine.logUnknownRuleEvent(event);
  });
}

}  // namespace quisp::modules
