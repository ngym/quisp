#include <cstdlib>
#include <gtest/gtest.h>

#include <memory>
#include <string>
#include <vector>
#include <optional>

#include "QutipBackend.h"
#include "backends/interfaces/IConfiguration.h"
#include "backends/interfaces/IQuantumBackend.h"
#include "backends/interfaces/IQubit.h"
#include "backends/interfaces/IQubitId.h"

namespace {
using omnetpp::SimTime;
using quisp::backends::abstract::IConfiguration;
using quisp::backends::abstract::IQuantumBackend;
using quisp::backends::abstract::IQubit;
using quisp::backends::abstract::IQubitId;
using quisp::modules::backend::BackendContext;
using quisp::modules::backend::PhysicalOperation;
using quisp::modules::backend::QubitHandle;
using quisp::modules::backend::QutipBackend;

bool qutipRuntimeAvailable();

class NullQuantumBackend : public IQuantumBackend {
 public:
  NullQuantumBackend() = default;

  IQubit* createQubit(const IQubitId* id, std::unique_ptr<IConfiguration> conf) override {
    delete id;
    (void)conf;
    return nullptr;
  }

  IQubit* createQubit(const IQubitId* id) override {
    delete id;
    return nullptr;
  }

  IQubit* createShortLiveQubit() override { return nullptr; }
  IQubit* getQubit(const IQubitId* id) override {
    delete id;
    return nullptr;
  }
  IQubit* getShortLiveQubit() override { return nullptr; }
  void returnToPool(IQubit*) override {}
  void deleteQubit(const IQubitId* id) override { delete id; }
  std::unique_ptr<IConfiguration> getDefaultConfiguration() const override { return std::make_unique<IConfiguration>(); }
  const SimTime& getSimTime() override {
    if (!sim_time_.has_value()) {
      sim_time_ = SimTime();
    }
    return sim_time_.value();
  }
  void setSimTime(SimTime time) override { (void)time; }

