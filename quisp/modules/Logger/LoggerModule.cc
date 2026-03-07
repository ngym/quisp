#include "LoggerModule.h"
#include <set>
#include <string>
#include <modules/Logger/DisabledLogger.h>
#include <nlohmann/json.hpp>
#include <spdlog/async.h>
#include <spdlog/sinks/basic_file_sink.h>
#include <spdlog/spdlog.h>
#include "JsonLogger.h"

namespace quisp::modules::Logger {

namespace {

bool isTopologyNode(omnetpp::cModule* module) {
  return module != nullptr && module->hasPar("address");
}

omnetpp::cModule* toTopLevelTopologyNode(omnetpp::cModule* module, omnetpp::cModule* network) {
  while (module != nullptr && module != network) {
    if (isTopologyNode(module) && module->getParentModule() == network) {
      return module;
    }
    module = module->getParentModule();
  }
  return nullptr;
}

omnetpp::cModule* firstTopologyPeerAlongPath(omnetpp::cGate* start_gate, omnetpp::cModule* network, omnetpp::cModule* source_node) {
  std::set<omnetpp::cGate*> visited;
  auto* gate = start_gate;
  while (gate != nullptr && visited.insert(gate).second) {
    gate = gate->getNextGate();
    if (gate == nullptr) {
      break;
    }
    auto* peer = toTopLevelTopologyNode(gate->getOwnerModule(), network);
    if (peer != nullptr && peer != source_node) {
      return peer;
    }
  }
  return nullptr;
}

std::string nodeIdOf(omnetpp::cModule* module) {
  if (module == nullptr || !module->hasPar("address")) {
    return "";
  }
  return std::to_string(module->par("address").intValue());
}

void addDisplayCoordinates(nlohmann::json& node, omnetpp::cModule* module) {
  if (module == nullptr) {
    return;
  }
  auto& display = module->getDisplayString();
  const char* raw_x = display.getTagArg("p", 0);
  const char* raw_y = display.getTagArg("p", 1);
  if (raw_x != nullptr && *raw_x != '\0') {
    node["x"] = std::atof(raw_x);
  }
  if (raw_y != nullptr && *raw_y != '\0') {
    node["y"] = std::atof(raw_y);
  }
}

}  // namespace

LoggerModule::LoggerModule() {}

LoggerModule::~LoggerModule() {
  if (logger_type == LoggerType::JsonLogger) {
    if (spdlog_logger != nullptr) spdlog::shutdown();
    return;
  }
}

void LoggerModule::initialize() {
  if (!par("enabled_log").boolValue()) {
    logger_type = LoggerType::Disabled;
    return;
  }
  logger_type = toLoggerType(par("logger"));
  if (logger_type == LoggerType::JsonLogger) {
    if (spdlog_logger != nullptr) return;

#ifndef __EMSCRIPTEN__
    spdlog_logger = spdlog::basic_logger_mt<spdlog::async_factory>("default_sim_result_logger", trimQuotes(par("log_filename").str()));
#else
    // if the platform is WebAssembly, use single thread logger
    spdlog_logger = spdlog::basic_logger_st("default_sim_result_logger", trimQuotes(par("log_filename").str()));
#endif
    emitTopologySnapshot();
    return;
  }
  error("unknown logger specified: %s", par("logger").str().c_str());
}

void LoggerModule::finish() {
  if (logger_type == LoggerType::JsonLogger) {
    if (spdlog_logger != nullptr) spdlog_logger->flush();
  }
}

ILogger* LoggerModule::getLogger() {
  if (logger_type == LoggerType::Disabled) return new DisabledLogger();
  if (logger_type == LoggerType::JsonLogger) {
    if (spdlog_logger == nullptr) error("failed to instantiate logger. spdlog is not initialized.");
    return new JsonLogger(spdlog_logger);
  }
  error("valid logger is not specified.");
  return nullptr;
}

std::string LoggerModule::trimQuotes(std::string s) {
  if (s.length() == 0) return s;
  if (s[0] == '\"') s = s.substr(1);
  if (s[s.length() - 1] == '\"') s = s.substr(0, s.length() - 1);
  return s;
}

LoggerType LoggerModule::toLoggerType(const std::string& s) {
  if (s == "JsonLogger") return LoggerType::JsonLogger;
  return LoggerType::Unknown;
}

void LoggerModule::emitTopologySnapshot() {
  if (spdlog_logger == nullptr) {
    return;
  }

  auto* network = getParentModule();
  if (network == nullptr) {
    return;
  }

  nlohmann::json payload;
  payload["nodes"] = nlohmann::json::array();
  payload["edges"] = nlohmann::json::array();

  std::vector<omnetpp::cModule*> topology_nodes;
  for (omnetpp::cModule::SubmoduleIterator it(network); !it.end(); ++it) {
    auto* submodule = *it;
    if (!isTopologyNode(submodule)) {
      continue;
    }
    topology_nodes.push_back(submodule);
    nlohmann::json node = {
        {"id", nodeIdOf(submodule)},
        {"label", submodule->getFullName()},
        {"module", submodule->getFullPath()},
    };
    addDisplayCoordinates(node, submodule);
    payload["nodes"].push_back(node);
  }

  std::set<std::pair<std::string, std::string>> seen_edges;
  for (auto* node : topology_nodes) {
    for (omnetpp::cModule::GateIterator gate_it(node); !gate_it.end(); ++gate_it) {
      auto* gate = *gate_it;
      if (gate == nullptr || gate->getType() != omnetpp::cGate::OUTPUT || !gate->isConnected()) {
        continue;
      }
      auto* peer = firstTopologyPeerAlongPath(gate, network, node);
      if (peer == nullptr || peer == node) {
        continue;
      }
      auto src = nodeIdOf(node);
      auto dst = nodeIdOf(peer);
      if (src.empty() || dst.empty() || src == dst) {
        continue;
      }
      if (dst < src) {
        std::swap(src, dst);
      }
      if (!seen_edges.insert({src, dst}).second) {
        continue;
      }
      payload["edges"].push_back({
          {"src", src},
          {"dst", dst},
          {"kind", "topology"},
      });
    }
  }

  spdlog_logger->info("\"simtime\": {}, \"event_type\": \"topology_snapshot\", \"event_payload\": {}", omnetpp::simTime(), payload.dump());
  spdlog_logger->flush();
}

}  // namespace quisp::modules::Logger
