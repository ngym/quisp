#pragma once

#include <cstddef>
#include <memory>
#include <vector>

#include "modules/QNIC.h"

#include "modules/QRSA/RuleEngine/BellPairStore/BellPairStore.h"
#include "Runtime.h"
#include "RuntimeManager.h"
#include "RuntimeStateStore.h"

namespace quisp::runtime {

class RuntimeFacade {
 public:
  explicit RuntimeFacade(std::unique_ptr<Runtime::ICallBack> &&callback);

  void submitRuleSet(const RuleSet& ruleset);
  void acceptRuleSet(const RuleSet& ruleset);
  void assignMessageToRuleSet(unsigned long long ruleset_id, int shared_rule_tag, MessageRecord msg_content);
  void allocateResources(modules::BellPairStore& bell_pair_store, modules::QNIC_type qnic_type, int qnic_index);

  Runtime *findById(unsigned long long ruleset_id);
  void exec();

  std::vector<Runtime>::iterator begin();
  std::vector<Runtime>::iterator end();
  std::vector<Runtime>::reference at(size_t index);
  size_t size() const;

  RuntimeStateSnapshot snapshotState(size_t index) const;

 private:
  RuntimeManager manager;
  RuntimeStateStore state_store;
};

}  // namespace quisp::runtime