 private:
  std::optional<SimTime> sim_time_;
};

BackendContext defaultContext() {
  BackendContext context;
  context.seed = 123;
  context.now = 0;
  context.scenario_id = "qutip-test";
  context.backend_name = "qutip";
  return context;
}

TEST(QutipBackendContractTest, ApplyOperationRejectsEmptyKind) {
  NullQuantumBackend backend;
  QutipBackend qutip_backend{&backend, "qutip"};

  auto result = qutip_backend.applyOperation(defaultContext(), PhysicalOperation{});
  EXPECT_FALSE(result.success);
  EXPECT_FALSE(result.message.empty());
  EXPECT_NE(result.message.find("operation.kind is empty"), std::string::npos);
}

TEST(QutipBackendContractTest, ApplyOperationSupportsAdvancedKindsWhenPossible) {
  NullQuantumBackend backend;
  QutipBackend qutip_backend{&backend, "qutip_density_matrix"};

  PhysicalOperation kerr_op;
  kerr_op.kind = "kerr";
  kerr_op.targets = {QubitHandle{1, 0, 0, 7}};
  auto result = qutip_backend.applyOperation(defaultContext(), kerr_op);
  if (qutipRuntimeAvailable()) {
    EXPECT_TRUE(result.success);
  } else {
    EXPECT_FALSE(result.success);
  }
  EXPECT_FALSE(result.message.empty());
}

TEST(QutipBackendContractTest, ApplyOperationAcceptsStateVectorAlias) {
  NullQuantumBackend backend;
  QutipBackend qutip_backend{&backend, "QUTIP_STATE_VECTOR"};
  PhysicalOperation unitary_op;
  unitary_op.kind = "unitary";
  unitary_op.targets = {QubitHandle{1, 0, 0, 7}};
  unitary_op.payload = {{"gate", "X"}};
  auto result = qutip_backend.applyOperation(defaultContext(), unitary_op);
  if (qutipRuntimeAvailable()) {
    EXPECT_TRUE(result.success);
  } else {
    EXPECT_FALSE(result.success);
  }
  EXPECT_FALSE(result.message.empty());
}

TEST(QutipBackendContractTest, ApplyOperationSupportsLegacyAliasAndCaseNormalization) {
  NullQuantumBackend backend;
  QutipBackend qutip_backend{&backend, "qutip"};

  PhysicalOperation kerr_op;
  kerr_op.kind = "Cross-Kerr";
  kerr_op.targets = {QubitHandle{1, 0, 0, 8}};
  auto kerr_result = qutip_backend.applyOperation(defaultContext(), kerr_op);
  if (qutipRuntimeAvailable()) {
    EXPECT_TRUE(kerr_result.success);
  } else {
    EXPECT_FALSE(kerr_result.success);
  }
  EXPECT_FALSE(kerr_result.message.empty());

  PhysicalOperation lower_noise_op;
  lower_noise_op.kind = "Loss";
  lower_noise_op.payload = {{"p", 0.2}};
  lower_noise_op.targets = {QubitHandle{1, 0, 0, 9}};
  auto loss_result = qutip_backend.applyOperation(defaultContext(), lower_noise_op);
  if (qutipRuntimeAvailable()) {
    EXPECT_TRUE(loss_result.success);
  } else {
    EXPECT_FALSE(loss_result.success);
  }
  EXPECT_FALSE(loss_result.message.empty());

  PhysicalOperation measure_alias_op;
  measure_alias_op.kind = "measure";
  measure_alias_op.targets = {QubitHandle{1, 0, 0, 10}};
  measure_alias_op.basis = "Z";
  auto measure_alias_result = qutip_backend.applyOperation(defaultContext(), measure_alias_op);
  if (qutipRuntimeAvailable()) {
    EXPECT_TRUE(measure_alias_result.success);
  } else {
    EXPECT_FALSE(measure_alias_result.success);
  }
  EXPECT_FALSE(measure_alias_result.message.empty());
}

TEST(QutipBackendContractTest, ApplyOperationSupportsCommonAdvancedKinds) {
  NullQuantumBackend backend;
  QutipBackend qutip_backend{&backend, "qutip"};
  const auto runtimes_available = qutipRuntimeAvailable();
  const std::vector<std::string> advanced_kinds = {
      "dephasing",
      "decoherence",
      "loss",
      "attenuation",
      "hom",
      "hom_interference",
      "two_photon_interference",
      "source_multiphoton",
      "multiphoton_source",
      "photon_source",
      "kerr",
      "kerr_effect",
      "kerreffect",
      "cross_kerr_effect",
      "cross-kerr",
      "beam_splitter",
      "beam splitter",
      "beamsplitter",
      "beam-splitter",
      "phase_shift",
      "phase-shift",
      "phaseshift",
      "phaseshifter",
      "phase_modulation",
      "phase_modulator",
      "self_phase_modulation",
      "self_phase_modulator",
      "cross_phase_modulation",
      "cross_phase_modulator",
      "nonlinear",
      "detection",
      "dark_count",
      "detector",
      "delay",
      "hamiltonian",
      "lindblad",
      "timing_jitter",
      "time-jitter",
      "timing-jitter",
      "heralded_entanglement",
      "dispersion",
      "multiphoton",
      "squeezing",
      "reset",
  };

  for (const auto& kind : advanced_kinds) {
    PhysicalOperation op;
    op.kind = kind;
    op.targets = {QubitHandle{1, 0, 0, 7}};
    if (kind == "phase_shift" || kind == "phase-shift") {
      op.params = {0.13};
    }
    if (kind.find("kerr") != std::string::npos) {
      op.params = {0.11};
    }
    if (kind == "beam_splitter" || kind == "beamsplitter" || kind == "beam splitter" || kind == "beam-splitter") {
      op.params = {0.75};
    }
    if (kind == "loss" || kind == "attenuation" || kind == "decoherence" || kind == "dephasing") {
      op.params = {0.05};
    }
    if (kind == "source_multiphoton" || kind == "multiphoton_source" || kind == "photon_source") {
      op.params = {0.04};
    }
    if (kind == "timing_jitter") {
      op.params = {0.12};
    }
    if (kind == "detection") {
      op.payload = {{"p", 0.02}};
    } else if (kind == "dark_count") {
      op.payload = {{"dark_count", 0.01}};
    } else if (kind == "detector") {
      op.payload = {{"detector", 0.01}};
    }
    if (kind == "hamiltonian" || kind == "lindblad") {
      op.payload = {{"expr", "sx"}};
    }
    if (kind == "heralded_entanglement") {
      op.params = {0.9};
    }

    const auto result = qutip_backend.applyOperation(defaultContext(), op);
    EXPECT_FALSE(result.message.empty()) << "kind=" << kind;
    if (runtimes_available) {
      EXPECT_TRUE(result.success) << "kind=" << kind;
    } else {
      EXPECT_FALSE(result.success) << "kind=" << kind;
    }
  }

  PhysicalOperation no_op_op;
  no_op_op.kind = "no-op";
  no_op_op.targets = {QubitHandle{1, 0, 0, 10}};
  const auto no_op_result = qutip_backend.applyOperation(defaultContext(), no_op_op);
  EXPECT_FALSE(no_op_result.message.empty()) << "kind=" << no_op_op.kind;
  if (runtimes_available) {
    EXPECT_TRUE(no_op_result.success) << "kind=" << no_op_op.kind;
  } else {
    EXPECT_FALSE(no_op_result.success) << "kind=" << no_op_op.kind;
  }
}

TEST(QutipBackendContractTest, ApplyOperationRejectsUnknownKind) {
  NullQuantumBackend backend;
  QutipBackend qutip_backend{&backend, "qutip"};

  PhysicalOperation op;
  op.kind = "not_an_operation";
  op.targets = {QubitHandle{1, 0, 0, 7}};
  auto result = qutip_backend.applyOperation(defaultContext(), op);
  EXPECT_FALSE(result.success);
  EXPECT_FALSE(result.message.empty());
}

bool qutipRuntimeAvailable() {
  const char* python_executable_env = std::getenv("QUTIP_PYTHON_EXECUTABLE");
  const char* python_executable = python_executable_env != nullptr && std::string(python_executable_env).size() > 0 ? python_executable_env : "python3";
  const std::string command = std::string(python_executable) + " -c \"import qutip, qutip_qip, qutip.qip\"";
  const int status = std::system(command.c_str());
  return status == 0;
}

TEST(QutipBackendContractTest, ApplyOperationFallsBackToLegacyForKnownKinds) {
  NullQuantumBackend backend;
  QutipBackend qutip_backend{&backend, "qutip_sv"};

  PhysicalOperation unitary_op;
  unitary_op.kind = "unitary";
  unitary_op.targets = {QubitHandle{1, 0, 0, 7}};
  unitary_op.payload = {{"gate", "X"}};
  auto unitary_result = qutip_backend.applyOperation(defaultContext(), unitary_op);
  if (qutipRuntimeAvailable()) {
    EXPECT_TRUE(unitary_result.success);
  } else {
    EXPECT_FALSE(unitary_result.success);
  }

  PhysicalOperation measurement_op;
  measurement_op.kind = "measurement";
  measurement_op.targets = {QubitHandle{1, 0, 0, 7}};
  measurement_op.basis = "X";
  auto measurement_result = qutip_backend.applyOperation(defaultContext(), measurement_op);
  if (qutipRuntimeAvailable()) {
    EXPECT_TRUE(measurement_result.success);
  } else {
    EXPECT_FALSE(measurement_result.success);
  }
}

}  // namespace
