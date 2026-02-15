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

  // Default execution registrations are keyed by (RuleEventType, ProtocolSpec),
  // where ProtocolSpec is protocol classification (MIM/MSM/Swapping/etc.) rather than link architecture naming.
  static void registerDefaults(RuleEngine& engine);
};

}  // namespace quisp::modules
