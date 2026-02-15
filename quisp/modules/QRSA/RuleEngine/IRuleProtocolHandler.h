#pragma once

#include "core/events/ProtocolSpec.h"

namespace quisp::modules {
class RuleEngine;

namespace handlers {

class IRuleProtocolHandler {
 public:
  virtual ~IRuleProtocolHandler() = default;
  virtual core::events::ProtocolSpec protocolSpec() const = 0;
  virtual void registerHandlers(RuleEngine& engine) = 0;
};

}  // namespace handlers
}  // namespace quisp::modules
