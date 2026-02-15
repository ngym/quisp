/** \file RuleProtocolExecutionContext.h
 *
 *  \brief Rule protocol execution context for RuleEngine.
 */
#pragma once

#include <vector>

#include "messages/BSA_ipc_messages_m.h"
#include "messages/classical_messages.h"
#include "messages/link_generation_messages_m.h"
#include "messages/purification_messages_m.h"

namespace quisp::modules {
class RuleEngine;

class RuleProtocolExecutionContext {
 public:
  explicit RuleProtocolExecutionContext(RuleEngine& engine);

  void handleSingleClickResult(messages::SingleClickResult *click_result);
  void handleMSMResult(messages::MSMResult *msm_result);
  void handleLinkGenerationResult(messages::CombinedBSAresults *bsa_result);
  void handleStopEmitting(messages::StopEmitting *stop_emit);
  void handlePurificationResult(messages::PurificationResult *result);
  void handleSwappingResult(messages::SwappingResult *result);
  void handleRuleSetForwarding(const messages::InternalRuleSetForwarding *pkt);
  void handleRuleSetForwardingApplication(const messages::InternalRuleSetForwarding_Application *pkt);
  void handleLinkTomographyRuleSet(const messages::LinkTomographyRuleSet *pkt);

 private:
  RuleEngine& engine_;
};
}  // namespace quisp::modules
