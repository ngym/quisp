#include <memory>
#include <utility>
#include <nlohmann/json.hpp>

#include <gmock/gmock.h>
#include <gtest/gtest.h>
#include <omnetpp.h>

#include "BellPairStore/BellPairStore.h"
#include "IRuleEngine.h"
#include "QubitRecord/QubitRecord.h"
#include "RuleEngine.h"
#include "messages/purification_messages_m.h"
#include "modules/PhysicalConnection/BSA/types.h"
#include "modules/Logger/DisabledLogger.h"
#include "modules/Logger/ILogger.h"
#include "modules/QNIC.h"
#include "modules/QNIC/StationaryQubit/IStationaryQubit.h"
#include "modules/QRSA/HardwareMonitor/IHardwareMonitor.h"
#include "modules/QRSA/QRSA.h"
#include "modules/QRSA/RealTimeController/IRealTimeController.h"
#include "modules/QRSA/RoutingDaemon/RoutingDaemon.h"
#include "rules/Action.h"
#include "rules/Rule.h"
#include "rules/RuleSet.h"
#include "messages/QNode_ipc_messages_m.h"
#include "runtime/RuleSet.h"
#include "runtime/Runtime.h"
#include "runtime/opcode.h"
#include "runtime/test.h"
#include "runtime/types.h"
#include "test_utils/TestUtilFunctions.h"
#include "test_utils/Gate.h"
#include "test_utils/TestUtils.h"
#include "test_utils/mock_modules/MockHardwareMonitor.h"
#include "test_utils/mock_modules/MockQNicStore.h"
#include "test_utils/mock_modules/MockRealTimeController.h"
#include "test_utils/mock_modules/MockRoutingDaemon.h"

namespace {

using namespace omnetpp;
using namespace quisp::utils;
using namespace quisp::rules;
using namespace quisp::modules;
using quisp::modules::qrsa::IQubitRecord;
using quisp::modules::qubit_record::QubitRecord;
using namespace quisp_test;
using namespace testing;
using quisp::modules::Logger::DisabledLogger;
using quisp::modules::Logger::ILogger;
using namespace quisp::messages;
using quisp::runtime::InstructionTypes;
using quisp::runtime::Program;
using quisp::runtime::QNodeAddr;
using quisp::runtime::Runtime;

class RuleEngineEventLogger : public ILogger {
 public:
  void logPacket(const std::string& event_type, omnetpp::cMessage const* const msg) override {}
  void logQubitState(quisp::modules::QNIC_type qnic_type, int qnic_index, int qubit_index, bool is_busy, bool is_allocated) override {}
  void logBellPairInfo(const std::string& event_type, int partner_addr, quisp::modules::QNIC_type qnic_type, int qnic_index, int qubit_index) override {}
  void logEvent(const std::string& event_type, const std::string& event_payload_json) override {
    last_event_type = event_type;
    last_payload = event_payload_json;
    log_event_count++;
  };
  void setModule(omnetpp::cModule const* const mod) override {}
  void setQNodeAddress(int addr) override {}

  int log_event_count = 0;
  std::string last_event_type;
  std::string last_payload;
};

class TestQNicStoreStub : public IQNicStore {
 public:
  int count_num_free_calls = 0;
  int take_free_qubit_calls = 0;
  int set_qubit_busy_calls = 0;
  int count_num_free_return = 0;
  int take_free_qubit_return = 0;

  int countNumFreeQubits(QNIC_type type, int qnic_index) override {
    (void)type;
    (void)qnic_index;
    count_num_free_calls++;
    return count_num_free_return;
  }

  int takeFreeQubitIndex(QNIC_type type, int qnic_index) override {
    (void)type;
    (void)qnic_index;
    take_free_qubit_calls++;
    return take_free_qubit_return;
  }

  void setQubitBusy(QNIC_type type, int qnic_index, int qubit_index, bool is_busy) override {
    (void)type;
    (void)qnic_index;
    (void)qubit_index;
    (void)is_busy;
    set_qubit_busy_calls++;
  }

