#include "RuleEventBus.h"

#include <algorithm>
#include <cstdint>
#include <string>
#include <typeinfo>
#include <utility>

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

ExecutionPath executionPathFromType(RuleEventKind type) {
  if (type == RuleEventKind::RULESET_FORWARDING || type == RuleEventKind::RULESET_FORWARDING_APPLICATION) {
    return ExecutionPath::Forwarding;
  }
  return ExecutionPath::EntanglementLifecycle;
}

ProtocolType protocolFromEmitPhotonRequest(const EmitPhotonRequest *msg) {
  if (msg == nullptr || !msg->isMSM()) {
    return ProtocolType::MIM_v1;
  }
  return ProtocolType::MSM_v1;
}

template <typename MessageT>
RuleEvent makeRuleEvent(RuleEventKind type, MessageT *msg, ::omnetpp::simtime_t now, bool keep_source_override, ProtocolType protocol_spec,
                        ExecutionPath execution_path, std::string protocol_raw_value = "") {
  const auto is_internal = msg != nullptr && msg->isSelfMessage();
  std::string full_name = msg == nullptr ? "" : msg->getFullName();
  const auto msg_name = full_name.empty() ? (msg == nullptr ? "" : msg->getClassName()) : full_name;
  return RuleEvent{type,
                   is_internal ? RuleEventChannel::INTERNAL_TIMER : RuleEventChannel::EXTERNAL,
                   keep_source_override || is_internal,
                   now,
                   getEventNumberOrFallback(),
                   protocol_spec,
                   execution_path,
                   std::move(protocol_raw_value),
                   static_cast<MessageT *>(msg),
                   msg_name,
                   msg == nullptr ? "" : msg->getClassName()};
}

