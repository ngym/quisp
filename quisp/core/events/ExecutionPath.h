#pragma once

#include <string>

namespace quisp::core::events {

enum class ExecutionPath {
  Unknown,
  EntanglementLifecycle,
  ConnectionControl,
  Forwarding,
  Maintenance,
};

inline std::string to_string(ExecutionPath execution_path) {
  switch (execution_path) {
    case ExecutionPath::EntanglementLifecycle:
      return "EntanglementLifecycle";
    case ExecutionPath::ConnectionControl:
      return "ConnectionControl";
    case ExecutionPath::Forwarding:
      return "Forwarding";
    case ExecutionPath::Maintenance:
      return "Maintenance";
    case ExecutionPath::Unknown:
    default:
      return "Unknown";
  }
}

}  // namespace quisp::core::events
