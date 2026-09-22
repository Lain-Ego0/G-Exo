#include "policy_runtime.hpp"

#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {

void require(bool condition, const char* message) {
  if (!condition) {
    throw std::runtime_error(message);
  }
}

}  // namespace

int main() {
  try {
    gexo::control::PolicyRuntime runtime;
    std::string error;
    require(runtime.initialize(GEXO_RL_TCN_MODEL_DIRECTORY,
                               GEXO_TCN_PD_MODEL_DIRECTORY, &error),
            error.c_str());

    gexo::control::SensorFrame sensor{};
    gexo::control::JointVector previous_action{};
    require(runtime.start(gexo::control::PolicyKind::kRlTcn, &error),
            error.c_str());
    for (int step = 1; step <= 150; ++step) {
      const auto result = runtime.step(sensor, previous_action);
      require(result.state == gexo::control::PolicyState::kWarmup,
              "RL+TCN must remain WARMUP through step 150.");
    }
    require(runtime.step(sensor, previous_action).state ==
                gexo::control::PolicyState::kReady,
            "RL+TCN must enter READY on step 151.");
    require(runtime.stop(&error), error.c_str());

    require(runtime.start(gexo::control::PolicyKind::kTcnPd, &error),
            error.c_str());
    for (int step = 1; step <= 150; ++step) {
      const auto result = runtime.step(sensor, previous_action);
      require(result.state == gexo::control::PolicyState::kWarmup,
              "TCN+PD must remain WARMUP through step 150.");
    }
    require(runtime.step(sensor, previous_action).state ==
                gexo::control::PolicyState::kReady,
            "TCN+PD must enter READY on step 151.");
    require(runtime.stop(&error), error.c_str());

    require(runtime.start(gexo::control::PolicyKind::kTcnPd, &error),
            error.c_str());
    require(runtime.step(sensor, previous_action).state ==
                gexo::control::PolicyState::kWarmup,
            "A restarted TCN+PD run must begin with fresh history.");
    require(runtime.stop(&error), error.c_str());
    runtime.close();
    return EXIT_SUCCESS;
  } catch (const std::exception& error) {
    std::cerr << "Policy runtime test failed: " << error.what() << '\n';
    return EXIT_FAILURE;
  }
}
