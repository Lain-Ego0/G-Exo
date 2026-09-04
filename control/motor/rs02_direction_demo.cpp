#include "rs02_motor_group.hpp"

#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <csignal>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <future>
#include <iomanip>
#include <iostream>
#include <string>
#include <thread>
#include <vector>

namespace {

constexpr float kPositivePositionStepRad = 0.3F;
constexpr float kVelocityTargetRadS = 0.0F;
constexpr float kFeedforwardTorqueNm = 0.0F;
constexpr float kKp = 5.0F;
constexpr float kKd = 1.0F;
constexpr float kMotorTorqueLimitNm = 2.0F;
constexpr float kConfirmedPositiveDeltaRad = 0.05F;
constexpr float kProtocolPositionLimitRad = 12.566370614359172F;
constexpr std::uint32_t kCanTimeoutTicks = 600;
constexpr auto kControlPeriod = std::chrono::milliseconds(5);
constexpr auto kFeedbackTimeout = std::chrono::milliseconds(30);
constexpr std::uint64_t kTestTicks = 400;

constexpr std::array<const char*, 4> kJointNames{
    "left_hip", "left_knee", "right_hip", "right_knee"};
constexpr std::array<const char*, 4> kUrdfPositiveDirections{
    "thigh backward (extension)",
    "shank backward (flexion)",
    "thigh forward (flexion)",
    "shank forward (extension)",
};

struct LogSample {
  std::uint64_t tick{0};
  double elapsed_ms{0.0};
  float position_rad{0.0F};
  float position_delta_rad{0.0F};
  float velocity_rad_s{0.0F};
  float torque_nm{0.0F};
  float temperature_c{0.0F};
  std::uint8_t mode{0};
  std::uint8_t fault_bits{0};
};

volatile std::sig_atomic_t signal_stop_requested = 0;

void handle_signal(int) { signal_stop_requested = 1; }

void stop_all_repeated(gexo::motor::Rs02MotorGroup& motors) noexcept {
  for (int repeat = 0; repeat < 3; ++repeat) {
    motors.stop_all();
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
  }
}

bool feedback_is_fresh(const gexo::motor::Rs02Feedback& feedback) {
  return feedback.valid && feedback.fault_bits == 0 &&
         std::chrono::steady_clock::now() - feedback.received_at <=
             kFeedbackTimeout;
}

bool write_log(
    const std::string& path, const gexo::motor::Rs02MotorGroup& motors,
    const std::array<float, gexo::motor::Rs02MotorGroup::kMotorCount>& initial,
    const std::array<float, gexo::motor::Rs02MotorGroup::kMotorCount>& target,
    const std::array<std::vector<LogSample>,
                     gexo::motor::Rs02MotorGroup::kMotorCount>& samples) {
  std::ofstream stream(path, std::ios::trunc);
  if (!stream) {
    return false;
  }
  stream << "joint,can_interface,motor_id,tick,elapsed_ms,initial_position_rad,"
            "target_position_rad,position_rad,position_delta_rad,velocity_rad_s,"
            "torque_nm,temperature_c,mode,fault_bits\n";
  stream << std::fixed << std::setprecision(6);
  for (std::size_t index = 0; index < samples.size(); ++index) {
    const auto& motor = *motors.motors()[index];
    for (const LogSample& sample : samples[index]) {
      stream << kJointNames[index] << ',' << motor.interface() << ','
             << static_cast<unsigned int>(motor.motor_id()) << ',' << sample.tick
             << ',' << sample.elapsed_ms << ',' << initial[index] << ','
             << target[index] << ',' << sample.position_rad << ','
             << sample.position_delta_rad << ',' << sample.velocity_rad_s << ','
             << sample.torque_nm << ',' << sample.temperature_c << ','
             << static_cast<unsigned int>(sample.mode) << ','
             << static_cast<unsigned int>(sample.fault_bits) << '\n';
    }
  }
  return static_cast<bool>(stream);
}

int run_direction_test(const std::string& log_path) {
  gexo::motor::Rs02MotorGroup motors;
  std::string error;

  if (!motors.open_all(&error) ||
      !motors.configure_all(kMotorTorqueLimitNm, kCanTimeoutTicks, &error)) {
    std::cerr << "RS02 initialization failed: " << error << '\n';
    return EXIT_FAILURE;
  }

  std::array<float, gexo::motor::Rs02MotorGroup::kMotorCount> initial{};
  std::array<float, gexo::motor::Rs02MotorGroup::kMotorCount> target{};
  gexo::motor::Rs02MotorGroup::Commands commands{};
  for (std::size_t index = 0; index < motors.motors().size(); ++index) {
    if (!motors.motors()[index]->read_mechanical_position(&initial[index],
                                                          &error)) {
      std::cerr << "Failed to read " << kJointNames[index]
                << " mechanical position: " << error << '\n';
      stop_all_repeated(motors);
      return EXIT_FAILURE;
    }
    target[index] = initial[index] + kPositivePositionStepRad;
    if (!std::isfinite(target[index]) ||
        std::fabs(target[index]) > kProtocolPositionLimitRad) {
      std::cerr << "Refusing to enable: " << kJointNames[index]
                << " target exceeds the RS02 position protocol range.\n";
      stop_all_repeated(motors);
      return EXIT_FAILURE;
    }
    commands[index] = gexo::motor::Rs02Command{
        target[index], kVelocityTargetRadS, kFeedforwardTorqueNm, kKp, kKd};
  }

  std::cout << std::fixed << std::setprecision(3);
  std::cout << "Positive motor-coordinate direction test:\n";
  for (std::size_t index = 0; index < initial.size(); ++index) {
    std::cout << "  " << kJointNames[index] << ": initial=" << initial[index]
              << " rad, target=" << target[index]
              << " rad, URDF positive=" << kUrdfPositiveDirections[index]
              << '\n';
  }

  // Damping is the active command while the four motors are enabled in turn.
  if (!motors.damping_all(kKd, &error) || !motors.enable_all(&error) ||
      !motors.damping_all(kKd, &error)) {
    std::cerr << "RS02 enable failed: " << error << '\n';
    stop_all_repeated(motors);
    return EXIT_FAILURE;
  }

  std::array<std::vector<LogSample>,
             gexo::motor::Rs02MotorGroup::kMotorCount>
      samples{};
  for (auto& motor_samples : samples) {
    motor_samples.reserve(kTestTicks);
  }
  std::array<std::string, gexo::motor::Rs02MotorGroup::kMotorCount>
      worker_errors{};
  std::array<std::thread, gexo::motor::Rs02MotorGroup::kMotorCount> workers;
  std::atomic<bool> stop_workers{false};
  std::promise<void> start_promise;
  const std::shared_future<void> start_signal =
      start_promise.get_future().share();
  std::chrono::steady_clock::time_point start_time{};

  for (std::size_t index = 0; index < workers.size(); ++index) {
    workers[index] = std::thread([&, index, start_signal] {
      auto& motor = *motors.motors()[index];
      std::string local_error;
      start_signal.wait();
      auto next_tick = start_time;

      for (std::uint64_t tick = 0;
           tick < kTestTicks && !stop_workers.load() &&
           signal_stop_requested == 0;
           ++tick) {
        next_tick += kControlPeriod;
        if (!motor.update_feedback(&local_error) ||
            !feedback_is_fresh(motor.feedback()) ||
            !motor.send(commands[index], &local_error)) {
          if (local_error.empty()) {
            local_error = "stale feedback or motor fault";
          }
          worker_errors[index] = local_error;
          stop_workers.store(true);
          break;
        }

        const auto& feedback = motor.feedback();
        const auto now = std::chrono::steady_clock::now();
        samples[index].push_back(LogSample{
            tick,
            std::chrono::duration<double, std::milli>(now - start_time).count(),
            feedback.position_rad,
            feedback.position_rad - initial[index],
            feedback.velocity_rad_s,
            feedback.torque_nm,
            feedback.temperature_c,
            feedback.mode,
            feedback.fault_bits,
        });
        std::this_thread::sleep_until(next_tick);
      }
    });
  }

  start_time = std::chrono::steady_clock::now();
  start_promise.set_value();
  for (std::thread& worker : workers) {
    worker.join();
  }
  stop_all_repeated(motors);

  if (!write_log(log_path, motors, initial, target, samples)) {
    std::cerr << "Failed to write direction log: " << log_path << '\n';
    return EXIT_FAILURE;
  }

  bool failed = stop_workers.load();
  std::cout << "Final motor-coordinate displacement:\n";
  for (std::size_t index = 0; index < samples.size(); ++index) {
    if (!worker_errors[index].empty()) {
      std::cerr << "  " << kJointNames[index]
                << " failed: " << worker_errors[index] << '\n';
    }
    if (samples[index].empty()) {
      std::cout << "  " << kJointNames[index] << ": no valid sample\n";
      failed = true;
      continue;
    }
    const float delta = samples[index].back().position_delta_rad;
    std::cout << "  " << kJointNames[index] << ": delta=" << delta
              << " rad, motor-positive movement="
              << (delta >= kConfirmedPositiveDeltaRad ? "YES" : "NO") << '\n';
    if (delta < kConfirmedPositiveDeltaRad) {
      failed = true;
    }
  }
  std::cout << "Log written to " << log_path
            << "; stop command sent three times.\n";
  return failed ? EXIT_FAILURE : EXIT_SUCCESS;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 2 || argc > 3 || std::string(argv[1]) != "--yes") {
    std::cerr
        << "usage: sudo gexo_rs02_direction_demo --yes [log.csv]\n"
        << "Each motor uses its own 200 Hz worker and moves toward "
           "initial_position + 0.3 rad with v=0, t_ff=0, Kp=5, Kd=1. "
           "Keep the mechanism unloaded and the physical emergency stop "
           "within reach.\n";
    return EXIT_FAILURE;
  }

  std::signal(SIGINT, handle_signal);
  std::signal(SIGTERM, handle_signal);
  const std::string log_path =
      argc == 3 ? argv[2] : "rs02_direction_log.csv";
  return run_direction_test(log_path);
}
