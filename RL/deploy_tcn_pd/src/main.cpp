#include "gexo_tcn_pd_deploy.hpp"

#include <chrono>
#include <csignal>
#include <filesystem>
#include <iomanip>
#include <iostream>
#include <string>
#include <thread>

namespace {

volatile std::sig_atomic_t g_stop_requested = 0;

extern "C" void handle_stop_signal(int) {
  g_stop_requested = 1;
}

bool is_zero(const gexo::deploy_tcn_pd::JointVector& values) {
  for (float value : values) {
    if (value != 0.0F) {
      return false;
    }
  }
  return true;
}

int run_smoke_test(gexo::deploy_tcn_pd::Runtime& runtime) {
  const gexo::deploy_tcn_pd::SensorFrame sensor{};
  for (std::size_t step = 1; step < 150; ++step) {
    const auto result = runtime.step(sensor);
    if (result.state != gexo::deploy_tcn_pd::State::kWarmup ||
        !is_zero(result.action) || !is_zero(result.target_torque_nm)) {
      std::cerr << "Warmup contract failed at step " << step << '\n';
      return 3;
    }
  }
  const auto result = runtime.step(sensor);
  if (result.state != gexo::deploy_tcn_pd::State::kReady) {
    std::cerr << "Smoke test failed: state="
              << gexo::deploy_tcn_pd::to_string(result.state) << " error="
              << runtime.get_error_message() << '\n';
    return 3;
  }
  std::cout << "state=READY action=[" << std::setprecision(8)
            << result.action[0] << ", " << result.action[1] << ", "
            << result.action[2] << ", " << result.action[3]
            << "] target_torque_nm=[" << result.target_torque_nm[0] << ", "
            << result.target_torque_nm[1] << ", "
            << result.target_torque_nm[2] << ", "
            << result.target_torque_nm[3] << "] confidence="
            << result.confidence << '\n';
  return 0;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 2 || argc > 3 ||
      (argc == 3 && std::string(argv[2]) != "--smoke-test")) {
    std::cerr << "Usage: " << argv[0]
              << " MODEL_DIRECTORY [--smoke-test]\n";
    return 64;
  }

  std::signal(SIGINT, handle_stop_signal);
  std::signal(SIGTERM, handle_stop_signal);

  gexo::deploy_tcn_pd::Runtime runtime;
  std::string error;
  if (!runtime.initialize(std::filesystem::path(argv[1]), &error)) {
    std::cerr << "TCN+PD Deploy initialization failed: " << error << '\n';
    runtime.request_shutdown("Initialization failed.");
    return 2;
  }
  std::cout << "state="
            << gexo::deploy_tcn_pd::to_string(runtime.get_state()) << '\n';

  int result = 0;
  if (argc == 3) {
    result = run_smoke_test(runtime);
  } else {
    while (g_stop_requested == 0) {
      std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }
  }

  runtime.request_shutdown("Process stop requested.");
  std::cout << "state="
            << gexo::deploy_tcn_pd::to_string(runtime.get_state()) << '\n';
  return result;
}

