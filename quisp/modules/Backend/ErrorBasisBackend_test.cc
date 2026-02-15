#include <gtest/gtest.h>

#include <memory>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

#include "PhysicalServiceFacade.h"
#include "backends/interfaces/IConfiguration.h"
#include "backends/interfaces/IQubit.h"
#include "backends/interfaces/IQubitId.h"
#include "backends/interfaces/IQuantumBackend.h"
#include "modules/QNIC/StationaryQubit/QubitId.h"

using quisp::backends::abstract::EigenvalueResult;
using quisp::backends::abstract::IConfiguration;
using quisp::backends::abstract::IQubit;
using quisp::backends::abstract::IQubitId;
using quisp::backends::abstract::IQuantumBackend;
using quisp::modules::backend::MeasureBasis;
using quisp::modules::backend::PhysicalServiceFacade;
using quisp::modules::backend::QubitHandle;
using quisp::modules::qubit_id::QubitId;

namespace {

class FakeQubit : public IQubit {
 public:
  explicit FakeQubit(std::unique_ptr<IQubitId> id) : id_(std::move(id)) {}

  const IQubitId* const getId() const override { return id_.get(); }
  void setFree() override { ++set_free_count; }

  void gateX() override { ++x_count; }
  void gateY() override { ++y_count; }
  void gateZ() override { ++z_count; }
  void gateH() override { ++h_count; }
  void gateS() override { ++s_count; }
  void gateSdg() override { ++sdg_count; }
  void gateCNOT(IQubit* const target) override {
    ++cnot_count;
    cnot_targets.push_back(dynamic_cast<FakeQubit*>(target));
  }

  void noiselessH() override { ++noiseless_h_count; }
  void noiselessX() override { ++noiseless_x_count; }
  void noiselessZ() override { ++noiseless_z_count; }
  void noiselessCNOT(IQubit* const target) override {
    ++noiseless_cnot_count;
    noiseless_cnot_targets.push_back(dynamic_cast<FakeQubit*>(target));
  }
  EigenvalueResult noiselessMeasureX() override { return noiseless_measure_plus ? EigenvalueResult::PLUS_ONE : EigenvalueResult::MINUS_ONE; }
  EigenvalueResult noiselessMeasureZ() override { return noiseless_measure_plus ? EigenvalueResult::PLUS_ONE : EigenvalueResult::MINUS_ONE; }
  EigenvalueResult noiselessMeasureZ(EigenvalueResult forced_result) override { return forced_result; }
  EigenvalueResult noiselessMeasureX(EigenvalueResult forced_result) override { return forced_result; }

  EigenvalueResult measureX() override { return measure_x_plus ? EigenvalueResult::PLUS_ONE : EigenvalueResult::MINUS_ONE; }
  EigenvalueResult measureY() override { return measure_y_plus ? EigenvalueResult::PLUS_ONE : EigenvalueResult::MINUS_ONE; }
  EigenvalueResult measureZ() override { return measure_z_plus ? EigenvalueResult::PLUS_ONE : EigenvalueResult::MINUS_ONE; }

  int set_free_count = 0;
  int x_count = 0;
  int y_count = 0;
  int z_count = 0;
  int h_count = 0;
  int s_count = 0;
  int sdg_count = 0;
  int cnot_count = 0;
  int noiseless_h_count = 0;
  int noiseless_x_count = 0;
  int noiseless_z_count = 0;
  int noiseless_cnot_count = 0;

  bool measure_x_plus = true;
  bool measure_y_plus = false;
  bool measure_z_plus = true;
  bool noiseless_measure_plus = true;

  std::vector<FakeQubit*> cnot_targets;
  std::vector<FakeQubit*> noiseless_cnot_targets;

 private:
  std::unique_ptr<IQubitId> id_;
};

class FakeBackend : public IQuantumBackend {
 public:
  IQubit* createQubit(const IQubitId* id, std::unique_ptr<IConfiguration> /*configuration*/) override {
    return createQubitInternal(id);
  }

  IQubit* createQubit(const IQubitId* id) override { return createQubitInternal(id); }

  IQubit* getQubit(const IQubitId* id) override {
    auto it = qubits.find(key(*id));
    if (it == qubits.end()) {
      throw std::runtime_error("qubit not found");
    }
    return it->second.get();
  }

  IQubit* createShortLiveQubit() override { return getOrCreateShortLiveQubit(); }

  IQubit* getShortLiveQubit() override {
    if (short_live_ == nullptr) {
      return createShortLiveQubit();
    }
    return short_live_.get();
  }

