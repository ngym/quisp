#include "ConnectionManager.h"

#include <gmock/gmock.h>
#include <gtest/gtest.h>
#include <omnetpp.h>
#include <nlohmann/json.hpp>

#include "messages/classical_messages.h"
#include "modules/QNIC.h"
#include "modules/QRSA/HardwareMonitor/IHardwareMonitor.h"
#include "modules/QRSA/RoutingDaemon/IRoutingDaemon.h"
#include "rules/Action.h"
#include "test_utils/TestUtils.h"

using json = nlohmann::json;
namespace {
using namespace omnetpp;
using namespace quisp_test;
using namespace testing;
using namespace quisp::messages;
using namespace quisp::modules;
using quisp::modules::QNIC_E;
using quisp::modules::QNIC_R;
using quisp::modules::QNIC_type;
using quisp::rules::PurType;

class Strategy : public quisp_test::TestComponentProviderStrategy {
 public:
  Strategy(IRoutingDaemon *_routing_daemon, IHardwareMonitor *_hardware_monitor) : routing_daemon(_routing_daemon), hardware_monitor(_hardware_monitor) {}
  Strategy() {}
  ~Strategy() {}
  int getNodeAddr() override { return 5; };
  IRoutingDaemon *getRoutingDaemon() override { return routing_daemon; }
  IHardwareMonitor *getHardwareMonitor() override { return hardware_monitor; }
  IRoutingDaemon *routing_daemon = nullptr;
  IHardwareMonitor *hardware_monitor = nullptr;
};

class ConnectionManagerTestTarget : public quisp::modules::ConnectionManager {
 public:
  using quisp::modules::ConnectionManager::isQnicBusy;
  using quisp::modules::ConnectionManager::par;
  using quisp::modules::ConnectionManager::parsePurType;
  using quisp::modules::ConnectionManager::purification_type;
  using quisp::modules::ConnectionManager::releaseQnic;
  using quisp::modules::ConnectionManager::reserved_qnics;
  using quisp::modules::ConnectionManager::reserveQnic;
  using quisp::modules::ConnectionManager::respondToRequest;
  using quisp::modules::ConnectionManager::respondToRequest_deprecated;
  using quisp::modules::ConnectionManager::storeRuleSet;
  using quisp::modules::ConnectionManager::storeRuleSetForApplication;
  bool shouldAcceptConnectionSetupResponseForTest(quisp::messages::ConnectionSetupResponse *pk) {
    return shouldAcceptConnectionSetupResponse(pk);
  }
  ConnectionManagerTestTarget(IRoutingDaemon *routing_daemon, IHardwareMonitor *hardware_monitor)
      : quisp::modules::ConnectionManager(), toRouterGate(new TestGate(this, "RouterPort$o")) {
    setComponentType(new module_type::TestModuleType("test cm"));
    setParInt(this, "address", 5);
    setParInt(this, "total_number_of_qnics", 10);
    this->setName("connection_manager_test_target");
    setParBool(this, "simultaneous_es_enabled", false);
    setParBool(this, "entanglement_swapping_with_purification", false);
    setParInt(this, "num_remote_purification", 1);
    setParStr(this, "purification_type_cm", "SINGLE_SELECTION_X_PURIFICATION");
    setParDouble(this, "threshold_fidelity", 0.0);
    setParInt(this, "seed_cm", 0);

    this->provider.setStrategy(std::make_unique<Strategy>(routing_daemon, hardware_monitor));
  }
  ConnectionManagerTestTarget() : quisp::modules::ConnectionManager(), toRouterGate(new TestGate(this, "RouterPort$o")) {
    setComponentType(new module_type::TestModuleType("test cm"));
    setParInt(this, "address", 5);
    setParInt(this, "total_number_of_qnics", 10);
    setParBool(this, "simultaneous_es_enabled", false);
    setParBool(this, "entanglement_swapping_with_purification", false);
    setParInt(this, "num_remote_purification", 1);
    setParStr(this, "purification_type_cm", "SINGLE_SELECTION_X_PURIFICATION");
    setParDouble(this, "threshold_fidelity", 0.0);
    setParInt(this, "seed_cm", 0);
    this->setName("connection_manager_test_target");
    this->provider.setStrategy(std::make_unique<Strategy>());
  }
  void receiveMessageForTest(cMessage *msg) { ConnectionManager::handleMessage(msg); }
  void send(cMessage *msg, const char *gatename, int gateindex = -1) override {
    if (strcmp(gatename, "RouterPort$o") == 0 || strcmp(gatename, "RouterPort") == 0 || strcmp(gatename, "RouterPort$o[0]") == 0 ||
        strncmp(gatename, "RouterPort$o[", 13) == 0) {
      if (!toRouterGate) {
        toRouterGate = new TestGate(this, "RouterPort$o");
      }
      cSimpleModule::send(msg, toRouterGate);
      return;
    }
    cSimpleModule::send(msg, gatename, gateindex);
  };
  void send(cMessage *msg, cGate *outputgate) override {
    if (outputgate == nullptr) {
      if (!toRouterGate) {
        toRouterGate = new TestGate(this, "RouterPort$o");
      }
      outputgate = toRouterGate;
    }
    cSimpleModule::send(msg, outputgate);
  }
  cGate *gate(const char *gatename, int index = -1) override {
    if (strcmp(gatename, "RouterPort$o") != 0 && strcmp(gatename, "RouterPort") != 0 && strcmp(gatename, "RouterPort$o[0]") != 0 &&
        strncmp(gatename, "RouterPort$o[", 13) != 0) {
      throw cRuntimeError("unknown gate called");
    }
    if (!toRouterGate) {
      toRouterGate = new TestGate(this, gatename == nullptr ? "RouterPort$o" : gatename);
    }
    return toRouterGate;
  };
  TestGate *toRouterGate;
  unsigned long createUniqueId() override { return 1234; };
};

TEST(ConnectionManagerTest, Init) {
  auto *sim = prepareSimulation();
  auto *c = new ConnectionManagerTestTarget{};
  sim->registerComponent(c);
  EXPECT_EQ(c->par("address").intValue(), 5);
  c->deleteModule();
}

TEST(ConnectionManagerTest, parsePurType) {
  prepareSimulation();
  auto *routing_daemon = new MockRoutingDaemon();
  auto *hardware_monitor = new MockHardwareMonitor();
  auto *connection_manager = new ConnectionManagerTestTarget(routing_daemon, hardware_monitor);

  auto pur_type = connection_manager->parsePurType("SINGLE_SELECTION_X_PURIFICATION");
  EXPECT_EQ(pur_type, PurType::SINGLE_SELECTION_X_PURIFICATION);
  pur_type = connection_manager->parsePurType("SINGLE_SELECTION_Y_PURIFICATION");
  EXPECT_EQ(pur_type, PurType::SINGLE_SELECTION_Y_PURIFICATION);
  pur_type = connection_manager->parsePurType("SINGLE_SELECTION_Z_PURIFICATION");
  EXPECT_EQ(pur_type, PurType::SINGLE_SELECTION_Z_PURIFICATION);
  pur_type = connection_manager->parsePurType("SINGLE_SELECTION_XZ_PURIFICATION");
  EXPECT_EQ(pur_type, PurType::SINGLE_SELECTION_XZ_PURIFICATION);
  pur_type = connection_manager->parsePurType("SINGLE_SELECTION_ZX_PURIFICATION");
  EXPECT_EQ(pur_type, PurType::SINGLE_SELECTION_ZX_PURIFICATION);
  pur_type = connection_manager->parsePurType("DOUBLE_SELECTION_X_PURIFICATION");
  EXPECT_EQ(pur_type, PurType::DOUBLE_SELECTION_X_PURIFICATION);
  pur_type = connection_manager->parsePurType("DOUBLE_SELECTION_Z_PURIFICATION");
  EXPECT_EQ(pur_type, PurType::DOUBLE_SELECTION_Z_PURIFICATION);
  pur_type = connection_manager->parsePurType("DOUBLE_SELECTION_XZ_PURIFICATION");
  EXPECT_EQ(pur_type, PurType::DOUBLE_SELECTION_XZ_PURIFICATION);
  pur_type = connection_manager->parsePurType("DOUBLE_SELECTION_ZX_PURIFICATION");
  EXPECT_EQ(pur_type, PurType::DOUBLE_SELECTION_ZX_PURIFICATION);
  pur_type = connection_manager->parsePurType("DOUBLE_SELECTION_X_PURIFICATION_SINGLE_SELECTION_Z_PURIFICATION");
  EXPECT_EQ(pur_type, PurType::DOUBLE_SELECTION_X_PURIFICATION_SINGLE_SELECTION_Z_PURIFICATION);
  pur_type = connection_manager->parsePurType("DOUBLE_SELECTION_Z_PURIFICATION_SINGLE_SELECTION_X_PURIFICATION");
  EXPECT_EQ(pur_type, PurType::DOUBLE_SELECTION_Z_PURIFICATION_SINGLE_SELECTION_X_PURIFICATION);
  // unknown purification name
  pur_type = connection_manager->parsePurType("DSDA_SECOND_INV_T");
  EXPECT_EQ(pur_type, PurType::INVALID);
}

TEST(ConnectionManagerTest, RespondToRequest) {
  auto *sim = prepareSimulation();
  auto *routing_daemon = new MockRoutingDaemon();
  auto *hardware_monitor = new MockHardwareMonitor();
  auto *connection_manager = new ConnectionManagerTestTarget(routing_daemon, hardware_monitor);
  sim->registerComponent(connection_manager);
  connection_manager->par("address") = 5;
  connection_manager->par("entanglement_swapping_with_purification") = true;

  connection_manager->callInitialize();
  auto *req = new ConnectionSetupRequest;

  // qnic_index(id)     11       12           13       14           15       16
  // [QNode2](qnic_addr:101) -- (102)[QNode3](103) -- (104)[QNode4](105) -- (106)[QNode5(test target)]
  req->setApplicationId(1);
  req->setActual_destAddr(5);
  req->setActual_srcAddr(2);
  req->setDestAddr(5);
  req->setSrcAddr(4);
  req->setStack_of_QNICsArraySize(3);
  req->setStack_of_QNodeIndexesArraySize(3);
  req->setStack_of_QNodeIndexes(0, 2);
  req->setStack_of_QNodeIndexes(1, 3);
  req->setStack_of_QNodeIndexes(2, 4);
  req->setStack_of_QNICs(0, QNicPairInfo{NULL_CONNECTION_SETUP_INFO.qnic, {.type = QNIC_E, .index = 11, .address = 101}});
  req->setStack_of_QNICs(1, QNicPairInfo{{.type = QNIC_E, .index = 12, .address = 102}, {.type = QNIC_E, .index = 13, .address = 103}});
  req->setStack_of_QNICs(2, QNicPairInfo{{.type = QNIC_E, .index = 14, .address = 104}, {.type = QNIC_E, .index = 15, .address = 105}});
  EXPECT_CALL(*routing_daemon, findQNicAddrByDestAddr(4)).Times(1).WillOnce(Return(106));

  sim->setContext(connection_manager);
  connection_manager->respondToRequest(req);
  auto gate = connection_manager->toRouterGate;
  EXPECT_EQ(gate->messages.size(), 4);
  // checking the ruleset for QNode2(initiator)
  {
    auto *packetFor2 = dynamic_cast<ConnectionSetupResponse *>(gate->messages[0]);
    ASSERT_NE(packetFor2, nullptr);
    EXPECT_EQ(packetFor2->getApplicationId(), 1);
    EXPECT_EQ(packetFor2->getDestAddr(), 2);
    auto ruleset = packetFor2->getRuleSet();  // json serialized ruleset
    ASSERT_NE(ruleset, nullptr);
    EXPECT_EQ(ruleset["rules"].size(), 2);
    auto expected_ruleset = R"({
  "num_rules": 2,
  "owner_address": 2,
  "rules": [
    {
      "action": {
        "options": {
          "interface": [
            {
              "partner_address": 3
            }
          ],
          "shared_rule_tag": 1
        },
        "type": "swapping_correction"
      },
      "condition": {
        "clauses": [
          {
            "options": {
              "interface": {
                "partner_address": 3
              },
              "shared_rule_tag": 1
            },
            "type": "swapping_correction"
          }
        ]
      },
      "interface": [
        {
          "partner_address": 3
        }
      ],
      "name": "swapping correction from 3",
      "receive_tag": 1,
      "send_tag": -1
    },
    {
      "action": {
        "options": {
          "interface": [
            {
              "partner_address": 5
            }
          ],
          "num_measure": 0,
          "owner_address": 2
        },
        "type": "tomography"
      },
      "condition": {
        "clauses": [
          {
            "options": {
              "interface": {
                "partner_address": 5
              },
              "num_resource": 1
            },
            "type": "enough_resource"
          },
          {
            "options": {
              "interface": {
                "partner_address": 5
              },
              "num_measure": 0
            },
            "type": "measure_count"
          }
        ]
      },
      "interface": [
        {
          "partner_address": 5
        }
      ],
      "name": "tomography with address 5",
      "receive_tag": 3,
      "send_tag": 3
    }
  ],
  "ruleset_id": 1234
})"_json;
    EXPECT_EQ(expected_ruleset, ruleset);
  }

  // checking the ruleset for QNode3 (swapper)
  {
    auto *packetFor3 = dynamic_cast<ConnectionSetupResponse *>(gate->messages[1]);
    ASSERT_NE(packetFor3, nullptr);
    EXPECT_EQ(packetFor3->getApplicationId(), 1);
    EXPECT_EQ(packetFor3->getDestAddr(), 3);
    auto ruleset = packetFor3->getRuleSet();  // json serialized ruleset
    ASSERT_NE(ruleset, nullptr);
    EXPECT_EQ(ruleset["rules"].size(), 2);

    auto expected_ruleset = R"({
  "num_rules": 2,
  "owner_address": 3,
  "rules": [
    {
      "action": {
        "options": {
          "interface": [
            {
              "partner_address": 4
            }
          ],
          "shared_rule_tag": 2
        },
        "type": "swapping_correction"
      },
      "condition": {
        "clauses": [
          {
            "options": {
              "interface": {
                "partner_address": 4
              },
              "shared_rule_tag": 2
            },
            "type": "swapping_correction"
          }
        ]
      },
      "interface": [
        {
          "partner_address": 4
        }
      ],
      "name": "swapping correction from 4",
      "receive_tag": 2,
      "send_tag": -1
    },
    {
      "action": {
        "options": {
          "interface": [
            {
              "partner_address": 2
            },
            {
              "partner_address": 5
            }
          ],
          "remote_interface": [
            {
              "partner_address": 2
            },
            {
              "partner_address": 5
            }
          ],
          "shared_rule_tag": 1
        },
        "type": "swapping"
      },
      "condition": {
        "clauses": [
          {
            "options": {
              "interface": {
                "partner_address": 2
              },
              "num_resource": 1
            },
            "type": "enough_resource"
          },
          {
            "options": {
              "interface": {
                "partner_address": 5
              },
              "num_resource": 1
            },
            "type": "enough_resource"
          }
        ]
      },
      "interface": [
        {
          "partner_address": 2
        },
        {
          "partner_address": 5
        }
      ],
      "name": "swap between 2 and 5",
      "receive_tag": -1,
      "send_tag": 1
    }
  ],
  "ruleset_id": 1234
})"_json;
    EXPECT_EQ(expected_ruleset, ruleset);
  }

  // checking the ruleset for QNode4 (swapper)
  {
    auto *packetFor4 = dynamic_cast<ConnectionSetupResponse *>(gate->messages[2]);
    ASSERT_NE(packetFor4, nullptr);
    EXPECT_EQ(packetFor4->getApplicationId(), 1);
    EXPECT_EQ(packetFor4->getDestAddr(), 4);
    auto ruleset = packetFor4->getRuleSet();  // json serialized ruleset
    ASSERT_NE(ruleset, nullptr);
    EXPECT_EQ(ruleset["rules"].size(), 1);

    // rule3 (id: 2): swapping with [3, 5], next to -1
    auto expected_ruleset = R"({
  "num_rules": 1,
  "owner_address": 4,
  "rules": [
    {
      "action": {
        "options": {
          "interface": [
            {
              "partner_address": 3
            },
            {
              "partner_address": 5
            }
          ],
          "remote_interface": [
            {
              "partner_address": 3
            },
            {
              "partner_address": 5
            }
          ],
          "shared_rule_tag": 2
        },
        "type": "swapping"
      },
      "condition": {
        "clauses": [
          {
            "options": {
              "interface": {
                "partner_address": 3
              },
              "num_resource": 1
            },
            "type": "enough_resource"
          },
          {
            "options": {
              "interface": {
                "partner_address": 5
              },
              "num_resource": 1
            },
            "type": "enough_resource"
          }
        ]
      },
      "interface": [
        {
          "partner_address": 3
        },
        {
          "partner_address": 5
        }
      ],
      "name": "swap between 3 and 5",
      "receive_tag": -1,
      "send_tag": 2
    }
  ],
  "ruleset_id": 1234
})"_json;
    EXPECT_EQ(expected_ruleset, ruleset);
  }

  // checking the ruleset for QNode5 (swapper)
  {
    auto *packetFor5 = dynamic_cast<ConnectionSetupResponse *>(gate->messages[3]);
    ASSERT_NE(packetFor5, nullptr);
    EXPECT_EQ(packetFor5->getApplicationId(), 1);
    EXPECT_EQ(packetFor5->getDestAddr(), 5);
    auto ruleset = packetFor5->getRuleSet();  // json serialized ruleset
    ASSERT_NE(ruleset, nullptr);
    EXPECT_EQ(ruleset["rules"].size(), 3);

    // rule6 (id: 5): tomography with 1, to (id: -1)
    auto expected_ruleset = R"({
  "num_rules": 3,
  "owner_address": 5,
  "rules": [
    {
      "action": {
        "options": {
          "interface": [
            {
              "partner_address": 4
            }
          ],
          "shared_rule_tag": 2
        },
        "type": "swapping_correction"
      },
      "condition": {
        "clauses": [
          {
            "options": {
              "interface": {
                "partner_address": 4
              },
              "shared_rule_tag": 2
            },
            "type": "swapping_correction"
          }
        ]
      },
      "interface": [
        {
          "partner_address": 4
        }
      ],
      "name": "swapping correction from 4",
      "receive_tag": 2,
      "send_tag": -1
    },
    {
      "action": {
        "options": {
          "interface": [
            {
              "partner_address": 3
            }
          ],
          "shared_rule_tag": 1
        },
        "type": "swapping_correction"
      },
      "condition": {
        "clauses": [
          {
            "options": {
              "interface": {
                "partner_address": 3
              },
              "shared_rule_tag": 1
            },
            "type": "swapping_correction"
          }
        ]
      },
      "interface": [
        {
          "partner_address": 3
        }
      ],
      "name": "swapping correction from 3",
      "receive_tag": 1,
      "send_tag": -1
    },
    {
      "action": {
        "options": {
          "interface": [
            {
              "partner_address": 2
            }
          ],
          "num_measure": 0,
          "owner_address": 5
        },
        "type": "tomography"
      },
      "condition": {
        "clauses": [
          {
            "options": {
              "interface": {
                "partner_address": 2
              },
              "num_resource": 1
            },
            "type": "enough_resource"
          },
          {
            "options": {
              "interface": {
                "partner_address": 2
              },
              "num_measure": 0
            },
            "type": "measure_count"
          }
        ]
      },
      "interface": [
        {
          "partner_address": 2
        }
      ],
      "name": "tomography with address 2",
      "receive_tag": 3,
      "send_tag": 3
    }
  ],
  "ruleset_id": 1234
})"_json;
    EXPECT_EQ(expected_ruleset, ruleset);
  }
  delete routing_daemon;
  delete hardware_monitor;
}

