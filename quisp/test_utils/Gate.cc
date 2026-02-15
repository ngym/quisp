#include "Gate.h"
#include <omnetpp/cenvir.h>
#include "omnetpp/cmessage.h"

namespace quisp_test {
namespace gate {

using omnetpp::cSimulation;

TempGate::TempGate() {}
bool TempGate::deliver(cMessage *msg, const omnetpp::SendOptions &options, simtime_t at) { return true; }

TestGate::TestGate(cModule *mod, const char *name) : TestGate(mod, name, true) {}

TestGate::TestGate(cModule *mod, const char *name, bool is_connected) : is_connected_(is_connected) {
  desc = new omnetpp::cGate::Desc;
  // only for output gate
  desc->name = new omnetpp::cGate::Name{name, omnetpp::cGate::Type::OUTPUT};
  desc->owner = mod;
  // output gate needs nextGate to be filled. actually temp_gate do nothing.
  nextGate = is_connected_ ? &temp_gate : nullptr;
  desc->setOutputGate(this);
}

void TestGate::setConnected(bool is_connected) {
  is_connected_ = is_connected;
  nextGate = is_connected_ ? &temp_gate : nullptr;
}

/**
 * \brief this method called when a module sent cMessage to this gate.
 * and then store the msg into `messages`
 */
bool TestGate::deliver(cMessage *msg, const omnetpp::SendOptions &options, simtime_t at) {
  messages.push_back(msg->dup());
  return true;
}

}  // namespace gate
}  // namespace quisp_test