  void returnToPool(IQubit*) override {}
  void deleteQubit(const IQubitId* id) override { qubits.erase(key(*id)); }
  std::unique_ptr<IConfiguration> getDefaultConfiguration() const override { return std::make_unique<IConfiguration>(); }
  const omnetpp::SimTime& getSimTime() override { return sim_time; }
  void setSimTime(omnetpp::SimTime time) override { sim_time = time; }

 private:
  static std::string key(const IQubitId& id_ref) {
    const auto* qid = dynamic_cast<const QubitId*>(&id_ref);
    if (qid == nullptr) {
      throw std::runtime_error("unsupported qubit id type");
    }
    return std::to_string(qid->node_addr) + "," + std::to_string(qid->qnic_index) + "," + std::to_string(qid->qnic_type) + "," +
           std::to_string(qid->qubit_addr);
  }

  IQubit* createQubitInternal(const IQubitId* id) {
    if (id == nullptr) {
      throw std::runtime_error("null qubit id");
    }
    const auto* qid = dynamic_cast<const QubitId*>(id);
    if (qid == nullptr) {
      delete id;
      throw std::runtime_error("unsupported qubit id type");
    }
    auto k = key(*qid);
    auto it = qubits.find(k);
    if (it != qubits.end()) {
      delete id;
      throw std::runtime_error("qubit already exists");
    }
    auto inserted = qubits.emplace(
        k,
        std::make_unique<FakeQubit>(std::make_unique<QubitId>(qid->node_addr, qid->qnic_index, qid->qnic_type, qid->qubit_addr)));
    delete id;
    return inserted.first->second.get();
  }

  IQubit* getOrCreateShortLiveQubit() {
    if (short_live_ == nullptr) {
      ++short_live_created_count;
      short_live_ = std::make_unique<FakeQubit>(std::make_unique<QubitId>(-1, -1, -1, short_live_created_count));
    }
    return short_live_.get();
  }