TEST(ConnectionManagerTest, QnicReservation) {
  prepareSimulation();
  auto *connection_manager = new ConnectionManagerTestTarget();

  int qnic_address = 13, qnic_address2 = 15;
  // qnic reservation
  EXPECT_EQ(connection_manager->reserved_qnics.size(), 0);
  connection_manager->reserveQnic(qnic_address);
  EXPECT_EQ(connection_manager->reserved_qnics.size(), 1);
  EXPECT_EQ(connection_manager->reserved_qnics.at(0), qnic_address);
  EXPECT_TRUE(connection_manager->isQnicBusy(qnic_address));
  EXPECT_FALSE(connection_manager->isQnicBusy(qnic_address2));
  connection_manager->reserveQnic(qnic_address2);
  EXPECT_EQ(connection_manager->reserved_qnics.size(), 2);
  EXPECT_EQ(connection_manager->reserved_qnics.at(1), qnic_address2);
  EXPECT_TRUE(connection_manager->isQnicBusy(qnic_address));
  EXPECT_TRUE(connection_manager->isQnicBusy(qnic_address2));

  // qnic release
  connection_manager->releaseQnic(qnic_address);
  EXPECT_EQ(connection_manager->reserved_qnics.size(), 1);
  EXPECT_EQ(connection_manager->reserved_qnics.at(0), qnic_address2);
  EXPECT_FALSE(connection_manager->isQnicBusy(qnic_address));
  EXPECT_TRUE(connection_manager->isQnicBusy(qnic_address2));
  connection_manager->releaseQnic(qnic_address2);
  EXPECT_EQ(connection_manager->reserved_qnics.size(), 0);
  EXPECT_FALSE(connection_manager->isQnicBusy(qnic_address));
  EXPECT_FALSE(connection_manager->isQnicBusy(qnic_address2));
}

