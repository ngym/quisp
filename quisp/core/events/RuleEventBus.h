#pragma once

#include <omnetpp/cmessage.h>
#include <omnetpp/simtime_t.h>

#include <functional>
#include <cstdint>
#include <optional>
#include <unordered_map>
#include <string>
#include <vector>
#include <variant>

#include "ExecutionPath.h"
#include "ProtocolSpec.h"

namespace quisp::messages {
class BSMTimingNotification;
class CombinedBSAresults;
class EPPSTimingNotification;
class EmitPhotonRequest;
class InternalRuleSetForwarding;
class InternalRuleSetForwarding_Application;
class LinkTomographyRuleSet;
class MSMResult;
class PurificationResult;
class SingleClickResult;
class StopEmitting;
class SwappingResult;
}  // namespace quisp::messages

namespace quisp::core::events {

enum class RuleEventChannel {
  UNKNOWN,
  EXTERNAL,
  INTERNAL_TIMER,
};

enum class RuleEventKind {
  UNKNOWN,
  BSM_RESULT,
  BSM_TIMING,
  EPPS_TIMING,
  EMIT_PHOTON_REQUEST,
  LINK_TOMOGRAPHY_RULESET,
  MSM_RESULT,
  PURIFICATION_RESULT,
  SINGLE_CLICK_RESULT,
  STOP_EMITTING,
  SWAPPING_RESULT,
  RULESET_FORWARDING,
  RULESET_FORWARDING_APPLICATION
};
// Kept for backward compatibility. New code should use RuleEventKind.
using RuleEventType = RuleEventKind;

inline std::string to_string(RuleEventKind event_type) {
  switch (event_type) {
    case RuleEventKind::BSM_RESULT:
      return "BSM_RESULT";
    case RuleEventKind::BSM_TIMING:
      return "BSM_TIMING";
    case RuleEventKind::EPPS_TIMING:
      return "EPPS_TIMING";
    case RuleEventKind::EMIT_PHOTON_REQUEST:
      return "EMIT_PHOTON_REQUEST";
    case RuleEventKind::LINK_TOMOGRAPHY_RULESET:
      return "LINK_TOMOGRAPHY_RULESET";
    case RuleEventKind::MSM_RESULT:
      return "MSM_RESULT";
    case RuleEventKind::PURIFICATION_RESULT:
      return "PURIFICATION_RESULT";
    case RuleEventKind::SINGLE_CLICK_RESULT:
      return "SINGLE_CLICK_RESULT";
    case RuleEventKind::STOP_EMITTING:
      return "STOP_EMITTING";
    case RuleEventKind::SWAPPING_RESULT:
      return "SWAPPING_RESULT";
    case RuleEventKind::RULESET_FORWARDING:
      return "RULESET_FORWARDING";
    case RuleEventKind::RULESET_FORWARDING_APPLICATION:
      return "RULESET_FORWARDING_APPLICATION";
    case RuleEventKind::UNKNOWN:
    default:
      return "UNKNOWN";
  }
}

using RuleEventPayload = std::variant<std::monostate, messages::BSMTimingNotification *, messages::CombinedBSAresults *,
                                     messages::EPPSTimingNotification *, messages::EmitPhotonRequest *,
                                     messages::InternalRuleSetForwarding *, messages::InternalRuleSetForwarding_Application *,
                                     messages::LinkTomographyRuleSet *, messages::MSMResult *, messages::PurificationResult *,
                                     messages::SingleClickResult *, messages::StopEmitting *, messages::SwappingResult *>;

struct RuleEvent {
  RuleEventKind type = RuleEventKind::UNKNOWN;
  RuleEventChannel channel = RuleEventChannel::UNKNOWN;
  bool keep_source = false;
  ::omnetpp::simtime_t time = SIMTIME_ZERO;
  int64_t event_number = 0;
  ProtocolType protocol_spec = ProtocolType::Unknown;
  ExecutionPath execution_path = ExecutionPath::Unknown;
  std::string protocol_raw_value = "";
  RuleEventPayload payload = std::monostate{};
  std::string msg_name = "";
  std::string msg_type = "";
};

class RuleEventBus {
 public:
  using RuleEventTranslator = std::function<std::optional<RuleEvent>(::omnetpp::cMessage *msg, ::omnetpp::simtime_t now)>;

  RuleEventBus();
  void registerTranslator(const std::string &message_class_name, RuleEventTranslator translator);
  RuleEvent toRuleEvent(::omnetpp::cMessage *msg, ::omnetpp::simtime_t now);
  void publish(::omnetpp::cMessage *msg, ::omnetpp::simtime_t now);
  void publish(const RuleEvent &event);
  std::vector<RuleEvent> drain(::omnetpp::simtime_t now);

 private:
  void registerDefaultTranslators();

  std::vector<RuleEvent> event_queue;
  std::unordered_map<std::string, RuleEventTranslator> translators;
};

}  // namespace quisp::core::events
