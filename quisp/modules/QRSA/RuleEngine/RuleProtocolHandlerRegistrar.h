#pragma once

namespace omnetpp {
class cMessage;
}

namespace quisp::modules {

class RuleEngine;

class RuleProtocolHandlerRegistrar {
 public:
  RuleProtocolHandlerRegistrar() = delete;
  RuleProtocolHandlerRegistrar(const RuleProtocolHandlerRegistrar&) = delete;
  RuleProtocolHandlerRegistrar& operator=(const RuleProtocolHandlerRegistrar&) = delete;
  RuleProtocolHandlerRegistrar(RuleProtocolHandlerRegistrar&&) = delete;
  RuleProtocolHandlerRegistrar& operator=(RuleProtocolHandlerRegistrar&&) = delete;

  // Default execution registrations are keyed by (RuleEventKind, ProtocolType),
  // where ProtocolType is protocol classification (MIM Protocol v1/MSM Protocol v1/etc.),
  // loaded from handlers::createDefaultProtocolHandlers().
  static void registerDefaults(RuleEngine& engine);
};

}  // namespace quisp::modules
