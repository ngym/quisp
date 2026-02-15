#pragma once

#include "IRuleProtocolHandler.h"

namespace quisp::modules {
class RuleEngine;
}

namespace quisp::modules::handlers {

class PurificationProtocolHandler : public IRuleProtocolHandler {
 public:
  core::events::ProtocolSpec protocolSpec() const override;
  void registerHandlers(RuleEngine& engine) override;
};

}  // namespace quisp::modules::handlers
