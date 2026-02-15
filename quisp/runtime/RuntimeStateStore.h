#pragma once

#include <cstddef>

namespace quisp::runtime {

class Runtime;

struct RuntimeStateSnapshot {
  bool terminated = false;
  std::size_t active_partners = 0;
  std::size_t qubit_resources = 0;
  std::size_t message_queues = 0;
  std::size_t named_qubits = 0;
};

class RuntimeStateStore {
 public:
  RuntimeStateSnapshot snapshot(const Runtime& runtime) const;
};

}  // namespace quisp::runtime
