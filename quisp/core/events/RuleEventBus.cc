#include "RuleEventBus.h"

#include <algorithm>
#include <cstdint>
#include <string>

#include "messages/classical_messages.h"
#include "omnetpp/csimulation.h"

namespace quisp::core::events {

using namespace messages;

namespace {
int64_t getEventNumberOrFallback() {
  if (auto sim = getSimulation()) {
    return sim->getEventNumber();
  }
  static int64_t fallback_event_number = 0;
  return fallback_event_number++;
}

template <typename MessageT>
RuleEvent makeRuleEvent(RuleEventType type, MessageT *msg, ::omnetpp::simtime_t now, bool keep_source_override = false) {
  const auto is_internal = msg != nullptr && msg->isSelfMessage();
  return RuleEvent{type,
                   is_internal ? RuleEventChannel::INTERNAL_TIMER : RuleEventChannel::EXTERNAL,
                   keep_source_override || is_internal,
                   now,
                   getEventNumberOrFallback(),
                   static_cast<MessageT *>(msg),
                   msg == nullptr ? "" : msg->getFullName(),
                   msg == nullptr ? "" : msg->getClassName()};
}

std::optional<RuleEvent> translateByType(::omnetpp::cMessage *msg, ::omnetpp::simtime_t now) {
  if (dynamic_cast<CombinedBSAresults *>(msg) != nullptr) {
    return makeRuleEvent(RuleEventType::BSM_RESULT, dynamic_cast<CombinedBSAresults *>(msg), now);
  }
  if (dynamic_cast<BSMTimingNotification *>(msg) != nullptr) {
    return makeRuleEvent(RuleEventType::BSM_TIMING, dynamic_cast<BSMTimingNotification *>(msg), now);
  }
  if (dynamic_cast<EPPSTimingNotification *>(msg) != nullptr) {
    return makeRuleEvent(RuleEventType::EPPS_TIMING, dynamic_cast<EPPSTimingNotification *>(msg), now);
  }
  if (dynamic_cast<EmitPhotonRequest *>(msg) != nullptr) {
    return makeRuleEvent(RuleEventType::EMIT_PHOTON_REQUEST, dynamic_cast<EmitPhotonRequest *>(msg), now, true);
  }
  if (dynamic_cast<LinkTomographyRuleSet *>(msg) != nullptr) {
    return makeRuleEvent(RuleEventType::LINK_TOMOGRAPHY_RULESET, dynamic_cast<LinkTomographyRuleSet *>(msg), now);
  }
  if (dynamic_cast<MSMResult *>(msg) != nullptr) {
    return makeRuleEvent(RuleEventType::MSM_RESULT, dynamic_cast<MSMResult *>(msg), now);
  }
  if (dynamic_cast<PurificationResult *>(msg) != nullptr) {
    return makeRuleEvent(RuleEventType::PURIFICATION_RESULT, dynamic_cast<PurificationResult *>(msg), now);
  }
  if (dynamic_cast<SingleClickResult *>(msg) != nullptr) {
    return makeRuleEvent(RuleEventType::SINGLE_CLICK_RESULT, dynamic_cast<SingleClickResult *>(msg), now);
  }
  if (dynamic_cast<StopEmitting *>(msg) != nullptr) {
    return makeRuleEvent(RuleEventType::STOP_EMITTING, dynamic_cast<StopEmitting *>(msg), now);
  }
  if (dynamic_cast<SwappingResult *>(msg) != nullptr) {
    return makeRuleEvent(RuleEventType::SWAPPING_RESULT, dynamic_cast<SwappingResult *>(msg), now);
  }
  if (dynamic_cast<InternalRuleSetForwarding *>(msg) != nullptr) {
    return makeRuleEvent(RuleEventType::RULESET_FORWARDING, dynamic_cast<InternalRuleSetForwarding *>(msg), now);
  }
  if (dynamic_cast<InternalRuleSetForwarding_Application *>(msg) != nullptr) {
    return makeRuleEvent(RuleEventType::RULESET_FORWARDING_APPLICATION, dynamic_cast<InternalRuleSetForwarding_Application *>(msg), now);
  }
  return std::nullopt;
}

template <typename MessageT>
std::string messageClassName() {
  return MessageT().getClassName();
}

template <typename MessageT>
RuleEventBus::RuleEventTranslator translatorFor(RuleEventType event_type, bool keep_source = false) {
  return [event_type, keep_source](::omnetpp::cMessage *msg, ::omnetpp::simtime_t now) -> std::optional<RuleEvent> {
    if (msg == nullptr) {
      return std::nullopt;
    }
    return std::optional{makeRuleEvent(event_type, static_cast<MessageT *>(msg), now, keep_source)};
  };
}

RuleEvent makeUnknownRuleEvent(::omnetpp::cMessage *msg, omnetpp::simtime_t now) {
  auto type_name = msg == nullptr ? "omnetpp::cMessage" : msg->getClassName();
  auto full_name = msg == nullptr ? "null" : msg->getFullName();
  return RuleEvent{
      RuleEventType::UNKNOWN,
      msg == nullptr ? RuleEventChannel::UNKNOWN : (msg->isSelfMessage() ? RuleEventChannel::INTERNAL_TIMER : RuleEventChannel::EXTERNAL),
      msg != nullptr && msg->isSelfMessage(),
      now,
      getEventNumberOrFallback(),
      std::monostate{},
      full_name,
      type_name,
  };
}
}  // namespace

RuleEventBus::RuleEventBus() {
  registerDefaultTranslators();
}

void RuleEventBus::registerTranslator(const std::string &message_class_name, RuleEventTranslator translator) {
  translators[message_class_name] = std::move(translator);
}

void RuleEventBus::registerDefaultTranslators() {
  registerTranslator(messageClassName<CombinedBSAresults>(),
                    translatorFor<CombinedBSAresults>(RuleEventType::BSM_RESULT));
  registerTranslator(messageClassName<BSMTimingNotification>(),
                    translatorFor<BSMTimingNotification>(RuleEventType::BSM_TIMING));
  registerTranslator(messageClassName<EPPSTimingNotification>(),
                    translatorFor<EPPSTimingNotification>(RuleEventType::EPPS_TIMING));
  registerTranslator(messageClassName<EmitPhotonRequest>(),
                    translatorFor<EmitPhotonRequest>(RuleEventType::EMIT_PHOTON_REQUEST, true));
  registerTranslator(messageClassName<LinkTomographyRuleSet>(),
                    translatorFor<LinkTomographyRuleSet>(RuleEventType::LINK_TOMOGRAPHY_RULESET));
  registerTranslator(messageClassName<MSMResult>(),
                    translatorFor<MSMResult>(RuleEventType::MSM_RESULT));
  registerTranslator(messageClassName<PurificationResult>(),
                    translatorFor<PurificationResult>(RuleEventType::PURIFICATION_RESULT));
  registerTranslator(messageClassName<SingleClickResult>(),
                    translatorFor<SingleClickResult>(RuleEventType::SINGLE_CLICK_RESULT));
  registerTranslator(messageClassName<InternalRuleSetForwarding>(),
                    translatorFor<InternalRuleSetForwarding>(RuleEventType::RULESET_FORWARDING));
  registerTranslator(messageClassName<InternalRuleSetForwarding_Application>(),
                    translatorFor<InternalRuleSetForwarding_Application>(RuleEventType::RULESET_FORWARDING_APPLICATION));
  registerTranslator(messageClassName<StopEmitting>(),
                    translatorFor<StopEmitting>(RuleEventType::STOP_EMITTING));
  registerTranslator(messageClassName<SwappingResult>(),
                    translatorFor<SwappingResult>(RuleEventType::SWAPPING_RESULT));
}

RuleEvent RuleEventBus::toRuleEvent(::omnetpp::cMessage *msg, ::omnetpp::simtime_t now) {
  if (msg == nullptr) {
    return makeUnknownRuleEvent(nullptr, now);
  }
  if (auto translated = translateByType(msg, now)) {
    return *translated;
  }
  auto it = translators.find(msg->getClassName());
  if (it != translators.end()) {
    if (auto translated = it->second(msg, now)) {
      return *translated;
    }
  }
  return makeUnknownRuleEvent(msg, now);
}

void RuleEventBus::publish(::omnetpp::cMessage *msg, ::omnetpp::simtime_t now) {
  publish(toRuleEvent(msg, now));
}

void RuleEventBus::publish(const RuleEvent &event) {
  event_queue.push_back(event);
}

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
