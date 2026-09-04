#pragma once

#include <array>
#include <cstddef>
#include <filesystem>
#include <memory>
#include <string>

namespace gexo::deploy {

inline constexpr std::size_t kSensorDimension = 32;
inline constexpr std::size_t kActionDimension = 4;

using SensorFrame = std::array<float, kSensorDimension>;
using Action = std::array<float, kActionDimension>;

enum class State {
  kWarmup,
  kReady,
  kFault,
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
};

struct StepResult {
  State state{State::kFault};
  Action action{};
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
  StepResult step(const SensorFrame& sensor,
                  const Action& previous_applied_action) noexcept;
  bool reset() noexcept;
  void close() noexcept;
  State get_state() const noexcept;
  ErrorCode get_error_code() const noexcept;
  std::string get_error_message() const;
  std::size_t valid_steps() const noexcept;
  // Number of attempted TCN+Actor inference cycles in the current run.
  std::size_t inference_steps() const noexcept;

 private:
  class Impl;
  std::unique_ptr<Impl> impl_;
};

const char* to_string(State state) noexcept;
const char* to_string(ErrorCode error_code) noexcept;

}  // namespace gexo::deploy
