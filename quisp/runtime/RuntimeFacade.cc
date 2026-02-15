#include "RuntimeFacade.h"

namespace quisp::runtime {

RuntimeFacade::RuntimeFacade(std::unique_ptr<Runtime::ICallBack> &&callback) : manager(std::move(callback)) {}

void RuntimeFacade::submitRuleSet(const RuleSet& ruleset) { manager.acceptRuleSet(ruleset); }

void RuntimeFacade::acceptRuleSet(const RuleSet& ruleset) { submitRuleSet(ruleset); }

Runtime *RuntimeFacade::findById(unsigned long long ruleset_id) { return manager.findById(ruleset_id); }

void RuntimeFacade::exec() { manager.exec(); }

std::vector<Runtime>::iterator RuntimeFacade::begin() { return manager.begin(); }
std::vector<Runtime>::iterator RuntimeFacade::end() { return manager.end(); }
std::vector<Runtime>::reference RuntimeFacade::at(size_t index) { return manager.at(index); }
size_t RuntimeFacade::size() const { return manager.size(); }

RuntimeStateSnapshot RuntimeFacade::snapshotState(size_t index) const {
  return state_store.snapshot(manager.at(index));
}

void RuntimeFacade::assignMessageToRuleSet(unsigned long long ruleset_id, int shared_rule_tag, MessageRecord msg_content) {
  auto *runtime = manager.findById(ruleset_id);
  if (runtime == nullptr) return;
  runtime->assignMessageToRuleSet(shared_rule_tag, msg_content);
}

void RuntimeFacade::allocateResources(modules::BellPairStore& bell_pair_store, modules::QNIC_type qnic_type, int qnic_index) {
  for (auto &runtime : manager) {
    auto &partners = runtime.getPartners();
    for (auto &partner_addr : partners) {
      auto range = bell_pair_store.getBellPairsRange(qnic_type, qnic_index, partner_addr.val);
      for (auto it = range.first; it != range.second; ++it) {
        auto qubit_record = it->second;
        if (!qubit_record->isAllocated()) {
          qubit_record->setAllocated(true);
          runtime.assignQubitToRuleSet(partner_addr, qubit_record);
        }
      }
    }
  }
}

}  // namespace quisp::runtime
