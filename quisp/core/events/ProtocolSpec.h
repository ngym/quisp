#pragma once

#include <string>

namespace quisp::core::events {

enum class ProtocolType {
  Unknown,
  MIM_v1,
  MSM_v1,
  Purification,
  Swapping,
  LinkTomography,
  ConnectionManagement,
  Maintenance,
};

// Kept for backward compatibility. New code should use ProtocolType.
using ProtocolSpec = ProtocolType;

inline std::string to_string(ProtocolType protocol) {
  switch (protocol) {
    case ProtocolType::MIM_v1:
      return "MIM Protocol v1";
    case ProtocolType::MSM_v1:
      return "MSM Protocol v1";
    case ProtocolType::Purification:
      return "Purification";
    case ProtocolType::Swapping:
      return "Swapping";
    case ProtocolType::LinkTomography:
      return "LinkTomography";
    case ProtocolType::ConnectionManagement:
      return "ConnectionManagement";
    case ProtocolType::Maintenance:
      return "Maintenance";
    case ProtocolType::Unknown:
    default:
      return "Unknown";
  }
}

inline ProtocolType protocol_from_int(int protocol_hint) {
  // Purification protocol identifiers are small non-negative enum values (see rules::PurType).
  if (protocol_hint >= 0 && protocol_hint <= 10) {
    return ProtocolType::Purification;
  }
  return ProtocolType::Unknown;
}

inline ProtocolType protocol_from_message_hint(int application_type) {
  return application_type == 0 ? ProtocolType::ConnectionManagement : ProtocolType::Unknown;
}

}  // namespace quisp::core::events
