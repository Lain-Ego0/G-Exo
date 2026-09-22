#include "gexo_deploy.hpp"

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

bool is_zero(const gexo::deploy::Action& action) {
  for (float value : action) {
    if (value != 0.0F) {
      return false;
    }
  }
  return true;
}

int run_smoke_test(gexo::deploy::Runtime& runtime) {
  const gexo::deploy::SensorFrame sensor{};
  const gexo::deploy::Action zero_action{};
  for (std::size_t step = 1; step <= 150; ++step) {
    const auto result = runtime.step(sensor, zero_action);
    if (!is_zero(result.action)) {
      std::cerr << "Warmup returned a non-zero action at step " << step << '\n';
      return 3;
    }
  }
  const gexo::deploy::Action applied{0.1F, -0.2F, 0.3F, -0.4F};
  const auto result = runtime.step(sensor, applied);
  if (result.state != gexo::deploy::State::kReady) {
    std::cerr << "Smoke test failed: state="
              << gexo::deploy::to_string(result.state) << " error="
              << runtime.get_error_message() << '\n';
    return 3;
  }
  std::cout << "state=READY action=[" << std::setprecision(8)
            << result.action[0] << ", " << result.action[1] << ", "
            << result.action[2] << ", " << result.action[3] << "]\n";
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

  gexo::deploy::Runtime runtime;
  std::string error;
  if (!runtime.initialize(std::filesystem::path(argv[1]), &error)) {
    std::cerr << "Deploy initialization failed: " << error << '\n';
    runtime.close();
    return 2;
  }
  std::cout << "state=" << gexo::deploy::to_string(runtime.get_state()) << '\n';

  int result = 0;
  if (argc == 3) {
    result = run_smoke_test(runtime);
  } else {
    while (g_stop_requested == 0) {
      std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }
  }

  runtime.close();
  std::cout << "Deploy closed.\n";
  return result;
}
