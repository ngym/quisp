#include <gmock/gmock.h>
#include <gtest/gtest.h>
#include <omnetpp.h>

#include <algorithm>
#include <vector>

#include "RuleEventBus.h"
#include "messages/BSA_ipc_messages_m.h"
#include "messages/QNode_ipc_messages_m.h"
#include "messages/entanglement_swapping_messages_m.h"
#include "messages/link_generation_messages_m.h"
#include "messages/purification_messages_m.h"
#include "messages/tomography_messages_m.h"

namespace {

using namespace omnetpp;
using namespace quisp::core::events;
using namespace quisp::messages;
using namespace testing;

TEST(RuleEventBusTest, ConvertsKnownMessagesToRuleEvents) {
  RuleEventBus bus;
  simtime_t now = SimTime(1);
  CombinedBSAresults combined_bsm_result;
  BSMTimingNotification bsm_timing;
  EPPSTimingNotification epps_timing;
  EmitPhotonRequest emit_photon;
  InternalRuleSetForwarding forwarding;
  InternalRuleSetForwarding_Application forwarding_app;
  LinkTomographyRuleSet link_tomography;
  MSMResult msm_result;
  PurificationResult purification_result;
  SingleClickResult single_click;
  StopEmitting stop_emitting;
  SwappingResult swapping_result;

  bus.publish(&combined_bsm_result, now);
  bus.publish(&bsm_timing, now);
  bus.publish(&epps_timing, now);
  bus.publish(&emit_photon, now);
  bus.publish(&forwarding, now);
  bus.publish(&forwarding_app, now);
  bus.publish(&link_tomography, now);
  bus.publish(&msm_result, now);
  bus.publish(&purification_result, now);
  bus.publish(&single_click, now);
  bus.publish(&stop_emitting, now);
  bus.publish(&swapping_result, now);

  auto events = bus.drain(now);
  ASSERT_EQ(events.size(), 11);

  EXPECT_EQ(std::count_if(events.begin(), events.end(), [](const RuleEvent& e) {
              return e.type == RuleEventType::BSM_RESULT && std::holds_alternative<CombinedBSAresults *>(e.payload);
            }),
            1);
  EXPECT_EQ(std::count_if(events.begin(), events.end(), [](const RuleEvent& e) {
              return e.type == RuleEventType::BSM_TIMING && std::holds_alternative<BSMTimingNotification *>(e.payload);
            }),
            1);
  EXPECT_EQ(std::count_if(events.begin(), events.end(), [](const RuleEvent& e) {
              return e.type == RuleEventType::EPPS_TIMING && std::holds_alternative<EPPSTimingNotification *>(e.payload);
            }),
            1);
  EXPECT_EQ(std::count_if(events.begin(), events.end(), [](const RuleEvent& e) {
              return e.type == RuleEventType::EMIT_PHOTON_REQUEST && std::holds_alternative<EmitPhotonRequest *>(e.payload);
            }),
            1);
  EXPECT_EQ(std::count_if(events.begin(), events.end(), [](const RuleEvent& e) {
              return e.type == RuleEventType::RULESET_FORWARDING && std::holds_alternative<InternalRuleSetForwarding *>(e.payload);
            }),
            1);
  EXPECT_EQ(std::count_if(events.begin(), events.end(), [](const RuleEvent& e) {
              return e.type == RuleEventType::RULESET_FORWARDING_APPLICATION &&
                     std::holds_alternative<InternalRuleSetForwarding_Application *>(e.payload);
            }),
            1);
  EXPECT_EQ(std::count_if(events.begin(), events.end(), [](const RuleEvent& e) {
              return e.type == RuleEventType::LINK_TOMOGRAPHY_RULESET && std::holds_alternative<LinkTomographyRuleSet *>(e.payload);
            }),
            1);
  EXPECT_EQ(std::count_if(events.begin(), events.end(), [](const RuleEvent& e) {
              return e.type == RuleEventType::MSM_RESULT && std::holds_alternative<MSMResult *>(e.payload);
            }),
            1);
  EXPECT_EQ(std::count_if(events.begin(), events.end(), [](const RuleEvent& e) {
              return e.type == RuleEventType::PURIFICATION_RESULT && std::holds_alternative<PurificationResult *>(e.payload);
            }),
            1);
  EXPECT_EQ(std::count_if(events.begin(), events.end(), [](const RuleEvent& e) {
              return e.type == RuleEventType::SINGLE_CLICK_RESULT && std::holds_alternative<SingleClickResult *>(e.payload);
            }),
            1);
  EXPECT_EQ(std::count_if(events.begin(), events.end(), [](const RuleEvent& e) {
              return e.type == RuleEventType::STOP_EMITTING && std::holds_alternative<StopEmitting *>(e.payload);
            }),
            1);
  EXPECT_EQ(std::count_if(events.begin(), events.end(), [](const RuleEvent& e) {
              return e.type == RuleEventType::SWAPPING_RESULT && std::holds_alternative<SwappingResult *>(e.payload);
            }),
            1);
}

TEST(RuleEventBusTest, KeepsOrderByTimeThenEventNumberInDrain) {
  RuleEventBus bus;
  bus.publish(RuleEvent{RuleEventType::BSM_RESULT, SimTime(2), 10});
  bus.publish(RuleEvent{RuleEventType::BSM_RESULT, SimTime(1), 100});
  bus.publish(RuleEvent{RuleEventType::BSM_RESULT, SimTime(2), 5});
  bus.publish(RuleEvent{RuleEventType::BSM_RESULT, SimTime(1), 20});
  bus.publish(RuleEvent{RuleEventType::BSM_RESULT, SimTime(3), 3});

  auto events = bus.drain(SimTime(2.5));
  ASSERT_EQ(events.size(), 4);
  EXPECT_EQ(events[0].time, SimTime(1));
  EXPECT_EQ(events[0].event_number, 20);
  EXPECT_EQ(events[1].time, SimTime(1));
  EXPECT_EQ(events[1].event_number, 100);
  EXPECT_EQ(events[2].time, SimTime(2));
  EXPECT_EQ(events[2].event_number, 5);
  EXPECT_EQ(events[3].time, SimTime(2));
  EXPECT_EQ(events[3].event_number, 10);
}

TEST(RuleEventBusTest, UnknownMessageAndNullMessageAreHandled) {
  RuleEventBus bus;
  bus.publish(RuleEvent{RuleEventType::UNKNOWN, SimTime(1), 9});
  bus.publish(nullptr, SimTime(1));

  auto events = bus.drain(SimTime(1));
  ASSERT_EQ(events.size(), 1);
  EXPECT_EQ(events[0].type, RuleEventType::UNKNOWN);
  EXPECT_TRUE(std::holds_alternative<std::monostate>(events[0].payload));
}

TEST(RuleEventBusTest, DrainsOnlyEventsBeforeOrAtCurrentTime) {
  RuleEventBus bus;
  bus.publish(RuleEvent{RuleEventType::BSM_RESULT, SimTime(3), 1});
  bus.publish(RuleEvent{RuleEventType::BSM_RESULT, SimTime(1), 2});
  bus.publish(RuleEvent{RuleEventType::BSM_RESULT, SimTime(2), 3});

  auto events = bus.drain(SimTime(1.5));
  ASSERT_EQ(events.size(), 1);
  EXPECT_EQ(events[0].event_number, 2);

  auto rest = bus.drain(SimTime(3));
  ASSERT_EQ(rest.size(), 2);
  EXPECT_EQ(rest[0].event_number, 3);
  EXPECT_EQ(rest[1].event_number, 1);
}

}  // namespace
