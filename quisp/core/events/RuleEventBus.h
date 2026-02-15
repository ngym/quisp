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

enum class RuleEventType {
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

using RuleEventPayload = std::variant<std::monostate, messages::BSMTimingNotification *, messages::CombinedBSAresults *,
                                     messages::EPPSTimingNotification *, messages::EmitPhotonRequest *,
                                     messages::InternalRuleSetForwarding *, messages::InternalRuleSetForwarding_Application *,
                                     messages::LinkTomographyRuleSet *, messages::MSMResult *, messages::PurificationResult *,
                                     messages::SingleClickResult *, messages::StopEmitting *, messages::SwappingResult *>;

struct RuleEvent {
  RuleEventType type = RuleEventType::UNKNOWN;
  RuleEventChannel channel = RuleEventChannel::UNKNOWN;
  bool keep_source = false;
  ::omnetpp::simtime_t time = SIMTIME_ZERO;
  int64_t event_number = 0;
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