  mutable omnetpp::SimTime sim_time;
  std::unordered_map<std::string, std::unique_ptr<IQubit>> qubits;
  int short_live_created_count = 0;
  std::unique_ptr<IQubit> short_live_;
};

QubitHandle handleFrom(int node, int idx, int type, int q) {
  return QubitHandle{node, idx, type, q};
}

TEST(ErrorBasisBackendContractTest, ApplyGateRoutesToBackendQubits) {
  FakeBackend backend;
  auto* qubit = static_cast<FakeQubit*>(backend.createQubit(new QubitId(1, 0, 0, 7)));
  ASSERT_NE(qubit, nullptr);

  PhysicalServiceFacade facade{&backend};
  EXPECT_TRUE(facade.applyGate("X", {handleFrom(1, 0, 0, 7)}).success);
  EXPECT_EQ(qubit->x_count, 1);
  EXPECT_TRUE(facade.applyGate("H", {handleFrom(1, 0, 0, 7)}).success);
  EXPECT_EQ(qubit->h_count, 1);
  EXPECT_TRUE(facade.applyGate("Sdg", {handleFrom(1, 0, 0, 7)}).success);
  EXPECT_EQ(qubit->sdg_count, 1);
}

TEST(ErrorBasisBackendContractTest, ApplyGateSupportsCnot) {
  FakeBackend backend;
  auto* source = static_cast<FakeQubit*>(backend.createQubit(new QubitId(2, 0, 0, 1)));
  auto* target = static_cast<FakeQubit*>(backend.createQubit(new QubitId(2, 0, 0, 2)));
  ASSERT_NE(source, nullptr);
  ASSERT_NE(target, nullptr);

  PhysicalServiceFacade facade{&backend};
  EXPECT_TRUE(facade.applyGate("CNOT", {handleFrom(2, 0, 0, 1), handleFrom(2, 0, 0, 2)}).success);
  EXPECT_EQ(source->cnot_count, 1);
  ASSERT_EQ(source->cnot_targets.size(), 1);
  EXPECT_EQ(source->cnot_targets.front(), target);
}

TEST(ErrorBasisBackendContractTest, ApplyNoiselessGateRoutesToNoiselessBackendOps) {
  FakeBackend backend;
  auto* source = static_cast<FakeQubit*>(backend.createQubit(new QubitId(9, 0, 0, 1)));
  auto* target = static_cast<FakeQubit*>(backend.createQubit(new QubitId(9, 0, 0, 2)));
  ASSERT_NE(source, nullptr);
  ASSERT_NE(target, nullptr);

  PhysicalServiceFacade facade{&backend};
  EXPECT_TRUE(facade.applyNoiselessGate("X", {handleFrom(9, 0, 0, 1)}).success);
  EXPECT_EQ(source->noiseless_x_count, 1);
  EXPECT_TRUE(facade.applyNoiselessGate("Z", {handleFrom(9, 0, 0, 1)}).success);
  EXPECT_EQ(source->noiseless_z_count, 1);
  EXPECT_TRUE(facade.applyNoiselessGate("H", {handleFrom(9, 0, 0, 1)}).success);
  EXPECT_EQ(source->noiseless_h_count, 1);
  EXPECT_TRUE(facade.applyNoiselessGate("CNOT", {handleFrom(9, 0, 0, 1), handleFrom(9, 0, 0, 2)}).success);
  ASSERT_EQ(source->noiseless_cnot_count, 1);
  ASSERT_EQ(source->noiseless_cnot_targets.size(), 1);
  EXPECT_EQ(source->noiseless_cnot_targets.front(), target);
}

TEST(ErrorBasisBackendContractTest, MeasureReturnsObservedOutcome) {
  FakeBackend backend;
  auto* qubit = static_cast<FakeQubit*>(backend.createQubit(new QubitId(3, 0, 0, 9)));
  ASSERT_NE(qubit, nullptr);
  qubit->measure_x_plus = true;
  qubit->measure_y_plus = false;
  qubit->measure_z_plus = true;

  PhysicalServiceFacade facade{&backend};
  auto x = facade.measure(handleFrom(3, 0, 0, 9), MeasureBasis::X);
  auto y = facade.measure(handleFrom(3, 0, 0, 9), MeasureBasis::Y);
  auto z = facade.measure(handleFrom(3, 0, 0, 9), MeasureBasis::Z);

  EXPECT_TRUE(x.success);
  EXPECT_TRUE(x.measured_plus);
  EXPECT_TRUE(y.success);
  EXPECT_FALSE(y.measured_plus);
  EXPECT_TRUE(z.success);
  EXPECT_TRUE(z.measured_plus);

  auto bad = facade.measure(handleFrom(4, 0, 0, 1), MeasureBasis::X);
  EXPECT_FALSE(bad.success);
}

TEST(ErrorBasisBackendContractTest, MeasureNoiselessForcesPlusAndSupportsMeasure) {
  FakeBackend backend;
  auto* qubit = static_cast<FakeQubit*>(backend.createQubit(new QubitId(10, 0, 0, 3)));
  ASSERT_NE(qubit, nullptr);
  qubit->noiseless_measure_plus = false;

  PhysicalServiceFacade facade{&backend};
  auto forced = facade.measureNoiseless(handleFrom(10, 0, 0, 3), MeasureBasis::X, true);
  auto regular = facade.measureNoiseless(handleFrom(10, 0, 0, 3), MeasureBasis::Z, false);

  EXPECT_TRUE(forced.success);
  EXPECT_TRUE(forced.measured_plus);
  EXPECT_TRUE(regular.success);
  EXPECT_FALSE(regular.measured_plus);
}

TEST(ErrorBasisBackendContractTest, GenerateEntanglementCallsNoiselessOps) {
  FakeBackend backend;
  auto* source = static_cast<FakeQubit*>(backend.createQubit(new QubitId(5, 0, 0, 1)));
  auto* target = static_cast<FakeQubit*>(backend.createShortLiveQubit());
  ASSERT_NE(source, nullptr);
  ASSERT_NE(target, nullptr);

  PhysicalServiceFacade facade{&backend};
  auto result = facade.generateEntanglement(handleFrom(5, 0, 0, 1), handleFrom(-1, -1, -1, 1));
  EXPECT_TRUE(result.success);
  EXPECT_EQ(source->noiseless_h_count, 1);
  EXPECT_EQ(source->noiseless_cnot_count, 1);
  EXPECT_EQ(source->noiseless_cnot_targets.size(), 1);
}

TEST(ErrorBasisBackendContractTest, UnknownGateReturnsFailure) {
  FakeBackend backend;
  backend.createQubit(new QubitId(6, 0, 0, 2));

  PhysicalServiceFacade facade{&backend};
  EXPECT_FALSE(facade.applyGate("INVALID", {handleFrom(6, 0, 0, 2)}).success);
  EXPECT_FALSE(facade.applyNoiselessGate("INVALID", {handleFrom(6, 0, 0, 2)}).success);
  EXPECT_FALSE(facade.measureNoiseless(handleFrom(6, 0, 0, 2), MeasureBasis::Y, true).success);
}

}  // namespace
