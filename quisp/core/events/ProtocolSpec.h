#pragma once

#include <string>

namespace quisp::core::events {

enum class ProtocolSpec {
  Unknown,
  MIM_v1,
  MSM_v1,
  Purification,
  Swapping,
  LinkTomography,
  ConnectionManagement,
  Maintenance,
};

inline std::string to_string(ProtocolSpec protocol) {
  switch (protocol) {
    case ProtocolSpec::MIM_v1:
      return "MIM Protocol v1";
    case ProtocolSpec::MSM_v1:
      return "MSM Protocol v1";
    case ProtocolSpec::Purification:
      return "Purification";
    case ProtocolSpec::Swapping:
      return "Swapping";
    case ProtocolSpec::LinkTomography:
      return "LinkTomography";
    case ProtocolSpec::ConnectionManagement:
      return "ConnectionManagement";
    case ProtocolSpec::Maintenance:
      return "Maintenance";
    case ProtocolSpec::Unknown:
    default:
      return "Unknown";
  }
}

inline ProtocolSpec protocol_from_int(int protocol_hint) {
  // Purification protocol identifiers are small non-negative enum values (see rules::PurType).
  if (protocol_hint >= 0 && protocol_hint <= 10) {
    return ProtocolSpec::Purification;
  }
  return ProtocolSpec::Unknown;
}

inline ProtocolSpec protocol_from_message_hint(int application_type) {
  return application_type == 0 ? ProtocolSpec::ConnectionManagement : ProtocolSpec::Unknown;
}

}  // namespace quisp::core::events
