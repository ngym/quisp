#include "RuntimeStateStore.h"

#include "Runtime.h"

namespace quisp::runtime {

RuntimeStateSnapshot RuntimeStateStore::snapshot(const Runtime& runtime) const {
  RuntimeStateSnapshot snapshot;
  snapshot.terminated = runtime.isTerminated();
  snapshot.active_partners = runtime.partnerCount();
  snapshot.qubit_resources = runtime.qubitCount();
  snapshot.message_queues = runtime.messageQueueCount();
  snapshot.named_qubits = runtime.namedQubitCount();
  return snapshot;
}

}  // namespace quisp::runtime