TEST(ConnectionManagerTest, StoreRuleSetForApplicationDeduplicatesResponsesBySessionAndAttempt) {
  auto *connection_manager = new ConnectionManagerTestTarget();
  auto makeResponse = [](int session_id, int attempt, unsigned long ruleset_id) {
    auto *resp = new ConnectionSetupResponse("ConnectionSetupResponse");
    resp->setApplicationId(1);
    resp->setConnection_session_id(session_id);
    resp->setConnection_attempt(attempt);
    resp->setRuleSet_id(ruleset_id);
    resp->setDestAddr(10);
    resp->setSrcAddr(11);
    resp->setActual_destAddr(10);
    resp->setActual_srcAddr(11);
    resp->setRuleSet(json::parse(R"({"num_rules":1})"));
    resp->setApplication_type(7);
    return resp;
  };

  auto *resp_s1_a1_first = makeResponse(100, 1, 11);
  auto *resp_s1_a1_duplicate = makeResponse(100, 1, 12);
  auto *resp_s1_a2_first = makeResponse(100, 2, 13);
  auto *resp_s1_a2_duplicate = makeResponse(100, 2, 14);
  auto *resp_s1_a0_older = makeResponse(100, 0, 15);
  auto *resp_s2_a1_first = makeResponse(101, 1, 21);

  EXPECT_TRUE(connection_manager->shouldAcceptConnectionSetupResponseForTest(resp_s1_a1_first));
  EXPECT_FALSE(connection_manager->shouldAcceptConnectionSetupResponseForTest(resp_s1_a1_duplicate));
  EXPECT_TRUE(connection_manager->shouldAcceptConnectionSetupResponseForTest(resp_s1_a2_first));
  EXPECT_FALSE(connection_manager->shouldAcceptConnectionSetupResponseForTest(resp_s1_a2_duplicate));
  EXPECT_FALSE(connection_manager->shouldAcceptConnectionSetupResponseForTest(resp_s1_a0_older));
  EXPECT_TRUE(connection_manager->shouldAcceptConnectionSetupResponseForTest(resp_s2_a1_first));

  delete resp_s1_a1_first;
  delete resp_s1_a1_duplicate;
  delete resp_s1_a2_first;
  delete resp_s1_a2_duplicate;
  delete resp_s1_a0_older;
  delete resp_s2_a1_first;
}

