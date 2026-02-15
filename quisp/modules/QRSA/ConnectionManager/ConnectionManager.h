/*
 * ConnectionManager.h
 *
 *  Created on: Sep 14, 2020
 *      Author: zigen
 */

#pragma once

#include <omnetpp.h>
#include <queue>
#include <vector>
#include <unordered_map>

#include "IConnectionManager.h"

#include <messages/classical_messages.h>
#include <modules/Logger/LoggerBase.h>
#include <modules/QNIC.h>
#include <modules/QRSA/HardwareMonitor/IHardwareMonitor.h>
#include <modules/QRSA/RoutingDaemon/IRoutingDaemon.h>
#include <rules/Action.h>
#include <utils/ComponentProvider.h>

struct SwappingConfig {
  int left_partner;
  int lres;
  int right_partner;
  int rres;
};

namespace quisp::modules {

/** \class ConnectionManager ConnectionManager.cc
 *
 *  \brief ConnectionManager
 *
 * The ConnectionManager is one of the five key modules in the
 * software for a quantum repeater/router (qrsa).  It is responsible for
 * managing the connections: initiating ConnectionSetupRequests,
 * behaving as responder for a ConnectionSetupRequest (which involves
 * actually creating the RuleSets), and handling the requests and
 * responses as the move along the path at setup time.
 *
 * It communicates with the RuleEngine, which is responsible for
 * actually executing the Rules as it is notified of events, but
 * the ConnectionManager has _nothing_ to do with the actual
 * processing of the quantum states as they evolve.
 *
 * You will see member functions for the roles as initiator, responder,
 * and intermediate node.  The main tasks are to respond to ConnectionSetupRequest,
 * ConnectionSetupResponse, RejectConnectionSetupRequest, and ConnectionTeardown messages.
 *
 * It is also responsible for the end-to-end reservation of resources,
 * as dictated by the multiplexing (muxing) discipline in use.
 */
class ConnectionManager : public IConnectionManager, public Logger::LoggerBase {
 public:
  enum class ConnectionManagerEventChannel { InternalTimer, ProtocolMessage, Unknown };
  enum class ConnectionManagerProtocolType { Unknown, SetupRequest, SetupResponse, RejectSetupRequest };
  enum class ConnectionManagerSelfTimingStatus { NotSelfMessage, Known, UnknownIndex };

  struct DecodedConnectionManagerEvent {
    ConnectionManagerEventChannel channel = ConnectionManagerEventChannel::Unknown;
    ConnectionManagerProtocolType protocol_type = ConnectionManagerProtocolType::Unknown;
    ConnectionManagerSelfTimingStatus self_timing_status = ConnectionManagerSelfTimingStatus::NotSelfMessage;
    int self_timing_qnic_index = -1;
    omnetpp::cMessage* raw = nullptr;
  };

 public:
  ConnectionManager();
  ~ConnectionManager();
  utils::ComponentProvider provider;

 protected:
  int my_address;
  int num_of_qnics;
  std::map<int, std::queue<messages::ConnectionSetupRequest *>> connection_setup_buffer;  // key is qnic address
  std::map<int, int> connection_retry_count;  // key is qnic address
  struct ConnectionSetupResponseState {
    int latest_attempt = -1;
    bool accepted_for_latest_attempt = false;
  };
  std::unordered_map<int, ConnectionSetupResponseState> connection_setup_response_state;
  std::vector<int> reserved_qnics = {};  // reserved qnic address table
  std::vector<cMessage *> request_send_timing;  // self message, notification for sending out request
  bool simultaneous_es_enabled;
  bool es_with_purify = false;
  int num_remote_purification;
  double threshold_fidelity;
  rules::PurType purification_type;
  IRoutingDaemon *routing_daemon;
  IHardwareMonitor *hardware_monitor;

  void initialize() override;
  void handleMessage(cMessage *msg) override;
  virtual DecodedConnectionManagerEvent decodeIncomingMessage(omnetpp::cMessage* msg) const;
  virtual bool isKnownSelfTimingMessage(const omnetpp::cMessage* msg, int& qnic_index) const;
  virtual void dispatchInternalEvent(const DecodedConnectionManagerEvent& ev);
  virtual void dispatchProtocolMessage(const DecodedConnectionManagerEvent& ev);
  virtual void handleUnknownControlMessage(const DecodedConnectionManagerEvent& ev);
  virtual void handleSelfTiming(int qnic_address);
  virtual void handleProtocolSetupRequest(messages::ConnectionSetupRequest* msg);
  virtual void handleProtocolSetupResponse(messages::ConnectionSetupResponse* msg);
  virtual void handleProtocolRejectSetup(messages::RejectConnectionSetupRequest* msg);
  virtual void handleUnknownControlMessage(cMessage* msg);
  virtual void handleIncomingControlMessage(cMessage* msg);

  void respondToRequest(messages::ConnectionSetupRequest *pk);
  void respondToRequest_deprecated(messages::ConnectionSetupRequest *pk);
  void tryRelayRequestToNextHop(messages::ConnectionSetupRequest *pk);

  void queueApplicationRequest(messages::ConnectionSetupRequest *pk);
  void initiateApplicationRequest(int qnic_address);
  void scheduleRequestRetry(int qnic_address);
  void popApplicationRequest(int qnic_address);

  void storeRuleSetForApplication(messages::ConnectionSetupResponse *pk);
  void storeRuleSet(messages::ConnectionSetupResponse *pk);

  void initiator_reject_req_handler(messages::RejectConnectionSetupRequest *pk);
  void responder_reject_req_handler(messages::RejectConnectionSetupRequest *pk);
  void intermediate_reject_req_handler(messages::RejectConnectionSetupRequest *pk);

  void rejectRequest(messages::ConnectionSetupRequest *req);

  void reserveQnic(int qnic_address);
  void releaseQnic(int qnic_address);
  bool isQnicBusy(int qnic_address);
  bool shouldAcceptConnectionSetupResponse(messages::ConnectionSetupResponse *pk);
  bool isLegacyConnectionSessionResponse(messages::ConnectionSetupResponse *pk);

  static rules::PurType parsePurType(const std::string &pur_type);

  unsigned long createUniqueId() override;
};

}  // namespace quisp::modules
