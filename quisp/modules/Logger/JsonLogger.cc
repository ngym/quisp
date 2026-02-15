#include "JsonLogger.h"
#include <sstream>
#include <iomanip>
#include "messages/connection_setup_messages_m.h"

namespace quisp::modules::Logger {

using quisp::messages::ConnectionSetupRequest;
using quisp::messages::ConnectionSetupResponse;
using quisp::messages::RejectConnectionSetupRequest;

JsonLogger::JsonLogger(std::shared_ptr<spdlog::logger> logger) : _logger(logger) {
  std::string jsonpattern = {"{%v}"};
  _logger->set_pattern(jsonpattern);
}

JsonLogger::~JsonLogger() {}

void JsonLogger::setModule(omnetpp::cModule const* const mod) {
  module = mod;
  module_path = mod->getFullPath();
}

void JsonLogger::setQNodeAddress(int addr) { qnode_address = addr; }

void JsonLogger::logPacket(const std::string& event_type, omnetpp::cMessage const* const msg) {
  auto current_time = omnetpp::simTime();
  _logger->info("\"simtime\": {}, \"event_type\": \"{}\", \"address\": \"{}\", {}", current_time, event_type, qnode_address, format(msg));
}

void JsonLogger::logQubitState(quisp::modules::QNIC_type qnic_type, int qnic_index, int qubit_index, bool is_busy, bool is_allocated) {
  auto current_time = omnetpp::simTime();
  _logger->info(
      "\"simtime\": {}, \"event_type\": \"QubitStateChange\", \"address\": \"{}\", \"qnic_type\": {}, \"qnic_index\": {}, \"qubit_index\": {}, \"busy\": {}, \"allocated\": {}",
      current_time, qnode_address, qnic_type, qnic_index, qubit_index, is_busy, is_allocated);
}

std::string JsonLogger::format(omnetpp::cMessage const* const msg) {
  auto escape_json = [](const std::string& value) {
    std::ostringstream os;
    for (char ch : value) {
      switch (ch) {
        case '"':
          os << "\\\"";
          break;
        case '\\':
          os << "\\\\";
          break;
        case '\b':
          os << "\\b";
          break;
        case '\f':
          os << "\\f";
          break;
        case '\n':
          os << "\\n";
          break;
        case '\r':
          os << "\\r";
          break;
        case '\t':
          os << "\\t";
          break;
        default:
          if (static_cast<unsigned char>(ch) < 0x20) {
            os << "\\u" << std::hex << std::setfill('0') << std::setw(4) << static_cast<int>(static_cast<unsigned char>(ch)) << std::dec;
          } else {
            os << ch;
          }
      }
    }
    return os.str();
  };
  if (msg == nullptr) {
    return "\"msg_type\": \"Unknown\", \"msg_full_path\": \"\"";
  }
  if (auto* req = dynamic_cast<const quisp::messages::ConnectionSetupRequest*>(msg)) {
    std::stringstream os;
    os << "\"msg_type\": \"ConnectionSetupRequest\"";
    os << ", \"application_id\": " << req->getApplicationId();
    os << ", \"actual_dest_addr\": " << req->getActual_destAddr();
    os << ", \"actual_src_addr\": " << req->getActual_srcAddr();
    os << ", \"num_measure\": " << req->getNum_measure();
    os << ", \"num_required_bell_pairs\": " << req->getNumber_of_required_Bellpairs();
    return os.str();
  }
  if (auto* req = dynamic_cast<const quisp::messages::RejectConnectionSetupRequest*>(msg)) {
    std::stringstream os;
    os << "\"msg_type\": \"RejectConnectionSetupRequest\"";
    os << ", \"application_id\": " << req->getApplicationId();
    os << ", \"actual_dest_addr\": " << req->getActual_destAddr();
    os << ", \"actual_src_addr\": " << req->getActual_srcAddr();
    os << ", \"num_required_bell_pairs\": " << req->getNumber_of_required_Bellpairs();
    return os.str();
  }
  if (auto* req = dynamic_cast<const quisp::messages::ConnectionSetupResponse*>(msg)) {
    std::stringstream os;
    os << "\"msg_type\": \"ConnectionSetupResponse\"";
    os << ", \"application_id\": " << req->getApplicationId();
    os << ", \"actual_dest_addr\": " << req->getActual_destAddr();
    os << ", \"actual_src_addr\": " << req->getActual_srcAddr();
    os << ", \"ruleset_id\": " << req->getRuleSet_id();
    os << ", \"ruleset\": " << req->getRuleSet();
    os << ", \"application_type\": " << req->getApplication_type();
    os << ", \"stack_of_qnode_indices\": [";
    for (int i = 0; i < req->getStack_of_QNodeIndexesArraySize(); i++) {
      if (i != 0) os << ", ";
      os << req->getStack_of_QNodeIndexes(i);
    }
    os << "]";
    return os.str();
  }

  return "\"msg_type\": \"Unknown\", \"msg_full_path\": \"" + escape_json(msg->getFullPath()) + "\"";
}

void JsonLogger::logBellPairInfo(const std::string& event_type, int partner_addr, quisp::modules::QNIC_type qnic_type, int qnic_index, int qubit_index) {
  auto current_time = omnetpp::simTime();
  _logger->info("\"simtime\": {}, \"event_type\": \"BellPair{}\", \"address\": \"{}\", \"partner_addr\": {}, \"qnic_type\": {}, \"qnic_index\": {}, \"qubit_index\": {}",
                current_time, event_type, qnode_address, partner_addr, qnic_type, qnic_index, qubit_index);
}

void JsonLogger::logEvent(const std::string& event_type, const std::string& event_payload_json) {
  auto current_time = omnetpp::simTime();
  _logger->info("\"simtime\": {}, \"event_type\": \"{}\", \"event_payload\": {}", current_time, event_type, event_payload_json);
}

}  // namespace quisp::modules::Logger