TEST(ConnectionManagerTest, StoreRuleSetForApplicationForwardsOnlyFirstMessagePerAttempt) {
  auto *sim = prepareSimulation();
  auto *connection_manager = new ConnectionManagerTestTarget();
  sim->registerComponent(connection_manager);
  sim->setContext(connection_manager);
  connection_manager->callInitialize();
  auto makeResponse = [](int session_id, int attempt, unsigned long ruleset_id, int application_type) {
    auto *resp = new ConnectionSetupResponse("ConnectionSetupResponse");
    resp->setApplicationId(1);
    resp->setConnection_session_id(session_id);
    resp->setConnection_attempt(attempt);
    resp->setRuleSet_id(ruleset_id);
    resp->setDestAddr(10);
    resp->setSrcAddr(11);
    resp->setActual_destAddr(10);
    resp->setActual_srcAddr(11);
    resp->setRuleSet(json::parse(R"({"num_rules":1})"));
    resp->setApplication_type(application_type);
    return resp;
  };

  auto *resp_first = makeResponse(200, 3, 31, 7);
  auto *resp_duplicate = makeResponse(200, 3, 32, 7);
  auto *resp_later = makeResponse(200, 4, 33, 7);

  EXPECT_NE(connection_manager->toRouterGate, nullptr);
  EXPECT_NE(connection_manager->gate("RouterPort$o"), nullptr);
  connection_manager->storeRuleSetForApplication(resp_first);
  EXPECT_EQ(connection_manager->toRouterGate->messages.size(), 1);
  auto *forwarded_first =
      dynamic_cast<InternalRuleSetForwarding_Application *>(connection_manager->toRouterGate->messages.back());
  ASSERT_NE(forwarded_first, nullptr);
  EXPECT_EQ(forwarded_first->getRuleSet_id(), 31);
  EXPECT_EQ(forwarded_first->getApplication_type(), 7);

  connection_manager->storeRuleSetForApplication(resp_duplicate);
  EXPECT_EQ(connection_manager->toRouterGate->messages.size(), 1);
  EXPECT_EQ(dynamic_cast<InternalRuleSetForwarding_Application *>(connection_manager->toRouterGate->messages.back())->getRuleSet_id(), 31);

  connection_manager->storeRuleSetForApplication(resp_later);
  EXPECT_EQ(connection_manager->toRouterGate->messages.size(), 2);
  auto *forwarded_later =
      dynamic_cast<InternalRuleSetForwarding_Application *>(connection_manager->toRouterGate->messages.back());
  ASSERT_NE(forwarded_later, nullptr);
  EXPECT_EQ(forwarded_later->getRuleSet_id(), 33);

  delete resp_first;
  delete resp_duplicate;
  delete resp_later;
}

