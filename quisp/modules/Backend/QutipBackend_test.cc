#include <cstdlib>
#include <filesystem>
#include <gtest/gtest.h>

#include <string>
#include <vector>

#include "QutipBackend.h"

namespace {
using quisp::modules::backend::BackendContext;
using quisp::modules::backend::PhysicalOperation;
using quisp::modules::backend::QubitHandle;
using quisp::modules::backend::QutipBackend;

bool qutipRuntimeAvailable();
void configureQutipPythonExecutableForTests();

struct QutipTestEnvironmentInitializer {
  QutipTestEnvironmentInitializer() { configureQutipPythonExecutableForTests(); }
} qutip_test_environment_initializer;

BackendContext defaultContext() {
  BackendContext context;
  context.seed = 123;
  context.now = omnetpp::SimTime::ZERO;
  context.scenario_id = "qutip-test";
  context.backend_name = "qutip";
  return context;
}

TEST(QutipBackendContractTest, ApplyOperationRejectsEmptyKind) {
  QutipBackend qutip_backend{"qutip"};

  auto result = qutip_backend.applyOperation(defaultContext(), PhysicalOperation{});
  EXPECT_FALSE(result.success);
  EXPECT_FALSE(result.message.empty());
  EXPECT_NE(result.message.find("operation.kind is empty"), std::string::npos);
}

TEST(QutipBackendContractTest, ApplyOperationSupportsAdvancedKindsWhenPossible) {
  QutipBackend qutip_backend{"qutip_density_matrix"};

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
  QutipBackend qutip_backend{"QUTIP_STATE_VECTOR"};
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
  QutipBackend qutip_backend{"qutip"};

  PhysicalOperation kerr_op;
  kerr_op.kind = "Kerr";
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

TEST(QutipBackendContractTest, ApplyOperationRejectsWrongTargetCountForBasicKinds) {
  QutipBackend qutip_backend{"qutip"};

  PhysicalOperation measurement_op;
  measurement_op.kind = "measurement";
  measurement_op.basis = "Z";
  auto missing_target = qutip_backend.applyOperation(defaultContext(), measurement_op);
  EXPECT_FALSE(missing_target.success);
  EXPECT_NE(missing_target.message.find("measurement operation expects exactly one target"), std::string::npos);

  measurement_op.targets = {QubitHandle{1, 0, 0, 7}, QubitHandle{1, 0, 0, 8}};
  auto too_many_targets = qutip_backend.applyOperation(defaultContext(), measurement_op);
  EXPECT_FALSE(too_many_targets.success);
  EXPECT_NE(too_many_targets.message.find("measurement operation expects exactly one target"), std::string::npos);

  PhysicalOperation noise_op;
  noise_op.kind = "noise";
  noise_op.payload = {{"noise_kind", "dephasing"}};
  noise_op.params = {0.2};
  auto noise_without_targets = qutip_backend.applyOperation(defaultContext(), noise_op);
  EXPECT_FALSE(noise_without_targets.success);
  EXPECT_NE(noise_without_targets.message.find("noise operation expects exactly one target"), std::string::npos);
}

TEST(QutipBackendContractTest, ApplyOperationRejectsInvalidControlHandle) {
  QutipBackend qutip_backend{"qutip"};

  PhysicalOperation op;
  op.kind = "kerr";
  op.targets = {QubitHandle{1, 0, 0, 7}};
  op.controls = {QubitHandle{-1, 0, 0, 0}};
  auto result = qutip_backend.applyOperation(defaultContext(), op);
  EXPECT_FALSE(result.success);
  EXPECT_NE(result.message.find("invalid control handle"), std::string::npos);
}

TEST(QutipBackendContractTest, GenerateEntanglementAcceptsFlyingQubitHandle) {
  QutipBackend qutip_backend{"qutip_density_matrix"};

  auto result = qutip_backend.generateEntanglement(defaultContext(), QubitHandle{1, 0, 0, 7}, QubitHandle{-1, -1, -1, 1});
  EXPECT_EQ(result.message.find("invalid qubit handle"), std::string::npos);
}

TEST(QutipBackendContractTest, ApplyOperationAcceptsFlyingQubitTargetForUnitary) {
  QutipBackend qutip_backend{"qutip_density_matrix"};

  PhysicalOperation op;
  op.kind = "unitary";
  op.targets = {QubitHandle{-1, -1, -1, 1}};
  op.payload = {{"gate", "H"}};
  auto result = qutip_backend.applyOperation(defaultContext(), op);
  EXPECT_EQ(result.message.find("invalid qubit handle"), std::string::npos);
}

TEST(QutipBackendContractTest, ApplyOperationSupportsCommonAdvancedKinds) {
  QutipBackend qutip_backend{"qutip"};
  const auto runtimes_available = qutipRuntimeAvailable();
  const std::vector<std::string> advanced_kinds = {
      "dephasing",
      "decoherence",
      "loss",
      "attenuation",
      "amplitude_damping",
      "thermal_relaxation",
      "bitflip",
      "phaseflip",
      "depolarizing",
      "polarization_rotation",
      "polarization_decoherence",
      "mode_coupling",
      "loss_mode",
      "two_mode_squeezing",
      "fock_loss",
      "photon_number_cutoff",
      "channel_dispersion",
      "fibre_dispersion",
      "fiber_dispersion",
      "hom",
      "hom_interference",
      "hominterference",
      "bs_interference",
      "bsinterference",
      "two_photon_interference",
      "twophoton_interference",
      "source_multiphoton",
      "multiphoton_source",
      "multi_photon_source",
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
      "dispersion",
      "multiphoton",
      "squeezing",
      "reset",
  };

  for (const auto& kind : advanced_kinds) {
    PhysicalOperation op;
    op.kind = kind;
    if (
        kind == "cross_kerr" ||
        kind == "beam_splitter" ||
        kind == "beamsplitter" ||
        kind == "beam splitter" ||
        kind == "beam-splitter" ||
        kind == "cross_phase_modulation" ||
        kind == "cross_phase_modulator" ||
        kind == "mode_coupling" ||
        kind == "hom" ||
        kind == "hom_interference" ||
        kind == "hominterference" ||
        kind == "bs_interference" ||
        kind == "bsinterference" ||
        kind == "two_photon_interference" ||
        kind == "twophoton_interference" ||
        kind == "cross_kerr_effect" ||
        kind == "cross-kerr" ||
        kind == "two_mode_squeezing"
    ) {
      op.targets = {QubitHandle{1, 0, 0, 7}, QubitHandle{1, 0, 0, 8}};
    } else {
      op.targets = {QubitHandle{1, 0, 0, 7}};
    }
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
  EXPECT_TRUE(no_op_result.success) << "kind=" << no_op_op.kind;
}

TEST(QutipBackendContractTest, ApplyOperationRejectsUnknownKind) {
  QutipBackend qutip_backend{"qutip"};

  PhysicalOperation op;
  op.kind = "not_an_operation";
  op.targets = {QubitHandle{1, 0, 0, 7}};
  auto result = qutip_backend.applyOperation(defaultContext(), op);
  EXPECT_FALSE(result.success);
  EXPECT_FALSE(result.message.empty());
}

bool qutipRuntimeAvailable() {
  configureQutipPythonExecutableForTests();
  const char* python_executable_env = std::getenv("QUTIP_PYTHON_EXECUTABLE");
  const char* python_executable = python_executable_env != nullptr && std::string(python_executable_env).size() > 0 ? python_executable_env : "python3";
  const std::string command = std::string(python_executable) + " -c \"import qutip, qutip_qip, qutip.qip\" >/dev/null 2>&1";
  const int status = std::system(command.c_str());
  return status == 0;
}

void configureQutipPythonExecutableForTests() {
  const char* configured = std::getenv("QUTIP_PYTHON_EXECUTABLE");
  if (configured != nullptr && std::string(configured).size() > 0) {
  } else {
    const auto cwd = std::filesystem::current_path();
    const std::vector<std::filesystem::path> candidates = {
        cwd / ".venv-qutip/bin/python",
        cwd / "../.venv-qutip/bin/python",
    };
    for (const auto& candidate : candidates) {
      if (std::filesystem::exists(candidate)) {
        setenv("QUTIP_PYTHON_EXECUTABLE", candidate.string().c_str(), 1);
        break;
      }
    }
  }

  const char* python_warnings = std::getenv("PYTHONWARNINGS");
  if (python_warnings == nullptr || std::string(python_warnings).empty()) {
    setenv("PYTHONWARNINGS", "ignore", 1);
  }

  const char* matplotlib_config = std::getenv("MPLCONFIGDIR");
  if (matplotlib_config == nullptr || std::string(matplotlib_config).empty()) {
    const auto mpl_config_dir = std::filesystem::temp_directory_path() / "quisp-mplconfig";
    std::filesystem::create_directories(mpl_config_dir);
    setenv("MPLCONFIGDIR", mpl_config_dir.string().c_str(), 1);
  }
}

TEST(QutipBackendContractTest, ApplyOperationFallsBackToLegacyForKnownKinds) {
  QutipBackend qutip_backend{"qutip_sv"};

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