  quisp::modules::qrsa::IQubitRecord* getQubitRecord(QNIC_type type, int qnic_index, int qubit_index) override {
    (void)type;
    (void)qnic_index;
    (void)qubit_index;
    return nullptr;
  }
};

std::unique_ptr<quisp::rules::RuleSet> makeMinimalRuleSetForRuntimeForwarding(unsigned long ruleset_id = 0, int owner_address = 0,
                                                                              int partner_address = 1) {
  auto ruleset = std::make_unique<quisp::rules::RuleSet>(ruleset_id, owner_address);
  auto rule = std::make_unique<quisp::rules::Rule>(partner_address, -1, -1);
  rule->setName("forwarding test rule");

  auto condition = std::make_unique<Condition>();
  condition->addClause(std::make_unique<EnoughResourceConditionClause>(1, partner_address));
  rule->setCondition(std::move(condition));
  rule->setAction(std::make_unique<Tomography>(1, owner_address, partner_address));
  ruleset->addRule(std::move(rule));
  return ruleset;
}

class Strategy : public quisp_test::TestComponentProviderStrategy {
 public:
  Strategy() : mockQubit(nullptr), routingDaemon(nullptr), hardwareMonitor(nullptr), logger(std::make_unique<DisabledLogger>()) {}
  Strategy(IStationaryQubit* _qubit, MockRoutingDaemon* routing_daemon, MockHardwareMonitor* hardware_monitor, MockRealTimeController* realtime_controller,
           std::vector<QNicSpec> qnic_specs, std::unique_ptr<ILogger> logger)
      : TestComponentProviderStrategy(qnic_specs),
        mockQubit(_qubit),
        routingDaemon(routing_daemon),
        hardwareMonitor(hardware_monitor),
        realtimeController(realtime_controller),
        logger(std::move(logger)) {
    if (this->logger == nullptr) {
      this->logger = std::make_unique<DisabledLogger>();
    }
  }
  ~Strategy() {
    delete mockQubit;
    delete routingDaemon;
    delete hardwareMonitor;
    delete realtimeController;
  }
  IStationaryQubit* mockQubit = nullptr;
  MockRoutingDaemon* routingDaemon = nullptr;
  MockHardwareMonitor* hardwareMonitor = nullptr;
  MockRealTimeController* realtimeController = nullptr;
  std::unique_ptr<ILogger> logger;
  IStationaryQubit* getStationaryQubit(int qnic_index, int qubit_index, QNIC_type qnic_type) override {
    if (mockQubit == nullptr) mockQubit = new MockQubit(QNIC_E, 1);
    return mockQubit;
  };
  IRoutingDaemon* getRoutingDaemon() override { return routingDaemon; };
  IHardwareMonitor* getHardwareMonitor() override { return hardwareMonitor; };
  IRealTimeController* getRealTimeController() override { return realtimeController; };
  ILogger* getLogger() override { return logger.get(); }
};

class RuleEngineTestTarget : public quisp::modules::RuleEngine {
 public:
  using quisp::modules::RuleEngine::handlePurificationResult;
  using quisp::modules::RuleEngine::handleSwappingResult;
  using quisp::modules::RuleEngine::initialize;
  using quisp::modules::RuleEngine::handleMessage;
  using quisp::modules::RuleEngine::handleRuleEvent;
  using quisp::modules::RuleEngine::par;
  using quisp::modules::RuleEngine::qnic_store;
  using quisp::modules::RuleEngine::runtimes;
  using quisp::modules::RuleEngine::gate;

  RuleEngineTestTarget(IStationaryQubit* mockQubit, MockRoutingDaemon* routingdaemon, MockHardwareMonitor* hardware_monitor, MockRealTimeController* realtime_controller,
                       std::vector<QNicSpec> qnic_specs = {}, std::unique_ptr<ILogger> logger = {})
      : quisp::modules::RuleEngine() {
    setParInt(this, "address", 2);
    setParInt(this, "number_of_qnics_rp", 0);
    setParInt(this, "number_of_qnics_r", 1);
    setParInt(this, "number_of_qnics", 1);
    setParInt(this, "total_number_of_qnics", 2);
    setName("rule_engine_test_target");
    provider.setStrategy(std::make_unique<Strategy>(mockQubit, routingdaemon, hardware_monitor, realtime_controller, qnic_specs, std::move(logger)));
    setComponentType(new TestModuleType("rule_engine_test"));
    router_port_gate = std::make_unique<quisp_test::gate::TestGate>(this, "RouterPort$o");
    qnic_store = std::make_unique<StrictMock<MockQNicStore>>();
  }
  // setter function for allResorces[qnic_type][qnic_index]
  void setAllResources(int partner_addr, IQubitRecord* qubit) { this->bell_pair_store.insertEntangledQubit(partner_addr, qubit); };
  cGate *gate(const char* gate_name, int index = -1) override { return std::string(gate_name) == "RouterPort$o" ? router_port_gate.get() : RuleEngine::gate(gate_name, index); }

 private:
  FRIEND_TEST(RuleEngineTest, ESResourceUpdate);
  FRIEND_TEST(RuleEngineTest, trackerUpdate);
  friend class MockRoutingDaemon;
  friend class MockHardwareMonitor;
  std::unique_ptr<quisp_test::gate::TestGate> router_port_gate;
};

class RuleEngineRegistrationProbe : public RuleEngineTestTarget {
 public:
  using RuleEngineTestTarget::RuleEngineTestTarget;

  bool hasExactHandler(core::events::RuleEventType type, core::events::ProtocolSpec protocol_spec) const {
    return rule_event_handlers.find({type, protocol_spec}) != rule_event_handlers.end();
  }

  bool hasProtocolFallbackHandler(core::events::ProtocolSpec protocol_spec) const {
    return rule_protocol_fallback_handlers.find(static_cast<int>(protocol_spec)) != rule_protocol_fallback_handlers.end();
  }

