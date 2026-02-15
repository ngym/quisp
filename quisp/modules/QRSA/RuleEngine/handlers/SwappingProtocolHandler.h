#pragma once

#include "../IRuleProtocolHandler.h"

namespace quisp::modules {
class RuleEngine;
}

namespace quisp::modules::handlers {

class SwappingProtocolHandler : public IRuleProtocolHandler {
 public:
  core::events::ProtocolType protocolSpec() const override;
  void registerHandlers(RuleEngine& engine) override;
};

}  // namespace quisp::modules::handlers
