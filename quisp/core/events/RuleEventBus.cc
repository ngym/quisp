#include "RuleEventBus.h"

#include <algorithm>

#include "messages/classical_messages.h"
#include "omnetpp/csimulation.h"

namespace quisp::core::events {

using namespace messages;

void RuleEventBus::publish(::omnetpp::cMessage *msg, ::omnetpp::simtime_t now) {
  if (msg == nullptr) {
    return;
  }
  RuleEvent event;
  event.time = now;
  event.event_number = getSimulation()->getEventNumber();

  if (auto *pkt = dynamic_cast<CombinedBSAresults *>(msg)) {
    event.type = RuleEventType::BSM_RESULT;
    event.payload = pkt;
  } else if (auto *notification_packet = dynamic_cast<BSMTimingNotification *>(msg)) {
    event.type = RuleEventType::BSM_TIMING;
    event.payload = notification_packet;
  } else if (auto *notification_packet = dynamic_cast<EPPSTimingNotification *>(msg)) {
    event.type = RuleEventType::EPPS_TIMING;
    event.payload = notification_packet;
  } else if (auto *pk = dynamic_cast<EmitPhotonRequest *>(msg)) {
    event.type = RuleEventType::EMIT_PHOTON_REQUEST;
    event.payload = pk;
  } else if (auto *pk = dynamic_cast<LinkTomographyRuleSet *>(msg)) {
    event.type = RuleEventType::LINK_TOMOGRAPHY_RULESET;
    event.payload = pk;
  } else if (auto *pk = dynamic_cast<MSMResult *>(msg)) {
    event.type = RuleEventType::MSM_RESULT;
    event.payload = pk;
  } else if (auto *pk = dynamic_cast<PurificationResult *>(msg)) {
    event.type = RuleEventType::PURIFICATION_RESULT;
    event.payload = pk;
  } else if (auto *pkt = dynamic_cast<SingleClickResult *>(msg)) {
    event.type = RuleEventType::SINGLE_CLICK_RESULT;
    event.payload = pkt;
  } else if (auto *pkt = dynamic_cast<InternalRuleSetForwarding *>(msg)) {
    event.type = RuleEventType::RULESET_FORWARDING;
    event.payload = pkt;
  } else if (auto *pkt = dynamic_cast<InternalRuleSetForwarding_Application *>(msg)) {
    event.type = RuleEventType::RULESET_FORWARDING_APPLICATION;
    event.payload = pkt;
  } else if (auto *pkt = dynamic_cast<StopEmitting *>(msg)) {
    event.type = RuleEventType::STOP_EMITTING;
    event.payload = pkt;
  } else if (auto *pkt = dynamic_cast<SwappingResult *>(msg)) {
    event.type = RuleEventType::SWAPPING_RESULT;
    event.payload = pkt;
  }
  publish(event);
}

void RuleEventBus::publish(const RuleEvent &event) { event_queue.push_back(event); }

std::vector<RuleEvent> RuleEventBus::drain(::omnetpp::simtime_t now) {
  std::sort(event_queue.begin(), event_queue.end(),
            [](const RuleEvent &lhs, const RuleEvent &rhs) {
              if (lhs.time != rhs.time) {
                return lhs.time < rhs.time;
              }
              return lhs.event_number < rhs.event_number;
            });
  std::vector<RuleEvent> events;
  auto it = event_queue.begin();
  for (; it != event_queue.end() && it->time <= now; ++it) {
    events.push_back(*it);
  }
  event_queue.erase(event_queue.begin(), it);
  return events;
}

}  // namespace quisp::core::events
