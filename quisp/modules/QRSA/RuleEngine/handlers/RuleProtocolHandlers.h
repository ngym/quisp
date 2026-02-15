#pragma once

#include <memory>
#include <vector>

#include "ConnectionManagementProtocolHandler.h"
#include "MIMProtocolHandler.h"
#include "MSMProtocolHandler.h"
#include "PurificationProtocolHandler.h"
#include "SwappingProtocolHandler.h"

namespace quisp::modules::handlers {

using ProtocolHandlerPtr = std::unique_ptr<IRuleProtocolHandler>;

inline std::vector<ProtocolHandlerPtr> createDefaultProtocolHandlers() {
  std::vector<ProtocolHandlerPtr> handlers;
  handlers.reserve(5);
  handlers.push_back(std::make_unique<MIMProtocolHandler>());
  handlers.push_back(std::make_unique<MSMProtocolHandler>());
  handlers.push_back(std::make_unique<PurificationProtocolHandler>());
  handlers.push_back(std::make_unique<SwappingProtocolHandler>());
  handlers.push_back(std::make_unique<ConnectionManagementProtocolHandler>());
  return handlers;
}

}  // namespace quisp::modules::handlers
