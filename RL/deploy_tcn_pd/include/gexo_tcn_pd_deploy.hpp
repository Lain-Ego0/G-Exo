#pragma once

#include <array>
#include <cstddef>
#include <filesystem>
#include <memory>
#include <string>

namespace gexo::deploy_tcn_pd {

inline constexpr std::size_t kSensorDimension = 32;
inline constexpr std::size_t kJointCount = 4;

using SensorFrame = std::array<float, kSensorDimension>;
using JointVector = std::array<float, kJointCount>;

enum class State {
  kWarmup,
  kReady,
  kFault,
  kShuttingDown,
};

enum class ErrorCode {
  kNone = 0,
  kNotInitialized,
  kConfiguration,
  kModelIntegrity,
  kModelInterface,
  kInvalidInput,
  kInference,
  kNonFinite,
  kHistory,
  kShutdownRequested,
};

struct StepResult {
  State state{State::kFault};
  JointVector target_torque_nm{};
  JointVector action{};
  float confidence{0.0F};
  float feature_ood_ratio{0.0F};
  float sensor_ood_ratio{0.0F};
  bool feature_saturated{false};
  bool sensor_saturated{false};
  bool error_limited{false};
  bool action_saturated{false};
  ErrorCode error_code{ErrorCode::kNotInitialized};
};

class Runtime final {
 public:
  Runtime();
  ~Runtime();

  Runtime(const Runtime&) = delete;
  Runtime& operator=(const Runtime&) = delete;
  Runtime(Runtime&&) = delete;
  Runtime& operator=(Runtime&&) = delete;

  bool initialize(const std::filesystem::path& model_directory,
                  std::string* error_message = nullptr) noexcept;
  StepResult step(const SensorFrame& sensor) noexcept;
  State get_state() const noexcept;
  ErrorCode get_error_code() const noexcept;
  std::string get_error_message() const;
  std::size_t valid_steps() const noexcept;

  // Runtime ownership is single-threaded. Every catchable stop path calls the
  // same idempotent cleanup operation.
  void request_shutdown(std::string reason = {}) noexcept;

 private:
  class Impl;
  std::unique_ptr<Impl> impl_;
};

const char* to_string(State state) noexcept;
const char* to_string(ErrorCode error_code) noexcept;

}  // namespace gexo::deploy_tcn_pd