std::optional<RuleEvent> translateByType(::omnetpp::cMessage *msg, ::omnetpp::simtime_t now) {
  if (dynamic_cast<CombinedBSAresults *>(msg) != nullptr) {
    return makeRuleEvent(RuleEventKind::BSM_RESULT, dynamic_cast<CombinedBSAresults *>(msg), now, false, ProtocolType::MIM_v1,
                         executionPathFromType(RuleEventKind::BSM_RESULT));
  }
  if (dynamic_cast<BSMTimingNotification *>(msg) != nullptr) {
    return makeRuleEvent(RuleEventKind::BSM_TIMING, dynamic_cast<BSMTimingNotification *>(msg), now, false, ProtocolType::MIM_v1,
                         executionPathFromType(RuleEventKind::BSM_TIMING));
  }
  if (dynamic_cast<EPPSTimingNotification *>(msg) != nullptr) {
    return makeRuleEvent(RuleEventKind::EPPS_TIMING, dynamic_cast<EPPSTimingNotification *>(msg), now, false, ProtocolType::MSM_v1,
                         executionPathFromType(RuleEventKind::EPPS_TIMING));
  }
  if (dynamic_cast<EmitPhotonRequest *>(msg) != nullptr) {
    auto *emit_request = dynamic_cast<EmitPhotonRequest *>(msg);
    return makeRuleEvent(RuleEventKind::EMIT_PHOTON_REQUEST, emit_request, now, true, protocolFromEmitPhotonRequest(emit_request),
                         executionPathFromType(RuleEventKind::EMIT_PHOTON_REQUEST));
  }
  if (dynamic_cast<LinkTomographyRuleSet *>(msg) != nullptr) {
    return makeRuleEvent(RuleEventKind::LINK_TOMOGRAPHY_RULESET, dynamic_cast<LinkTomographyRuleSet *>(msg), now, false,
                         ProtocolType::LinkTomography, executionPathFromType(RuleEventKind::LINK_TOMOGRAPHY_RULESET));
  }
  if (dynamic_cast<MSMResult *>(msg) != nullptr) {
    return makeRuleEvent(RuleEventKind::MSM_RESULT, dynamic_cast<MSMResult *>(msg), now, false, ProtocolType::MSM_v1,
                         executionPathFromType(RuleEventKind::MSM_RESULT));
  }
  if (dynamic_cast<PurificationResult *>(msg) != nullptr) {
    auto *pkt = dynamic_cast<PurificationResult *>(msg);
    const auto protocol = protocol_from_int(pkt->getProtocol());
    auto protocol_raw_value = protocol == ProtocolType::Unknown ? std::to_string(pkt->getProtocol()) : "";
    return makeRuleEvent(RuleEventKind::PURIFICATION_RESULT, pkt, now, false, protocol, executionPathFromType(RuleEventKind::PURIFICATION_RESULT),
                         std::move(protocol_raw_value));
  }
  if (dynamic_cast<SingleClickResult *>(msg) != nullptr) {
    return makeRuleEvent(RuleEventKind::SINGLE_CLICK_RESULT, dynamic_cast<SingleClickResult *>(msg), now, false, ProtocolType::MSM_v1,
                         executionPathFromType(RuleEventKind::SINGLE_CLICK_RESULT));
  }
  if (dynamic_cast<StopEmitting *>(msg) != nullptr) {
    return makeRuleEvent(RuleEventKind::STOP_EMITTING, dynamic_cast<StopEmitting *>(msg), now, false, ProtocolType::MSM_v1,
                         executionPathFromType(RuleEventKind::STOP_EMITTING));
  }
  if (dynamic_cast<SwappingResult *>(msg) != nullptr) {
    return makeRuleEvent(RuleEventKind::SWAPPING_RESULT, dynamic_cast<SwappingResult *>(msg), now, false, ProtocolType::Swapping,
                         executionPathFromType(RuleEventKind::SWAPPING_RESULT));
  }
  if (dynamic_cast<InternalRuleSetForwarding *>(msg) != nullptr) {
    return makeRuleEvent(RuleEventKind::RULESET_FORWARDING, dynamic_cast<InternalRuleSetForwarding *>(msg), now, false,
                         ProtocolType::ConnectionManagement, executionPathFromType(RuleEventKind::RULESET_FORWARDING));
  }
  if (dynamic_cast<InternalRuleSetForwarding_Application *>(msg) != nullptr) {
    auto *pkt = dynamic_cast<InternalRuleSetForwarding_Application *>(msg);
    const auto protocol = protocol_from_message_hint(pkt->getApplication_type());
    auto protocol_raw_value = protocol == ProtocolType::Unknown ? std::to_string(pkt->getApplication_type()) : "";
    return makeRuleEvent(RuleEventKind::RULESET_FORWARDING_APPLICATION, pkt, now, false, protocol,
                         executionPathFromType(RuleEventKind::RULESET_FORWARDING_APPLICATION), std::move(protocol_raw_value));
  }
  return std::nullopt;
}

template <typename MessageT>
std::string messageClassName() {
  return omnetpp::opp_typename(typeid(MessageT));
}

template <typename MessageT>
RuleEventBus::RuleEventTranslator translatorFor(RuleEventKind event_type, ProtocolType protocol_spec, ExecutionPath execution_path, bool keep_source = false) {
  return [event_type, protocol_spec, execution_path, keep_source](::omnetpp::cMessage *msg, ::omnetpp::simtime_t now) -> std::optional<RuleEvent> {
    if (msg == nullptr) {
      return std::nullopt;
    }
    return std::optional{makeRuleEvent(event_type, static_cast<MessageT *>(msg), now, keep_source, protocol_spec, execution_path)};
  };
}

