/** \file RuleProtocolExecutionContext.cc
 *
 *  \brief Execution context for protocol-level handling in RuleEngine.
 */
#include "RuleProtocolExecutionContext.h"

#include <iterator>

#include "RuleEngine.h"

#include <nlohmann/json.hpp>

#include "modules/QNIC.h"
#include "rules/RuleSet.h"

namespace quisp::modules {

namespace {
constexpr auto kMSMResultKind = 6;
}

RuleProtocolExecutionContext::RuleProtocolExecutionContext(RuleEngine& engine) : engine_(engine) {}

void RuleProtocolExecutionContext::handleSingleClickResult(messages::SingleClickResult *click_result) {
  auto qnic_index = click_result->getQnicIndex();
  auto &msm_info = engine_.msm_info_map[qnic_index];
  auto qubit_index = msm_info.qubit_info_map[msm_info.iteration_index];
  auto *msm_result = new messages::MSMResult();
  msm_result->setQnicIndex(msm_info.partner_qnic_index);
  msm_result->setQnicType(QNIC_RP);
  msm_result->setPhotonIndex(msm_info.photon_index_counter);
  msm_result->setSuccess(click_result->getClickResult().success);
  msm_result->setCorrectionOperation(click_result->getClickResult().correction_operation);
  msm_result->setSrcAddr(engine_.parentAddress);
  msm_result->setDestAddr(msm_info.partner_address);
  msm_result->setKind(kMSMResultKind);
  if (click_result->getClickResult().success) {
    msm_info.qubit_postprocess_info[msm_info.photon_index_counter].qubit_index = qubit_index;
    msm_info.qubit_postprocess_info[msm_info.photon_index_counter].correction_operation =
        click_result->getClickResult().correction_operation;
    msm_info.iteration_index++;
  } else {
    engine_.realtime_controller->ReInitialize_StationaryQubit(qnic_index, qubit_index, QNIC_RP, false);
    engine_.qnic_store->setQubitBusy(QNIC_RP, qnic_index, qubit_index, false);
  }
  engine_.send(msm_result, "RouterPort$o");
}

void RuleProtocolExecutionContext::handleMSMResult(messages::MSMResult *msm_result) {
  auto qnic_index = msm_result->getQnicIndex();
  auto &msm_info = engine_.msm_info_map[qnic_index];
  auto qubit_itr = msm_info.qubit_postprocess_info.find(msm_result->getPhotonIndex());
  // local: fail | partner: success
  // qubit on photon index is not included in msm_info
  if (qubit_itr == msm_info.qubit_postprocess_info.end()) {
    return;
  }
  RuleEngine::QubitInfo qubit_info = qubit_itr->second;
  auto qubit_index = qubit_info.qubit_index;
  // local: success | partner: fail
  // qubit on photon index is included in msm_info but the partner sends fail
  if (!msm_result->getSuccess()) {
    engine_.realtime_controller->ReInitialize_StationaryQubit(qnic_index, qubit_index, QNIC_RP, false);
    engine_.qnic_store->setQubitBusy(QNIC_RP, qnic_index, qubit_index, false);
  }
  // local: success | partner: success
  // qubit on photon index is included in msm_info and the partner sends success
  else {
    auto *qubit_record = engine_.qnic_store->getQubitRecord(QNIC_RP, qnic_index, qubit_index);
    // condition whether to apply Z gate or not
    bool is_phi_minus = qubit_info.correction_operation != msm_result->getCorrectionOperation();
    // restrict correction operation only on one side
    bool is_younger_address = engine_.parentAddress < msm_info.partner_address;
    if (is_phi_minus && is_younger_address) {
      engine_.realtime_controller->applyZGate(qubit_record);
    }
    engine_.bell_pair_store.insertEntangledQubit(msm_info.partner_address, qubit_record);
  }
}

void RuleProtocolExecutionContext::handleLinkGenerationResult(messages::CombinedBSAresults *bsa_result) {
  auto type = bsa_result->getQnicType();
  auto qnic_index = bsa_result->getQnicIndex();
  auto num_success = bsa_result->getSuccessCount();
  auto partner_address = bsa_result->getNeighborAddress();
  auto &emitted_indices = engine_.emitted_photon_order_map[{type, qnic_index}];
  for (int i = num_success - 1; i >= 0; i--) {
    auto emitted_index = bsa_result->getSuccessfulPhotonIndices(i);
    auto qubit_index = emitted_indices[emitted_index];
    auto *qubit_record = engine_.qnic_store->getQubitRecord(type, qnic_index, qubit_index);
    auto iterator = emitted_indices.begin();
    std::advance(iterator, emitted_index);
    engine_.bell_pair_store.insertEntangledQubit(partner_address, qubit_record);
    emitted_indices.erase(iterator);

    auto correction_operation = bsa_result->getCorrectionOperationList(i);
    if (correction_operation == PauliOperator::X) {
      engine_.realtime_controller->applyXGate(qubit_record);
    } else if (correction_operation == PauliOperator::Z) {
      engine_.realtime_controller->applyZGate(qubit_record);
    } else if (correction_operation == PauliOperator::Y) {
      engine_.realtime_controller->applyYGate(qubit_record);
    }
  }
}

void RuleProtocolExecutionContext::handleStopEmitting(messages::StopEmitting *stop_emit) {
  int qnic_index = stop_emit->getQnic_address();
  auto &msm_info = engine_.msm_info_map[qnic_index];
  // only do the following procedure for MSM links
  if (msm_info.photon_index_counter == 0) {
    return;
  }
  auto *stop_epps_emission = new messages::StopEPPSEmission();
  stop_epps_emission->setSrcAddr(engine_.parentAddress);
  stop_epps_emission->setDestAddr(msm_info.epps_address);
  engine_.send(stop_epps_emission, "RouterPort$o");
}

void RuleProtocolExecutionContext::handlePurificationResult(messages::PurificationResult *result) {
  auto ruleset_id = result->getRulesetId();
  auto shared_rule_tag = result->getSharedRuleTag();
  auto sequence_number = result->getSequenceNumber();
  auto measurement_result = result->getMeasurementResult();
  auto purification_protocol = result->getProtocol();
  std::vector<int> message_content = {sequence_number, measurement_result, purification_protocol};
  engine_.runtimes.assignMessageToRuleSet(ruleset_id, shared_rule_tag, message_content);
}

void RuleProtocolExecutionContext::handleSwappingResult(messages::SwappingResult *result) {
  auto ruleset_id = result->getRulesetId();
  auto shared_rule_tag = result->getSharedRuleTag();
  auto sequence_number = result->getSequenceNumber();
  auto correction_frame = result->getCorrectionFrame();
  auto new_partner_addr = result->getNewPartner();
  std::vector<int> message_content = {sequence_number, correction_frame, new_partner_addr};
  engine_.runtimes.assignMessageToRuleSet(ruleset_id, shared_rule_tag, message_content);
}

void RuleProtocolExecutionContext::handleRuleSetForwarding(const messages::InternalRuleSetForwarding *pkt) {
  auto serialized_ruleset = pkt->getRuleSet().dump();
  rules::RuleSet ruleset(0, 0);
  ruleset.deserialize_json(nlohmann::json::parse(serialized_ruleset));
  engine_.runtimes.submitRuleSet(ruleset.construct());
}

void RuleProtocolExecutionContext::handleRuleSetForwardingApplication(const messages::InternalRuleSetForwarding_Application *pkt) {
  auto application_type = pkt->getApplication_type();
  if (application_type != 0) {
    return;
  }
  auto serialized_ruleset = pkt->getRuleSet().dump();
  rules::RuleSet ruleset(0, 0);
  ruleset.deserialize_json(nlohmann::json::parse(serialized_ruleset));
  engine_.runtimes.submitRuleSet(ruleset.construct());
}

void RuleProtocolExecutionContext::handleLinkTomographyRuleSet(const messages::LinkTomographyRuleSet *pkt) {
  auto *ruleset = pkt->getRuleSet();
  engine_.runtimes.submitRuleSet(ruleset->construct());
}

}  // namespace quisp::modules
