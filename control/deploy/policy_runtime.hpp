#pragma once

#include "control_contract.hpp"

#include <filesystem>
#include <memory>
#include <string>

namespace gexo::deploy {
class Runtime;
}

namespace gexo::deploy_tcn_pd {
class Runtime;
}

namespace gexo::control {

using SensorFrame = contract::SensorFrame;
using JointVector = contract::JointVector;

enum class PolicyKind {
  kRlTcn,
  kTcnPd,
};

enum class PolicyState {
  kStopped,
  kWarmup,
  kReady,
  kFault,
};

struct PolicyResult {
  PolicyState state{PolicyState::kStopped};
  JointVector normalized_action{};
  JointVector target_torque_nm{};
  float confidence{0.0F};
  std::string diagnostic;
};

class PolicyRuntime final {
 public:
  PolicyRuntime();
  ~PolicyRuntime();

  PolicyRuntime(const PolicyRuntime&) = delete;
  PolicyRuntime& operator=(const PolicyRuntime&) = delete;

  bool initialize(const std::filesystem::path& rl_tcn_model_directory,
                  const std::filesystem::path& tcn_pd_model_directory,
                  std::string* error_message = nullptr) noexcept;
  bool start(PolicyKind kind, std::string* error_message = nullptr) noexcept;
  PolicyResult step(const SensorFrame& sensor,
                    const JointVector& previous_applied_action) noexcept;
  bool stop(std::string* error_message = nullptr) noexcept;
  void close() noexcept;

  bool is_active() const noexcept;
  PolicyKind active_kind() const noexcept;
  PolicyState state() const noexcept;

 private:
  bool validate_model_packages(std::string* error_message) noexcept;

  std::filesystem::path rl_tcn_model_directory_;
  std::filesystem::path tcn_pd_model_directory_;
  std::unique_ptr<gexo::deploy::Runtime> rl_tcn_;
  std::unique_ptr<gexo::deploy_tcn_pd::Runtime> tcn_pd_;
  PolicyKind active_kind_{PolicyKind::kRlTcn};
  PolicyState state_{PolicyState::kStopped};
  bool initialized_{false};
  bool active_{false};
  bool closed_{false};
};

bool parse_policy_kind(const std::string& value, PolicyKind* kind) noexcept;
const char* to_string(PolicyKind kind) noexcept;
const char* to_string(PolicyState state) noexcept;

}  // namespace gexo::control