TEST(ConnectionManagerTest, StoreRuleSetForRoutingForwardsOnlyFirstMessagePerAttempt) {
  auto *sim = prepareSimulation();
  auto *connection_manager = new ConnectionManagerTestTarget();
  sim->registerComponent(connection_manager);
  sim->setContext(connection_manager);
  connection_manager->callInitialize();
  auto makeResponse = [](int session_id, int attempt, unsigned long ruleset_id) {
    auto *resp = new ConnectionSetupResponse("ConnectionSetupResponse");
    resp->setApplicationId(1);
    resp->setConnection_session_id(session_id);
    resp->setConnection_attempt(attempt);
    resp->setRuleSet_id(ruleset_id);
    resp->setDestAddr(10);
    resp->setSrcAddr(11);
    resp->setActual_destAddr(10);
    resp->setActual_srcAddr(11);
    resp->setRuleSet(json::parse(R"({"num_rules":1})"));
    resp->setApplication_type(7);
    return resp;
  };

  auto *resp_first = makeResponse(300, 1, 41);
  auto *resp_duplicate = makeResponse(300, 1, 42);
  auto *resp_later = makeResponse(300, 2, 43);

  connection_manager->storeRuleSet(resp_first);
  EXPECT_EQ(connection_manager->toRouterGate->messages.size(), 1);
  auto *forwarded_first = dynamic_cast<InternalRuleSetForwarding *>(connection_manager->toRouterGate->messages.back());
  ASSERT_NE(forwarded_first, nullptr);
  EXPECT_EQ(forwarded_first->getRuleSet_id(), 41);

  connection_manager->storeRuleSet(resp_duplicate);
  EXPECT_EQ(connection_manager->toRouterGate->messages.size(), 1);
  EXPECT_EQ(dynamic_cast<InternalRuleSetForwarding *>(connection_manager->toRouterGate->messages.back())->getRuleSet_id(), 41);

  connection_manager->storeRuleSet(resp_later);
  EXPECT_EQ(connection_manager->toRouterGate->messages.size(), 2);
  auto *forwarded_later = dynamic_cast<InternalRuleSetForwarding *>(connection_manager->toRouterGate->messages.back());
  ASSERT_NE(forwarded_later, nullptr);
  EXPECT_EQ(forwarded_later->getRuleSet_id(), 43);

  delete resp_first;
  delete resp_duplicate;
  delete resp_later;
}