  bool hasTypeFallbackHandler(core::events::RuleEventType type) const {
    return rule_event_type_fallback_handlers.find(static_cast<int>(type)) != rule_event_type_fallback_handlers.end();
  }
};

class RuleEngineTest : public testing::Test {
 protected:
  void SetUp() {
    sim = prepareSimulation();
    routing_daemon = new MockRoutingDaemon;
    hardware_monitor = new MockHardwareMonitor;
    realtime_controller = new MockRealTimeController;
  }
  void TearDown() {
    delete routing_daemon;
    delete hardware_monitor;
    delete realtime_controller;
  }
  utils::TestSimulation* sim;
  MockRoutingDaemon* routing_daemon;
  MockHardwareMonitor* hardware_monitor;
  MockRealTimeController* realtime_controller;
};

// specifier for qnics in order to create qnic_record and qubit_record.
static const std::vector<QNicSpec> qnic_specs = {{QNIC_E, 0, 2}, {QNIC_R, 0, 2}};

TEST_F(RuleEngineTest, resourceAllocation) {
  auto logger = std::make_unique<DisabledLogger>();
  auto* qubit_record0 = new QubitRecord(QNIC_E, 3, 0, logger.get());
  auto* qubit_record1 = new QubitRecord(QNIC_E, 3, 1, logger.get());
  auto* qubit_record2 = new QubitRecord(QNIC_E, 3, 2, logger.get());
  auto rule_engine = new RuleEngineTestTarget{nullptr, routing_daemon, hardware_monitor, nullptr, qnic_specs};
  sim->registerComponent(rule_engine);
  rule_engine->callInitialize();
  rule_engine->setAllResources(0, qubit_record0);
  rule_engine->setAllResources(1, qubit_record1);
  rule_engine->setAllResources(2, qubit_record2);
  int q0 = 0;
  QNodeAddr partner_addr{1};
  // this action needs a resource qubit that is entangled with partner 1.
  Program test_action{"testAction", {quisp::runtime::INSTR_GET_QUBIT_QubitId_QNodeAddr_int_{{q0, partner_addr, 0}}}};
  Program empty_condition{"emptyCondition", {}};
  auto rs = quisp::runtime::RuleSet{"test rs", {quisp::runtime::Rule{"test", -1, -1, empty_condition, test_action}}};
  auto runtime = quisp::runtime::Runtime{};
  rule_engine->runtimes.acceptRuleSet(rs);

  rule_engine->ResourceAllocation(QNIC_E, 3);
  EXPECT_TRUE(qubit_record1->isAllocated());

  // resource allocation assigns a corresponding qubit to action's resource
  auto& rt = rule_engine->runtimes.at(0);
  EXPECT_EQ(rt.ruleset.rules.size(), 1);
  EXPECT_EQ(rt.qubits.size(), 1);
}

TEST_F(RuleEngineTest, freeConsumedResourceFallsBackToQnicIndexWhenQubitNotRegistered) {
  auto* rule_engine = new RuleEngineTestTarget{nullptr, routing_daemon, hardware_monitor, realtime_controller};
  sim->registerComponent(rule_engine);
  rule_engine->callInitialize();
  int qnic_index = 7;
  auto logger = std::make_unique<DisabledLogger>();
  auto* qubit = new MockQubit(QNIC_E, qnic_index);
  auto* qubit_record = new QubitRecord(QNIC_E, qnic_index, 1, logger.get());
  qubit_record->setBusy(true);
  qubit->fillParams();

  EXPECT_CALL(*realtime_controller, ReInitialize_StationaryQubit(qubit_record, false)).Times(1).WillOnce(Return());
  EXPECT_CALL(*dynamic_cast<MockQNicStore*>(rule_engine->qnic_store.get()), getQubitRecord(QNIC_E, qnic_index, qnic_index)).Times(1).WillOnce(Return(qubit_record));
  rule_engine->freeConsumedResource(qnic_index, qubit, QNIC_E);
  EXPECT_FALSE(qubit_record->isBusy());
  delete qubit;
  rule_engine->qnic_store.reset();
}

TEST_F(RuleEngineTest, freeConsumedResourceUsesStationaryAddressWhenQubitRegistered) {
  auto* rule_engine = new RuleEngineTestTarget{nullptr, routing_daemon, hardware_monitor, realtime_controller};
  sim->registerComponent(rule_engine);
  rule_engine->callInitialize();
  int qnic_index = 7;
  auto logger = std::make_unique<DisabledLogger>();
  auto* qubit = new MockQubit(QNIC_E, qnic_index);
  qubit->fillParams();
  sim->registerComponent(qubit);
  auto* qubit_record = new QubitRecord(QNIC_E, qnic_index, 1, logger.get());
  qubit_record->setBusy(true);

  EXPECT_CALL(*realtime_controller, ReInitialize_StationaryQubit(qubit_record, false)).Times(1).WillOnce(Return());
  EXPECT_CALL(*dynamic_cast<MockQNicStore*>(rule_engine->qnic_store.get()), getQubitRecord(QNIC_E, qnic_index, 1)).Times(1).WillOnce(Return(qubit_record));
  rule_engine->freeConsumedResource(qnic_index, qubit, QNIC_E);
  EXPECT_FALSE(qubit_record->isBusy());
  qubit->deleteModule();
  rule_engine->qnic_store.reset();
}

TEST_F(RuleEngineTest, unknownRuleEventIsLogged) {
  auto logger = std::make_unique<RuleEngineEventLogger>();
  auto* raw_logger = logger.get();
  auto* rule_engine = new RuleEngineTestTarget{nullptr, routing_daemon, hardware_monitor, realtime_controller, qnic_specs, std::move(logger)};
  sim->registerComponent(rule_engine);
  sim->setContext(rule_engine);
  rule_engine->callInitialize();

  rule_engine->handleMessage(new cMessage("raw"));

  EXPECT_EQ(raw_logger->log_event_count, 1);
  EXPECT_EQ(raw_logger->last_event_type, "unknown_rule_event");
  EXPECT_THAT(raw_logger->last_payload, HasSubstr("\"event_type\": \"UNKNOWN\""));
  EXPECT_THAT(raw_logger->last_payload, HasSubstr("\"msg_name\": \"raw\""));
}

TEST_F(RuleEngineTest, unknownProtocolForKnownTypeIsLoggedAsUnknownRuleProtocol) {
  auto logger = std::make_unique<RuleEngineEventLogger>();
  auto* raw_logger = logger.get();
  auto* rule_engine = new RuleEngineTestTarget{nullptr, routing_daemon, hardware_monitor, realtime_controller, qnic_specs, std::move(logger)};
  sim->registerComponent(rule_engine);
  rule_engine->callInitialize();

  core::events::RuleEvent unknown_protocol_event{core::events::RuleEventType::BSM_RESULT, core::events::RuleEventChannel::EXTERNAL, false,
                                                 SimTime(1), 0, core::events::ProtocolSpec::Unknown,
                                                 core::events::ExecutionPath::EntanglementLifecycle};

  rule_engine->handleRuleEvent(unknown_protocol_event);

  EXPECT_EQ(raw_logger->last_event_type, "unknown_rule_protocol");
  EXPECT_THAT(raw_logger->last_payload, HasSubstr("\"event_type\": \""
                                                     + std::to_string(static_cast<int>(core::events::RuleEventType::BSM_RESULT)) + "\""));
  EXPECT_THAT(raw_logger->last_payload, HasSubstr("\"protocol_spec\": \"Unknown\""));
}

TEST_F(RuleEngineTest, dispatchRuleEventPrefersExactHandlerBeforeFallbacks) {
  auto logger = std::make_unique<RuleEngineEventLogger>();
  auto* raw_logger = logger.get();
  auto* rule_engine = new RuleEngineTestTarget{nullptr, routing_daemon, hardware_monitor, realtime_controller, qnic_specs, std::move(logger)};
  sim->registerComponent(rule_engine);
  rule_engine->callInitialize();

  int exact_calls = 0;
  int type_fallback_calls = 0;
  int protocol_fallback_calls = 0;
  core::events::RuleEvent event{core::events::RuleEventType::BSM_RESULT, core::events::RuleEventChannel::EXTERNAL, false, SimTime(1), 0,
                                core::events::ProtocolSpec::MSM_v1, core::events::ExecutionPath::EntanglementLifecycle};

  rule_engine->registerRuleEventHandler(core::events::RuleEventType::BSM_RESULT, core::events::ProtocolSpec::MSM_v1,
                                        [&exact_calls](const core::events::RuleEvent&) { ++exact_calls; });
  rule_engine->registerRuleEventTypeFallback(core::events::RuleEventType::BSM_RESULT,
                                            [&type_fallback_calls](const core::events::RuleEvent&) { ++type_fallback_calls; });
  rule_engine->registerRuleEventProtocolFallback(core::events::ProtocolSpec::MSM_v1,
                                                [&protocol_fallback_calls](const core::events::RuleEvent&) { ++protocol_fallback_calls; });
  rule_engine->handleRuleEvent(event);

  EXPECT_EQ(exact_calls, 1);
  EXPECT_EQ(type_fallback_calls, 0);
  EXPECT_EQ(protocol_fallback_calls, 0);
  EXPECT_EQ(raw_logger->log_event_count, 0);
}

TEST_F(RuleEngineTest, dispatchRuleEventFallsBackByTypeBeforeProtocolFallback) {
  auto logger = std::make_unique<RuleEngineEventLogger>();
  auto* raw_logger = logger.get();
  auto* rule_engine = new RuleEngineTestTarget{nullptr, routing_daemon, hardware_monitor, realtime_controller, qnic_specs, std::move(logger)};
  sim->registerComponent(rule_engine);
  rule_engine->callInitialize();

  int type_fallback_calls = 0;
  int protocol_fallback_calls = 0;
  core::events::RuleEvent event{core::events::RuleEventType::BSM_RESULT, core::events::RuleEventChannel::EXTERNAL, false, SimTime(1), 0,
                                core::events::ProtocolSpec::Maintenance, core::events::ExecutionPath::EntanglementLifecycle};

  rule_engine->registerRuleEventTypeFallback(core::events::RuleEventType::BSM_RESULT,
                                            [&type_fallback_calls](const core::events::RuleEvent&) { ++type_fallback_calls; });
  rule_engine->registerRuleEventProtocolFallback(core::events::ProtocolSpec::Maintenance,
                                                [&protocol_fallback_calls](const core::events::RuleEvent&) { ++protocol_fallback_calls; });
  rule_engine->handleRuleEvent(event);

  EXPECT_EQ(type_fallback_calls, 1);
  EXPECT_EQ(protocol_fallback_calls, 0);
  EXPECT_EQ(raw_logger->log_event_count, 0);
}

TEST_F(RuleEngineTest, dispatchRuleEventFallsBackByProtocolWhenTypeFallbackMissing) {
  auto logger = std::make_unique<RuleEngineEventLogger>();
  auto* raw_logger = logger.get();
  auto* rule_engine = new RuleEngineTestTarget{nullptr, routing_daemon, hardware_monitor, realtime_controller, qnic_specs, std::move(logger)};
  sim->registerComponent(rule_engine);
  rule_engine->callInitialize();

  int protocol_fallback_calls = 0;
  core::events::RuleEvent event{core::events::RuleEventType::BSM_RESULT, core::events::RuleEventChannel::EXTERNAL, false, SimTime(1), 0,
                                core::events::ProtocolSpec::Maintenance, core::events::ExecutionPath::EntanglementLifecycle};

  rule_engine->registerRuleEventProtocolFallback(core::events::ProtocolSpec::Maintenance,
                                                [&protocol_fallback_calls](const core::events::RuleEvent&) { ++protocol_fallback_calls; });
  rule_engine->handleRuleEvent(event);

  EXPECT_EQ(protocol_fallback_calls, 1);
  EXPECT_EQ(raw_logger->log_event_count, 0);
}

TEST_F(RuleEngineTest, bsmResultEventIsHandledByRegistrarWithoutUnknownLog) {
  auto logger = std::make_unique<RuleEngineEventLogger>();
  auto* raw_logger = logger.get();
  auto* rule_engine = new RuleEngineTestTarget{nullptr, routing_daemon, hardware_monitor, realtime_controller, qnic_specs, std::move(logger)};
  sim->registerComponent(rule_engine);
  rule_engine->callInitialize();

  auto bsm_result = new CombinedBSAresults();
  bsm_result->setQnicType(QNIC_E);
  bsm_result->setQnicIndex(0);
  rule_engine->handleMessage(bsm_result);

  EXPECT_EQ(raw_logger->log_event_count, 0);
  EXPECT_EQ(raw_logger->last_event_type, "");
}

TEST_F(RuleEngineTest, bsmTimingEventIsHandledByRegistrarWithoutUnknownLog) {
  auto logger = std::make_unique<RuleEngineEventLogger>();
  auto* raw_logger = logger.get();
  auto* rule_engine = new RuleEngineTestTarget{nullptr, routing_daemon, hardware_monitor, realtime_controller, qnic_specs, std::move(logger)};
  sim->registerComponent(rule_engine);
  rule_engine->callInitialize();

  auto bsm_timing = new BSMTimingNotification();
  bsm_timing->setQnicType(QNIC_E);
  bsm_timing->setQnicIndex(0);
  bsm_timing->setInterval(1.0);
  bsm_timing->setFirstPhotonEmitTime(SimTime(0.1));
  rule_engine->handleMessage(bsm_timing);

  EXPECT_EQ(raw_logger->log_event_count, 0);
  EXPECT_EQ(raw_logger->last_event_type, "");
}

TEST_F(RuleEngineTest, eppsTimingEventIsHandledByRegistrarWithoutUnknownLog) {
  auto logger = std::make_unique<RuleEngineEventLogger>();
  auto* raw_logger = logger.get();
  auto* rule_engine = new RuleEngineTestTarget{nullptr, routing_daemon, hardware_monitor, realtime_controller, qnic_specs, std::move(logger)};
  sim->registerComponent(rule_engine);
  rule_engine->callInitialize();

  auto epps_timing = new EPPSTimingNotification();
  epps_timing->setOtherQnicParentAddr(1);
  epps_timing->setOtherQnicIndex(0);
  epps_timing->setEPPSAddr(1);
  epps_timing->setQnicIndex(0);
  epps_timing->setTotalTravelTime(0);
  epps_timing->setFirstPhotonEmitTime(SimTime(0.1));
  epps_timing->setInterval(1.0);
  rule_engine->handleMessage(epps_timing);

  EXPECT_EQ(raw_logger->log_event_count, 0);
  EXPECT_EQ(raw_logger->last_event_type, "");
}

TEST_F(RuleEngineTest, singleClickResultEventIsHandledByRegistrarWithoutUnknownLog) {
  using namespace quisp_test::mock_modules::qnic_store;
  using namespace quisp::physical::types;

  auto logger = std::make_unique<RuleEngineEventLogger>();
  auto* raw_logger = logger.get();
  auto* rule_engine = new RuleEngineTestTarget{nullptr, routing_daemon, hardware_monitor, realtime_controller, qnic_specs, std::move(logger)};
  sim->registerComponent(rule_engine);
  rule_engine->callInitialize();

  auto* single_click = new SingleClickResult();
  single_click->setQnicIndex(0);
  single_click->setClickResult(BSAClickResult{false, PauliOperator::I});

  auto* qnic_store_stub = new TestQNicStoreStub();
  rule_engine->qnic_store.reset(qnic_store_stub);
  EXPECT_CALL(*realtime_controller, ReInitialize_StationaryQubit(0, 0, QNIC_RP, false)).Times(1);

  sim->setContext(rule_engine);
  rule_engine->handleMessage(single_click);

  EXPECT_EQ(raw_logger->log_event_count, 0);
  EXPECT_EQ(raw_logger->last_event_type, "");
  EXPECT_EQ(qnic_store_stub->set_qubit_busy_calls, 1);

  rule_engine->qnic_store.reset();
	// do not delete rule_engine directly here (OMNeT++ module lifecycle handled by simulation environment)
}

TEST_F(RuleEngineTest, msmResultEventIsHandledByRegistrarWithoutUnknownLog) {
  auto logger = std::make_unique<RuleEngineEventLogger>();
  auto* raw_logger = logger.get();
  auto* rule_engine = new RuleEngineTestTarget{nullptr, routing_daemon, hardware_monitor, realtime_controller, qnic_specs, std::move(logger)};
  sim->registerComponent(rule_engine);
  rule_engine->callInitialize();

  auto* msm_result = new MSMResult();
  msm_result->setQnicIndex(0);
  msm_result->setPhotonIndex(1);
  msm_result->setSuccess(false);
  msm_result->setCorrectionOperation(PauliOperator::I);
  rule_engine->handleMessage(msm_result);

  EXPECT_EQ(raw_logger->log_event_count, 0);
  EXPECT_EQ(raw_logger->last_event_type, "");
}

TEST_F(RuleEngineTest, purificationResultEventIsHandledByRegistrarWithoutUnknownLog) {
  auto logger = std::make_unique<RuleEngineEventLogger>();
  auto* raw_logger = logger.get();
  auto* rule_engine = new RuleEngineTestTarget{nullptr, routing_daemon, hardware_monitor, realtime_controller, qnic_specs, std::move(logger)};
  sim->registerComponent(rule_engine);
  rule_engine->callInitialize();

  auto* purification_result = new PurificationResult();
  purification_result->setRulesetId(0);
  purification_result->setSharedRuleTag(0);
  purification_result->setSequenceNumber(0);
  purification_result->setMeasurementResult(0);
  purification_result->setProtocol(0);
  rule_engine->handleMessage(purification_result);

  EXPECT_EQ(raw_logger->log_event_count, 0);
  EXPECT_EQ(raw_logger->last_event_type, "");
}

TEST_F(RuleEngineTest, swappingResultEventIsHandledByRegistrarWithoutUnknownLog) {
  auto logger = std::make_unique<RuleEngineEventLogger>();
  auto* raw_logger = logger.get();
  auto* rule_engine = new RuleEngineTestTarget{nullptr, routing_daemon, hardware_monitor, realtime_controller, qnic_specs, std::move(logger)};
  sim->registerComponent(rule_engine);
  rule_engine->callInitialize();

  auto* swapping_result = new SwappingResult();
  swapping_result->setRulesetId(0);
  swapping_result->setSharedRuleTag(0);
  swapping_result->setSequenceNumber(0);
  swapping_result->setCorrectionFrame(0);
  swapping_result->setNewPartner(1);
  rule_engine->handleMessage(swapping_result);

  EXPECT_EQ(raw_logger->log_event_count, 0);
  EXPECT_EQ(raw_logger->last_event_type, "");
}

TEST_F(RuleEngineTest, linkTomographyRuleSetEventIsHandledByRegistrarWithoutUnknownLog) {
  auto logger = std::make_unique<RuleEngineEventLogger>();
  auto* raw_logger = logger.get();
  auto* rule_engine = new RuleEngineTestTarget{nullptr, routing_daemon, hardware_monitor, realtime_controller, qnic_specs, std::move(logger)};
  sim->registerComponent(rule_engine);
  rule_engine->callInitialize();

  auto* link_tomography = new LinkTomographyRuleSet();
  auto* ruleset = makeMinimalRuleSetForRuntimeForwarding(0, 0, 1).release();
  link_tomography->setRuleSet(ruleset);
  rule_engine->handleMessage(link_tomography);

  EXPECT_EQ(raw_logger->log_event_count, 0);
  EXPECT_EQ(raw_logger->last_event_type, "");
}

TEST_F(RuleEngineTest, stopEmittingEventIsHandledByRegistrarWithoutUnknownLog) {
  auto logger = std::make_unique<RuleEngineEventLogger>();
  auto* raw_logger = logger.get();
  auto* rule_engine = new RuleEngineTestTarget{nullptr, routing_daemon, hardware_monitor, realtime_controller, qnic_specs, std::move(logger)};
  sim->registerComponent(rule_engine);
  rule_engine->callInitialize();

  auto stop_emitting = new StopEmitting();
  stop_emitting->setQnic_address(0);
  rule_engine->handleMessage(stop_emitting);

  EXPECT_EQ(raw_logger->log_event_count, 0);
  EXPECT_EQ(raw_logger->last_event_type, "");
}

TEST_F(RuleEngineTest, ruleSetForwardingEventIsHandledByRegistrarWithoutUnknownLog) {
  auto logger = std::make_unique<RuleEngineEventLogger>();
  auto* raw_logger = logger.get();
  auto* rule_engine = new RuleEngineTestTarget{nullptr, routing_daemon, hardware_monitor, realtime_controller, qnic_specs, std::move(logger)};
  sim->registerComponent(rule_engine);
  rule_engine->callInitialize();

  auto forwarding = new InternalRuleSetForwarding();
  nlohmann::json empty_ruleset = makeMinimalRuleSetForRuntimeForwarding(0, 0, 1)->serialize_json();
  forwarding->setRuleSet(empty_ruleset);
  rule_engine->handleMessage(forwarding);

  EXPECT_EQ(raw_logger->log_event_count, 0);
  EXPECT_EQ(raw_logger->last_event_type, "");
}

TEST_F(RuleEngineTest, ruleSetForwardingApplicationEventIsHandledByRegistrarWithoutUnknownLog) {
  auto logger = std::make_unique<RuleEngineEventLogger>();
  auto* raw_logger = logger.get();
  auto* rule_engine = new RuleEngineTestTarget{nullptr, routing_daemon, hardware_monitor, realtime_controller, qnic_specs, std::move(logger)};
  sim->registerComponent(rule_engine);
  rule_engine->callInitialize();

  auto forwarding = new InternalRuleSetForwarding_Application();
  forwarding->setApplication_type(0);
  nlohmann::json empty_ruleset = makeMinimalRuleSetForRuntimeForwarding(0, 0, 1)->serialize_json();
  forwarding->setRuleSet(empty_ruleset);
  rule_engine->handleMessage(forwarding);

  EXPECT_EQ(raw_logger->log_event_count, 0);
  EXPECT_EQ(raw_logger->last_event_type, "");
}

TEST_F(RuleEngineTest, ruleSetForwardingApplicationEventWithUnknownApplicationTypeIsLogged) {
  auto logger = std::make_unique<RuleEngineEventLogger>();
  auto* raw_logger = logger.get();
  auto* rule_engine = new RuleEngineTestTarget{nullptr, routing_daemon, hardware_monitor, realtime_controller, qnic_specs, std::move(logger)};
  sim->registerComponent(rule_engine);
  rule_engine->callInitialize();

  auto forwarding = new InternalRuleSetForwarding_Application();
  forwarding->setApplication_type(999);
  nlohmann::json empty_ruleset = makeMinimalRuleSetForRuntimeForwarding(0, 0, 1)->serialize_json();
  forwarding->setRuleSet(empty_ruleset);

  EXPECT_NO_THROW(rule_engine->handleMessage(forwarding));

  EXPECT_EQ(raw_logger->last_event_type, "unknown_rule_protocol");
  EXPECT_THAT(raw_logger->last_payload, HasSubstr("\"protocol_raw_value\": \"999\""));
}

TEST(RuleProtocolHandlerRegistrarTest, registerDefaultsRegistersExpectedExactEventHandlers) {
  RuleEngineRegistrationProbe rule_engine_probe(nullptr, nullptr, nullptr, nullptr);

  EXPECT_TRUE(rule_engine_probe.hasExactHandler(core::events::RuleEventType::BSM_RESULT, core::events::ProtocolSpec::MIM_v1));
  EXPECT_TRUE(rule_engine_probe.hasExactHandler(core::events::RuleEventType::BSM_TIMING, core::events::ProtocolSpec::MIM_v1));
  EXPECT_TRUE(rule_engine_probe.hasExactHandler(core::events::RuleEventType::EPPS_TIMING, core::events::ProtocolSpec::MSM_v1));
  EXPECT_TRUE(rule_engine_probe.hasExactHandler(core::events::RuleEventType::EMIT_PHOTON_REQUEST, core::events::ProtocolSpec::Unknown));
  EXPECT_TRUE(rule_engine_probe.hasExactHandler(core::events::RuleEventType::SINGLE_CLICK_RESULT, core::events::ProtocolSpec::MSM_v1));
  EXPECT_TRUE(rule_engine_probe.hasExactHandler(core::events::RuleEventType::MSM_RESULT, core::events::ProtocolSpec::MSM_v1));
  EXPECT_TRUE(rule_engine_probe.hasExactHandler(core::events::RuleEventType::STOP_EMITTING, core::events::ProtocolSpec::MSM_v1));
  EXPECT_TRUE(rule_engine_probe.hasExactHandler(core::events::RuleEventType::PURIFICATION_RESULT, core::events::ProtocolSpec::Purification));
  EXPECT_TRUE(rule_engine_probe.hasExactHandler(core::events::RuleEventType::SWAPPING_RESULT, core::events::ProtocolSpec::Swapping));
  EXPECT_TRUE(rule_engine_probe.hasExactHandler(core::events::RuleEventType::RULESET_FORWARDING, core::events::ProtocolSpec::ConnectionManagement));
  EXPECT_TRUE(rule_engine_probe.hasExactHandler(core::events::RuleEventType::RULESET_FORWARDING_APPLICATION, core::events::ProtocolSpec::ConnectionManagement));
  EXPECT_TRUE(rule_engine_probe.hasExactHandler(core::events::RuleEventType::LINK_TOMOGRAPHY_RULESET, core::events::ProtocolSpec::LinkTomography));
  EXPECT_TRUE(rule_engine_probe.hasExactHandler(core::events::RuleEventType::UNKNOWN, core::events::ProtocolSpec::Unknown));
  EXPECT_FALSE(rule_engine_probe.hasProtocolFallbackHandler(core::events::ProtocolSpec::MSM_v1));
  EXPECT_FALSE(rule_engine_probe.hasTypeFallbackHandler(core::events::RuleEventType::UNKNOWN));
}

TEST(RuleProtocolHandlerRegistrarTest, registerDefaultsDoesNotRegisterFallbackHandlers) {
  RuleEngineRegistrationProbe rule_engine_probe(nullptr, nullptr, nullptr, nullptr);

  EXPECT_FALSE(rule_engine_probe.hasProtocolFallbackHandler(core::events::ProtocolSpec::MIM_v1));
  EXPECT_FALSE(rule_engine_probe.hasProtocolFallbackHandler(core::events::ProtocolSpec::MSM_v1));
  EXPECT_FALSE(rule_engine_probe.hasProtocolFallbackHandler(core::events::ProtocolSpec::Purification));
  EXPECT_FALSE(rule_engine_probe.hasProtocolFallbackHandler(core::events::ProtocolSpec::Swapping));
  EXPECT_FALSE(rule_engine_probe.hasProtocolFallbackHandler(core::events::ProtocolSpec::ConnectionManagement));
  EXPECT_FALSE(rule_engine_probe.hasProtocolFallbackHandler(core::events::ProtocolSpec::LinkTomography));
  EXPECT_FALSE(rule_engine_probe.hasTypeFallbackHandler(core::events::RuleEventType::BSM_RESULT));
  EXPECT_FALSE(rule_engine_probe.hasTypeFallbackHandler(core::events::RuleEventType::BSM_TIMING));
  EXPECT_FALSE(rule_engine_probe.hasTypeFallbackHandler(core::events::RuleEventType::EPPS_TIMING));
  EXPECT_FALSE(rule_engine_probe.hasTypeFallbackHandler(core::events::RuleEventType::EMIT_PHOTON_REQUEST));
  EXPECT_FALSE(rule_engine_probe.hasTypeFallbackHandler(core::events::RuleEventType::SINGLE_CLICK_RESULT));
  EXPECT_FALSE(rule_engine_probe.hasTypeFallbackHandler(core::events::RuleEventType::MSM_RESULT));
  EXPECT_FALSE(rule_engine_probe.hasTypeFallbackHandler(core::events::RuleEventType::STOP_EMITTING));
  EXPECT_FALSE(rule_engine_probe.hasTypeFallbackHandler(core::events::RuleEventType::PURIFICATION_RESULT));
  EXPECT_FALSE(rule_engine_probe.hasTypeFallbackHandler(core::events::RuleEventType::SWAPPING_RESULT));
  EXPECT_FALSE(rule_engine_probe.hasTypeFallbackHandler(core::events::RuleEventType::RULESET_FORWARDING));
  EXPECT_FALSE(rule_engine_probe.hasTypeFallbackHandler(core::events::RuleEventType::RULESET_FORWARDING_APPLICATION));
  EXPECT_FALSE(rule_engine_probe.hasTypeFallbackHandler(core::events::RuleEventType::LINK_TOMOGRAPHY_RULESET));
}

TEST_F(RuleEngineTest, directUnknownRuleEventFromRuleEngineLogsUnknownRuleEvent) {
  auto logger = std::make_unique<RuleEngineEventLogger>();
  auto* raw_logger = logger.get();
  auto* rule_engine = new RuleEngineTestTarget{nullptr, routing_daemon, hardware_monitor, realtime_controller, qnic_specs, std::move(logger)};
  sim->registerComponent(rule_engine);
  sim->setContext(rule_engine);
  rule_engine->callInitialize();

  core::events::RuleEvent unknown_event{core::events::RuleEventType::UNKNOWN, core::events::RuleEventChannel::EXTERNAL, false, SimTime(2), 11,
                                        core::events::ProtocolSpec::Unknown, core::events::ExecutionPath::Unknown};
  rule_engine->handleRuleEvent(unknown_event);

  EXPECT_EQ(raw_logger->last_event_type, "unknown_rule_event");
  EXPECT_THAT(raw_logger->last_payload, HasSubstr("\"event_type\": \"UNKNOWN\""));
  EXPECT_THAT(raw_logger->last_payload, HasSubstr("\"event_number\": 11"));
}

TEST_F(RuleEngineTest, emitPhotonRequestEventIsHandledByRegistrarWithoutUnknownLog) {
  auto logger = std::make_unique<RuleEngineEventLogger>();
  auto* raw_logger = logger.get();
  auto* rule_engine = new RuleEngineTestTarget{nullptr, routing_daemon, hardware_monitor, realtime_controller, qnic_specs, std::move(logger)};
  sim->registerComponent(rule_engine);
  rule_engine->callInitialize();

  auto emit_request = new EmitPhotonRequest();
  emit_request->setQnicType(QNIC_E);
  emit_request->setQnicIndex(0);
  emit_request->setIntervalBetweenPhotons(SimTime(2));
  emit_request->setMSM(false);
  emit_request->setFirst(true);

  auto* qnic_store_stub = new TestQNicStoreStub();
  qnic_store_stub->count_num_free_return = 1;
  qnic_store_stub->take_free_qubit_return = 5;
  rule_engine->qnic_store.reset(qnic_store_stub);
 	EXPECT_CALL(*realtime_controller, EmitPhoton(0, 5, QNIC_E, _)).Times(1);

  rule_engine->handleMessage(emit_request);

  EXPECT_EQ(raw_logger->log_event_count, 0);
  EXPECT_EQ(raw_logger->last_event_type, "");
  EXPECT_EQ(qnic_store_stub->count_num_free_calls, 1);
  EXPECT_EQ(qnic_store_stub->take_free_qubit_calls, 1);

  rule_engine->qnic_store.reset();
	// do not delete rule_engine directly here (OMNeT++ module lifecycle handled by simulation environment)
}

}  // namespace
