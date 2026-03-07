#pragma once
#include <omnetpp.h>
#include <modules/Logger/ILogger.h>
#include <utils/ComponentProvider.h>
#include "messages/classical_messages.h"

namespace quisp::modules {

using namespace ospf;
using RoutingTable = std::map<NodeAddr, int>;  // destaddr -> gateindex

/** \class Router
 *
 *  \brief Router routes messages to components or other qnode according to the message header
 */
class Router : public omnetpp::cSimpleModule {
 public:
  Router();

 protected:
  virtual void initialize() override;
  virtual void handleMessage(omnetpp::cMessage* msg) override;
  void generateRoutingTable(cTopology* topo);
  void handleOspfHelloPacket(omnetpp::cMessage* msg);

 utils::ComponentProvider provider;
  Logger::ILogger *logger = nullptr;

  NodeAddr my_address;
  RoutingTable routing_table;
  std::map<int, int> next_hop_addr_by_gate_index;

 private:
  virtual bool parentModuleIsQNode();
  Logger::ILogger *ensureLogger();
  void emitClassicalPacketHop(const messages::Header *pk, int out_gate_index);
  void emitClassicalPacketLocalDelivery(const messages::Header *pk, const char *delivery_port);
  void nonQNodeForwardOspfPacket(messages::OspfPacket* pk);
  void sendOspfHelloPacketToQueue(messages::OspfPacket* pk);
  void redirectOspfHelloPacketToRoutingDaemon(messages::OspfPacket* pk);
};

Define_Module(Router);
}  // namespace quisp::modules
