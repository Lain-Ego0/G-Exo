#include "rs02_motor_group.hpp"

#include <chrono>
#include <cmath>
#include <csignal>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <thread>

namespace {

volatile std::sig_atomic_t stop_requested = 0;

void handle_signal(int) { stop_requested = 1; }

float parse_kd(int argc, char** argv) {
  if (argc > 2) {
    throw std::invalid_argument("usage: gexo_rs02_damping_demo [Kd]");
  }
  std::size_t parsed = 0;
  const float kd = argc == 2 ? std::stof(argv[1], &parsed) : 0.2F;
  if (argc == 2 && parsed != std::string(argv[1]).size()) {
    throw std::invalid_argument("Kd is not a valid number");
  }
  if (!std::isfinite(kd) || kd <= 0.0F || kd > 5.0F) {
    throw std::invalid_argument("Kd must be in (0, 5]");
  }
  return kd;
}

bool feedback_is_fresh(const gexo::motor::Rs02MotorGroup& motors) {
  constexpr auto timeout = std::chrono::milliseconds(30);
  const auto now = std::chrono::steady_clock::now();
  for (const auto& motor : motors.motors()) {
    const auto& feedback = motor->feedback();
    if (!feedback.valid || feedback.fault_bits != 0 ||
        now - feedback.received_at > timeout) {
      return false;
    }
  }
  return true;
}

void print_feedback(const gexo::motor::Rs02MotorGroup& motors) {
  std::cout << std::fixed << std::setprecision(3);
  for (const auto& motor : motors.motors()) {
    const auto& feedback = motor->feedback();
    std::cout << motor->interface() << "/" << static_cast<int>(motor->motor_id())
              << " q=" << feedback.position_rad
              << " dq=" << feedback.velocity_rad_s
              << " tau=" << feedback.torque_nm
              << " temp=" << feedback.temperature_c << "  ";
  }
  std::cout << '\n';
}

}  // namespace

int main(int argc, char** argv) {
  try {
    const float kd = parse_kd(argc, argv);
    std::signal(SIGINT, handle_signal);
    std::signal(SIGTERM, handle_signal);

    gexo::motor::Rs02MotorGroup motors;
    std::string error;
    if (!motors.open_all(&error) || !motors.configure_all(6.0F, 600, &error) ||
        !motors.damping_all(kd, &error) || !motors.enable_all(&error)) {
      std::cerr << "RS02 initialization failed: " << error << '\n';
      return EXIT_FAILURE;
    }

    constexpr auto period = std::chrono::milliseconds(5);
    auto next_tick = std::chrono::steady_clock::now();
    std::uint64_t tick = 0;
    while (stop_requested == 0) {
      next_tick += period;
      if (!motors.update_all(&error) || !feedback_is_fresh(motors) ||
          !motors.damping_all(kd, &error)) {
        motors.stop_all();
        std::cerr << "RS02 damping stopped"
                  << (error.empty() ? "" : ": " + error) << '\n';
        return EXIT_FAILURE;
      }
      if (++tick % 200 == 0) {
        print_feedback(motors);
      }
      std::this_thread::sleep_until(next_tick);
    }

    motors.stop_all();
    return EXIT_SUCCESS;
  } catch (const std::exception& exception) {
    std::cerr << exception.what() << '\n';
    return EXIT_FAILURE;
  }
}