TEST(ConnectionManagerTest, LegacyConnectionSetupResponseBySessionIdIsAlwaysAccepted) {
  auto *connection_manager = new ConnectionManagerTestTarget();
  auto makeResponse = [](int session_id, int attempt, unsigned long ruleset_id) {
    auto *resp = new ConnectionSetupResponse("ConnectionSetupResponse");
    resp->setApplicationId(1);
    resp->setConnection_session_id(session_id);
    resp->setConnection_attempt(attempt);
    resp->setRuleSet_id(ruleset_id);
    resp->setRuleSet(json::parse(R"({"num_rules":1})"));
    resp->setApplication_type(7);
    return resp;
  };

  auto *legacy_0 = makeResponse(0, 1, 31);
  auto *legacy_1 = makeResponse(0, 2, 32);
  auto *new_attempt = makeResponse(1, 1, 33);
  auto *same_attempt_retry = makeResponse(1, 1, 34);

  EXPECT_TRUE(connection_manager->shouldAcceptConnectionSetupResponseForTest(legacy_0));
  EXPECT_TRUE(connection_manager->shouldAcceptConnectionSetupResponseForTest(legacy_1));
  EXPECT_TRUE(connection_manager->shouldAcceptConnectionSetupResponseForTest(new_attempt));
  EXPECT_FALSE(connection_manager->shouldAcceptConnectionSetupResponseForTest(same_attempt_retry));

  delete legacy_0;
  delete legacy_1;
  delete new_attempt;
  delete same_attempt_retry;
}

}  // namespace
