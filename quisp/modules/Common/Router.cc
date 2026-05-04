/** \file Router.cc
 *  \authors takaakimatsuo
 *
 *  \brief Router
 */
#include "Router.h"
#include <nlohmann/json.hpp>
#include "messages/BSA_ipc_messages_m.h"
#include "messages/classical_messages.h"  //Path selection: type = 1, Timing notifier for BMA: type = 4
#include "messages/link_generation_messages_m.h"

using namespace omnetpp;
using namespace quisp::messages;

namespace quisp::modules {

namespace {

std::string shortClassName(const cMessage *message) {
  if (message == nullptr) {
    return "Unknown";
  }
  const std::string class_name = message->getClassName();
  const auto separator = class_name.rfind("::");
  if (separator == std::string::npos) {
    return class_name;
  }
  return class_name.substr(separator + 2);
}

std::string protocolFamilyFor(const Header *pk) {
  if (dynamic_cast<const ConnectionSetupRequest *>(pk) != nullptr || dynamic_cast<const ConnectionSetupResponse *>(pk) != nullptr ||
      dynamic_cast<const RejectConnectionSetupRequest *>(pk) != nullptr) {
    return "connection_setup";
  }
  if (dynamic_cast<const InternalRuleSetForwarding *>(pk) != nullptr || dynamic_cast<const InternalRuleSetForwarding_Application *>(pk) != nullptr) {
    return "ruleset_forwarding";
  }
  if (dynamic_cast<const SwappingResult *>(pk) != nullptr) {
    return "swapping";
  }
  if (dynamic_cast<const PurificationResult *>(pk) != nullptr) {
    return "purification";
  }
  if (dynamic_cast<const BSMTimingNotification *>(pk) != nullptr || dynamic_cast<const EPPSTimingNotification *>(pk) != nullptr ||
      dynamic_cast<const SingleClickResult *>(pk) != nullptr || dynamic_cast<const MSMResult *>(pk) != nullptr || dynamic_cast<const StopEmitting *>(pk) != nullptr ||
      dynamic_cast<const StopEPPSEmission *>(pk) != nullptr) {
    return "link_generation";
  }
  if (dynamic_cast<const LinkTomographyRequest *>(pk) != nullptr || dynamic_cast<const LinkTomographyAck *>(pk) != nullptr ||
      dynamic_cast<const LinkTomographyRuleSet *>(pk) != nullptr || dynamic_cast<const LinkTomographyResult *>(pk) != nullptr) {
    return "tomography";
  }
  if (dynamic_cast<const OspfPacket *>(pk) != nullptr) {
    return "routing";
  }
  return "unknown";
}

NodeAddr finalSourceAddress(const Header *pk) {
  if (const auto *req = dynamic_cast<const ConnectionSetupRequest *>(pk)) {
    return req->getActual_srcAddr();
  }
  if (const auto *res = dynamic_cast<const ConnectionSetupResponse *>(pk)) {
    return res->getActual_srcAddr();
  }
  if (const auto *rej = dynamic_cast<const RejectConnectionSetupRequest *>(pk)) {
    return rej->getActual_srcAddr();
  }
  return pk->getSrcAddr();
}

NodeAddr finalDestinationAddress(const Header *pk) {
  if (const auto *req = dynamic_cast<const ConnectionSetupRequest *>(pk)) {
    return req->getActual_destAddr();
  }
  if (const auto *res = dynamic_cast<const ConnectionSetupResponse *>(pk)) {
    return res->getActual_destAddr();
  }
  if (const auto *rej = dynamic_cast<const RejectConnectionSetupRequest *>(pk)) {
    return rej->getActual_destAddr();
  }
  return pk->getDestAddr();
}

}  // namespace

Router::Router() : provider(utils::ComponentProvider{this}) {}

void Router::initialize() {
  my_address = provider.getNodeAddr();

  // Topology creation for routing table
  auto topo = provider.getTopologyForRouter();

  // If no node with the parameter & value found, do nothing.
  if (topo->getNumNodes() == 0 || topo == nullptr) {
    return;
  }

  generateRoutingTable(topo);
}

void Router::generateRoutingTable(cTopology *topo) {
  cTopology::Node *thisNode = topo->getNodeFor(getParentModule());  // The parent node with this specific router

  // Traverse through all the destinations from the thisNode
  for (int i = 0; i < topo->getNumNodes(); i++) {
    const auto node = topo->getNode(i);
    // skip the node that is running this specific router app
    if (node == thisNode) continue;

    // Apply dijkstra to each node to find all shortest paths.
    topo->calculateWeightedSingleShortestPathsTo(topo->getNode(i));

    // Overwrites getNumPaths() and so on.
    // Check the number of shortest paths towards the target node.
    // This may be more than 1 if multiple paths have the same minimum cost.

    if (thisNode->getNumPaths() == 0) continue;

    // Returns the next link/gate in the ith shortest paths towards the target node.
    cGate *parentModuleGate = thisNode->getPath(0)->getLocalGate();
    int gateIndex = parentModuleGate->getIndex();
    int address = topo->getNode(i)->getModule()->par("address");
    auto *remoteNode = thisNode->getPath(0)->getRemoteNode();
    int nextHopAddr = remoteNode == nullptr ? address : static_cast<int>(remoteNode->getModule()->par("address"));

    // Store gate index per destination from this node
    routing_table[address] = gateIndex;
    next_hop_addr_by_gate_index[gateIndex] = nextHopAddr;

    if (strstr(parentModuleGate->getFullName(), "quantum")) {
      error("Classical routing table referring to quantum gates...");
    }
  }
}

void Router::handleMessage(cMessage *msg) {
  const int unidentified_destination = -1;
  // check the header of the received package
  Header *pk = check_and_cast<Header *>(msg);
  int dest_addr = pk->getDestAddr();
  int who_are_you = pk->getKind();

  // If destination is this node: Path selection
  if (dest_addr == my_address && who_are_you == 1) {
    emitClassicalPacketLocalDelivery(pk, "toApp");
    send(pk, "toApp");
    return;
  } else if (dest_addr == my_address && dynamic_cast<BSMTimingNotification *>(msg)) {  // Timing for BSM
    bubble("Timing Notifier from BSA (stand-alone or internal) received");
    emitClassicalPacketLocalDelivery(pk, "rePort");
    send(pk, "rePort$o");  // send to Application locally
    return;
  } else if (dest_addr == my_address && dynamic_cast<EPPSTimingNotification *>(msg)) {  // Timing for BSM
    bubble("Timing Notifier from EPPS received");
    emitClassicalPacketLocalDelivery(pk, "rePort");
    send(pk, "rePort$o");  // send to Application locally
    return;
  } else if (dest_addr == my_address && dynamic_cast<SingleClickResult *>(msg)) {
    bubble("Single click result from BSA received");
    emitClassicalPacketLocalDelivery(pk, "rePort");
    send(pk, "rePort$o");
    return;
  } else if (dest_addr == my_address && dynamic_cast<MSMResult *>(msg)) {
    bubble("MSM BSA result from partner RE received");
    emitClassicalPacketLocalDelivery(pk, "rePort");
    send(pk, "rePort$o");
    return;
  } else if (dest_addr == my_address && dynamic_cast<StopEPPSEmission *>(msg)) {
    bubble("Stop EPPS emission signal received");
    emitClassicalPacketLocalDelivery(pk, "toApp");
    send(pk, "toApp");
    return;
  } else if (dest_addr == my_address && dynamic_cast<ConnectionSetupRequest *>(msg)) {
    bubble("Connection setup request received");
    emitClassicalPacketLocalDelivery(pk, "cmPort");
    send(pk, "cmPort$o");
    return;
  } else if (dest_addr == my_address && dynamic_cast<ConnectionSetupResponse *>(msg)) {
    bubble("Connection setup response received");
    emitClassicalPacketLocalDelivery(pk, "cmPort");
    send(pk, "cmPort$o");
    return;
  } else if (dest_addr == my_address && dynamic_cast<RejectConnectionSetupRequest *>(msg)) {
    bubble("Reject connection setup response received");
    emitClassicalPacketLocalDelivery(pk, "cmPort");
    send(pk, "cmPort$o");
    return;
  } else if (dest_addr == my_address && dynamic_cast<InternalRuleSetForwarding *>(msg)) {
    bubble("Internal RuleSet Forwarding packet received");
    emitClassicalPacketLocalDelivery(pk, "rePort");
    send(pk, "rePort$o");
    return;
  } else if (dest_addr == my_address && dynamic_cast<InternalRuleSetForwarding_Application *>(msg)) {
    bubble("Internal RuleSet Forwarding Application packet received");
    emitClassicalPacketLocalDelivery(pk, "rePort");
    send(pk, "rePort$o");
    return;
  } else if (dest_addr == my_address && dynamic_cast<SwappingResult *>(msg)) {
    bubble("Swapping Result packet received");
    emitClassicalPacketLocalDelivery(pk, "rePort");
    send(pk, "rePort$o");
    return;
  } else if (dest_addr == my_address && dynamic_cast<LinkTomographyRequest *>(msg)) {
    bubble("Link tomography request received");
    emitClassicalPacketLocalDelivery(pk, "hmPort");
    send(pk, "hmPort$o");
    return;
  } else if (dest_addr == my_address && dynamic_cast<LinkTomographyAck *>(msg)) {
    bubble("Link tomography ack received");
    emitClassicalPacketLocalDelivery(pk, "hmPort");
    send(pk, "hmPort$o");
    return;
  } else if (dest_addr == my_address && dynamic_cast<LinkTomographyRuleSet *>(msg)) {
    bubble("Link tomography rule set received");
    emitClassicalPacketLocalDelivery(pk, "rePort");
    send(pk, "rePort$o");
    return;
  } else if (dest_addr == my_address && dynamic_cast<LinkTomographyResult *>(msg)) {
    bubble("Link tomography result received");
    emitClassicalPacketLocalDelivery(pk, "hmPort");
    send(pk, "hmPort$o");
    return;
  } else if (dest_addr == my_address && dynamic_cast<PurificationResult *>(msg)) {
    bubble("Purification result received");
    emitClassicalPacketLocalDelivery(pk, "rePort");
    send(pk, "rePort$o");
    return;
  } else if (dest_addr == my_address && dynamic_cast<StopEmitting *>(msg)) {
    emitClassicalPacketLocalDelivery(pk, "rePort");
    send(pk, "rePort$o");
    return;
  } else if (dest_addr == my_address && dynamic_cast<OspfPacket *>(msg)) {
    emitClassicalPacketLocalDelivery(pk, "rdPort");
    send(pk, "rdPort$o");
    return;
  }

  // RoutingDaemon sends hello packet without desination specified
  if (dest_addr == unidentified_destination && dynamic_cast<OspfHelloPacket *>(msg)) {
    handleOspfHelloPacket(msg);
    return;
  }

  // Check if packet is reachable
  if (!routing_table.count(dest_addr)) {
    std::cout << "In Node[" << my_address << "]Address... " << dest_addr << " unreachable, discarding packet " << pk->getName() << endl;
    delete pk;
    error("Router couldn't find the path. Shoudn't happen. Or maybe the router does not understand the packet.");
    return;
  }

  int out_gate_index = routing_table.at(dest_addr);
  pk->setHopCount(pk->getHopCount() + 1);
  emitClassicalPacketHop(pk, out_gate_index);
  send(pk, "toQueue", out_gate_index);
}

void Router::handleOspfHelloPacket(cMessage *msg) {
  auto pk = dynamic_cast<OspfHelloPacket *>(msg);
  if (!parentModuleIsQNode()) {
    nonQNodeForwardOspfPacket(pk);
    return;
  }

  const bool dst_is_this_node = (pk->getSrcAddr() != my_address);
  if (dst_is_this_node) {
    redirectOspfHelloPacketToRoutingDaemon(pk);
  } else {
    sendOspfHelloPacketToQueue(pk);
  }
}

bool Router::parentModuleIsQNode() { return provider.getNode()->getModuleType() == cModuleType::get("modules.QNode"); }

/**
 * @details Unlike QNodes, BSA nodes are connected to only two nodes (at least that is the assumption)
 *          So this function simulates BSA nodes receiving packets from one node, and sending them to the other node.
 */
void Router::nonQNodeForwardOspfPacket(OspfPacket *pk) {
  pk->setHopCount(pk->getHopCount() + 1);
  const int gate_index_to_pk_src = pk->getArrivalGate()->getIndex();
  const int gate_index_to_pk_dst = gate_index_to_pk_src == 0 ? 1 : 0;
  emitClassicalPacketHop(pk, gate_index_to_pk_dst);
  send(pk, "toQueue", gate_index_to_pk_dst);
}

void Router::sendOspfHelloPacketToQueue(OspfPacket *pk) {
  pk->setHopCount(pk->getHopCount() + 1);
  const int gate_index_to_pk_dst = pk->getSendingGateIndex();
  emitClassicalPacketHop(pk, gate_index_to_pk_dst);
  send(pk, "toQueue", gate_index_to_pk_dst);
}

void Router::redirectOspfHelloPacketToRoutingDaemon(OspfPacket *pk) {
  emitClassicalPacketLocalDelivery(pk, "rdPort");
  send(pk, "rdPort$o");
}

Logger::ILogger *Router::ensureLogger() {
  if (logger != nullptr) {
    return logger;
  }
  logger = provider.getLogger();
  if (logger != nullptr) {
    logger->setModule(provider.module);
    logger->setQNodeAddress(provider.getNodeAddr());
  }
  return logger;
}

void Router::emitClassicalPacketHop(const Header *pk, int out_gate_index) {
  auto *event_logger = ensureLogger();
  if (event_logger == nullptr || pk == nullptr) {
    return;
  }
  nlohmann::json payload = {
      {"packet_uid", pk->getId()},
      {"msg_type", shortClassName(pk)},
      {"msg_class_name", pk->getClassName()},
      {"protocol_family", protocolFamilyFor(pk)},
      {"src_node_id", my_address},
      {"dst_node_id", next_hop_addr_by_gate_index.count(out_gate_index) ? next_hop_addr_by_gate_index.at(out_gate_index) : pk->getDestAddr()},
      {"final_src_addr", finalSourceAddress(pk)},
      {"final_dest_addr", finalDestinationAddress(pk)},
      {"hop_count", pk->getHopCount()},
      {"module_path", getFullPath()},
  };
  event_logger->logEvent("classical_packet_hop", payload.dump());
}

void Router::emitClassicalPacketLocalDelivery(const Header *pk, const char *delivery_port) {
  auto *event_logger = ensureLogger();
  if (event_logger == nullptr || pk == nullptr) {
    return;
  }
  nlohmann::json payload = {
      {"packet_uid", pk->getId()},
      {"msg_type", shortClassName(pk)},
      {"msg_class_name", pk->getClassName()},
      {"protocol_family", protocolFamilyFor(pk)},
      {"node_id", my_address},
      {"delivery_port", delivery_port == nullptr ? "" : delivery_port},
      {"final_src_addr", finalSourceAddress(pk)},
      {"final_dest_addr", finalDestinationAddress(pk)},
      {"hop_count", pk->getHopCount()},
      {"module_path", getFullPath()},
  };
  event_logger->logEvent("classical_packet_deliver_local", payload.dump());
}

}  // namespace quisp::modules
