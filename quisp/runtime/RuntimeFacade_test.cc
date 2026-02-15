#include <gtest/gtest.h>

#include "RuntimeFacade.h"
#include "RuntimeStateStore.h"
#include "RuleSet.h"
#include "test.h"

namespace {
using namespace quisp::runtime;
using namespace quisp::modules;
using namespace quisp::modules::qubit_record;
using namespace quisp_test;
using namespace testing;

class RuntimeFacadeTest : public testing::Test {
 protected:
  void SetUp() {
    auto cb = std::make_unique<MockRuntimeCallback>();
    callback = cb.get();
    facade = new RuntimeFacade(std::move(cb));
  }
  void TearDown() {
    delete facade;
  }

  RuntimeFacade* facade;
  MockRuntimeCallback* callback = nullptr;
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
  QubitId q0{0};
  Program cond{"cond", {INSTR_GET_QUBIT_QubitId_QNodeAddr_int_{{q0, partner_addr, 0}}, INSTR_RET_ReturnCode_{{ReturnCode::COND_PASSED}}}};
  Program action{"action", {}};
  Rule rule{"", -1, -1, cond, action};
  Program terminated{"", {INSTR_RET_ReturnCode_{{ReturnCode::RS_TERMINATED}}}};
  RuleSet rs{"snapshot", {rule}, terminated};
  rs.id = 101;

  facade->submitRuleSet(rs);
  auto* runtime = facade->findById(101);
  ASSERT_NE(runtime, nullptr);

  auto* qubit_record = new QubitRecord(QNIC_E, 0, 0);
  runtime->assignQubitToRuleSet(partner_addr, qubit_record);
  MessageRecord msg = {7, 8, 9};
  runtime->assignMessageToRuleSet(-1, msg);

  auto snapshot = facade->snapshotState(0);
  EXPECT_EQ(snapshot.terminated, false);
  EXPECT_EQ(snapshot.active_partners, 1);
  EXPECT_EQ(snapshot.qubit_resources, 1);
  EXPECT_EQ(snapshot.message_queues, 1);
  EXPECT_EQ(snapshot.named_qubits, 0);
}

}  // namespace
