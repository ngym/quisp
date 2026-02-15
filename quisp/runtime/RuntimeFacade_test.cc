#include <gtest/gtest.h>

#include "RuntimeFacade.h"
#include "RuntimeStateStore.h"
#include "RuleSet.h"
#include "test.h"
#include "modules/QRSA/RuleEngine/QubitRecord/QubitRecord.h"

namespace {
using namespace quisp::runtime;
using namespace quisp::modules::qubit_record;
using quisp::modules::QNIC_E;
using namespace quisp_test;
using namespace testing;

class RuntimeFacadeTest : public testing::Test {
 protected:
  void SetUp() {
    facade = new RuntimeFacade(std::make_unique<MockRuntimeCallback>());
  }
  void TearDown() {
    delete facade;
  }

  RuntimeFacade* facade;
};

TEST_F(RuntimeFacadeTest, SubmitRuleSetAndFindById) {
  RuleSet rs{"rs"};
  rs.id = 100;
  facade->submitRuleSet(rs);
  EXPECT_EQ(facade->size(), 1);
  EXPECT_NE(facade->findById(100), nullptr);
  EXPECT_EQ(facade->findById(100)->ruleset.id, 100);
}

TEST_F(RuntimeFacadeTest, SnapshotReflectsRuntimeResources) {
  const auto partner_addr = QNodeAddr{1};
  const int shared_rule_tag = 99;
  QubitId q0{0};
  Program cond{"cond", {INSTR_GET_QUBIT_QubitId_QNodeAddr_int_{{q0, partner_addr, 0}}, INSTR_RET_ReturnCode_{{ReturnCode::COND_PASSED}}}};
  Program action{"action", {}};
  Rule rule{"", -1, shared_rule_tag, cond, action};
  Program terminated{"", {INSTR_RET_ReturnCode_{{ReturnCode::RS_TERMINATED}}}};
  RuleSet rs{"snapshot", {rule}, terminated};
  rs.id = 101;

  facade->submitRuleSet(rs);
  auto* runtime = facade->findById(101);
  ASSERT_NE(runtime, nullptr);

  auto* qubit_record = new QubitRecord(QNIC_E, 0, 0);
  runtime->assignQubitToRuleSet(partner_addr, qubit_record);
  MessageRecord msg = {7, 8, 9};
  runtime->assignMessageToRuleSet(shared_rule_tag, msg);

  auto snapshot = facade->snapshotState(0);
  EXPECT_EQ(snapshot.terminated, false);
  EXPECT_EQ(snapshot.active_partners, 1);
  EXPECT_EQ(snapshot.qubit_resources, 1);
  EXPECT_EQ(snapshot.message_queues, 1);
  EXPECT_EQ(snapshot.named_qubits, 0);
}

TEST_F(RuntimeFacadeTest, AssignMessageToMissingRulesetIsNoop) {
  RuleSet rs{"rs", {}, Program{"", {}}};
  rs.id = 102;
  facade->submitRuleSet(rs);
  MessageRecord msg = {1, 2, 3};
  facade->assignMessageToRuleSet(9999, 0, msg);

  auto snapshot = facade->snapshotState(0);
  EXPECT_EQ(snapshot.terminated, false);
  EXPECT_EQ(snapshot.active_partners, 0);
  EXPECT_EQ(snapshot.qubit_resources, 0);
  EXPECT_EQ(snapshot.message_queues, 0);
}

}  // namespace