RuleEvent makeUnknownRuleEvent(::omnetpp::cMessage *msg, omnetpp::simtime_t now) {
  auto type_name = msg == nullptr ? "omnetpp::cMessage" : msg->getClassName();
  auto full_name = msg == nullptr ? "null" : msg->getFullName();
  auto protocol_raw_value = msg == nullptr ? "" : msg->getClassName();
  return RuleEvent{
      RuleEventKind::UNKNOWN,
      msg == nullptr ? RuleEventChannel::UNKNOWN : (msg->isSelfMessage() ? RuleEventChannel::INTERNAL_TIMER : RuleEventChannel::EXTERNAL),
      msg != nullptr && msg->isSelfMessage(),
      now,
      getEventNumberOrFallback(),
      ProtocolType::Unknown,
      ExecutionPath::Unknown,
      protocol_raw_value,
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
                    translatorFor<CombinedBSAresults>(RuleEventKind::BSM_RESULT, ProtocolType::MIM_v1, executionPathFromType(RuleEventKind::BSM_RESULT)));
  registerTranslator(messageClassName<BSMTimingNotification>(),
                    translatorFor<BSMTimingNotification>(RuleEventKind::BSM_TIMING, ProtocolType::MIM_v1,
                                                         executionPathFromType(RuleEventKind::BSM_TIMING)));
  registerTranslator(messageClassName<EPPSTimingNotification>(),
                    translatorFor<EPPSTimingNotification>(RuleEventKind::EPPS_TIMING, ProtocolType::MSM_v1,
                                                         executionPathFromType(RuleEventKind::EPPS_TIMING)));
  registerTranslator(
      messageClassName<EmitPhotonRequest>(),
      [](::omnetpp::cMessage *msg, ::omnetpp::simtime_t now) -> std::optional<RuleEvent> {
        if (auto *emit_request = dynamic_cast<EmitPhotonRequest *>(msg)) {
          return std::optional{
              makeRuleEvent(RuleEventKind::EMIT_PHOTON_REQUEST, emit_request, now, true, protocolFromEmitPhotonRequest(emit_request),
                           executionPathFromType(RuleEventKind::EMIT_PHOTON_REQUEST))};
        }
        return std::nullopt;
      });
  registerTranslator(messageClassName<LinkTomographyRuleSet>(),
                    translatorFor<LinkTomographyRuleSet>(RuleEventKind::LINK_TOMOGRAPHY_RULESET, ProtocolType::LinkTomography,
                                                         executionPathFromType(RuleEventKind::LINK_TOMOGRAPHY_RULESET)));
  registerTranslator(messageClassName<MSMResult>(),
                    translatorFor<MSMResult>(RuleEventKind::MSM_RESULT, ProtocolType::MSM_v1,
                                              executionPathFromType(RuleEventKind::MSM_RESULT)));
  registerTranslator(messageClassName<PurificationResult>(),
                    translatorFor<PurificationResult>(RuleEventKind::PURIFICATION_RESULT, ProtocolType::Purification,
                                                     executionPathFromType(RuleEventKind::PURIFICATION_RESULT)));
  registerTranslator(messageClassName<SingleClickResult>(),
                    translatorFor<SingleClickResult>(RuleEventKind::SINGLE_CLICK_RESULT, ProtocolType::MSM_v1,
                                                     executionPathFromType(RuleEventKind::SINGLE_CLICK_RESULT)));
  registerTranslator(messageClassName<InternalRuleSetForwarding>(),
                    translatorFor<InternalRuleSetForwarding>(RuleEventKind::RULESET_FORWARDING, ProtocolType::ConnectionManagement,
                                                             executionPathFromType(RuleEventKind::RULESET_FORWARDING)));
  registerTranslator(messageClassName<InternalRuleSetForwarding_Application>(),
                    translatorFor<InternalRuleSetForwarding_Application>(RuleEventKind::RULESET_FORWARDING_APPLICATION, ProtocolType::Unknown,
                                                                         executionPathFromType(RuleEventKind::RULESET_FORWARDING_APPLICATION)));
  registerTranslator(messageClassName<StopEmitting>(),
                    translatorFor<StopEmitting>(RuleEventKind::STOP_EMITTING, ProtocolType::MSM_v1, executionPathFromType(RuleEventKind::STOP_EMITTING)));
  registerTranslator(messageClassName<SwappingResult>(),
                    translatorFor<SwappingResult>(RuleEventKind::SWAPPING_RESULT, ProtocolType::Swapping,
                                                  executionPathFromType(RuleEventKind::SWAPPING_RESULT)));
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
