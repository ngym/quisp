#pragma once
#include <modules/Logger/ILogger.h>
#include <iostream>
#include <string>
namespace quisp_test::Logger {
using quisp::modules::Logger::ILogger;
class TestLogger : public ILogger {
 public:
  TestLogger() {}
  ~TestLogger() {}
  void logPacket(const std::string& event_type, omnetpp::cMessage const* const msg) override { std::cout << "logPacket: " << event_type << std::endl; };
  void logQubitState(quisp::modules::QNIC_type qnic_type, int qnic_index, int qubit_index, bool is_busy, bool is_allocated) override {
    std::cout << "logQubitState: " << qnic_index << ", " << qubit_index << ", busy: " << is_busy << ", allocated: " << is_allocated << std::endl;
  };

  void logBellPairInfo(const std::string& event_type, int partner_addr, quisp::modules::QNIC_type qnic_type, int qnic_index, int qubit_index) override{};
  void logEvent(const std::string& event_type, const std::string& event_payload_json) override {
    log_event_type = event_type;
    log_event_payload = event_payload_json;
    log_event_count++;
  };

  void setModule(omnetpp::cModule const* const mod) override {}
  void setQNodeAddress(int addr) override {}
  std::string log_event_type;
  std::string log_event_payload;
  int log_event_count = 0;
};
}  // namespace quisp_test::Logger
