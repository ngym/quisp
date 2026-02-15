#pragma once

#include <omnetpp/cmessage.h>
#include <omnetpp/simtime_t.h>

#include <cstdint>
#include <variant>
#include <vector>

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
  ::omnetpp::simtime_t time = SIMTIME_ZERO;
  int64_t event_number = 0;
  RuleEventPayload payload = std::monostate{};
};

class RuleEventBus {
 public:
  void publish(::omnetpp::cMessage *msg, ::omnetpp::simtime_t now);
  void publish(const RuleEvent &event);
  std::vector<RuleEvent> drain(::omnetpp::simtime_t now);

 private:
  std::vector<RuleEvent> event_queue;
};

}  // namespace quisp::core::events
