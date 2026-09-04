#include "policy_runtime.hpp"

#include "gexo_deploy.hpp"
#include "gexo_tcn_pd_deploy.hpp"

#include <algorithm>
#include <utility>

namespace gexo::control {
namespace {

void copy_error(std::string* destination, const std::string& value) noexcept {
  if (destination == nullptr) {
    return;
  }
  try {
    *destination = value;
  } catch (...) {
  }
}

PolicyState map_rl_state(gexo::deploy::State state) noexcept {
  switch (state) {
    case gexo::deploy::State::kWarmup:
      return PolicyState::kWarmup;
    case gexo::deploy::State::kReady:
      return PolicyState::kReady;
    case gexo::deploy::State::kFault:
      return PolicyState::kFault;
  }
  return PolicyState::kFault;
}

PolicyState map_tcn_pd_state(gexo::deploy_tcn_pd::State state) noexcept {
  switch (state) {
    case gexo::deploy_tcn_pd::State::kWarmup:
      return PolicyState::kWarmup;
    case gexo::deploy_tcn_pd::State::kReady:
      return PolicyState::kReady;
    case gexo::deploy_tcn_pd::State::kFault:
      return PolicyState::kFault;
    case gexo::deploy_tcn_pd::State::kShuttingDown:
      return PolicyState::kStopped;
  }
  return PolicyState::kFault;
}

}  // namespace

PolicyRuntime::PolicyRuntime() = default;

PolicyRuntime::~PolicyRuntime() { close(); }

bool PolicyRuntime::initialize(
    const std::filesystem::path& rl_tcn_model_directory,
    const std::filesystem::path& tcn_pd_model_directory,
    std::string* error_message) noexcept {
  if (initialized_ || closed_) {
    copy_error(error_message, "PolicyRuntime cannot be initialized twice.");
    return false;
  }
  rl_tcn_model_directory_ = rl_tcn_model_directory;
  tcn_pd_model_directory_ = tcn_pd_model_directory;
  if (!validate_model_packages(error_message)) {
    return false;
  }

  initialized_ = true;
  state_ = PolicyState::kStopped;
  copy_error(error_message, {});
  return true;
}

bool PolicyRuntime::start(PolicyKind kind,
                          std::string* error_message) noexcept {
  if (!initialized_ || closed_) {
    copy_error(error_message, "PolicyRuntime is not initialized.");
    return false;
  }
  if (active_ && !stop(error_message)) {
    return false;
  }

  std::string detail;
  if (kind == PolicyKind::kRlTcn) {
    rl_tcn_ = std::make_unique<gexo::deploy::Runtime>();
    if (!rl_tcn_->initialize(rl_tcn_model_directory_, &detail)) {
      copy_error(error_message, "RL+TCN open failed: " + detail);
      rl_tcn_.reset();
      state_ = PolicyState::kFault;
      return false;
    }
  } else {
    tcn_pd_ = std::make_unique<gexo::deploy_tcn_pd::Runtime>();
    if (!tcn_pd_->initialize(tcn_pd_model_directory_, &detail)) {
      copy_error(error_message, "TCN+PD open failed: " + detail);
      tcn_pd_.reset();
      state_ = PolicyState::kFault;
      return false;
    }
  }

  active_kind_ = kind;
  active_ = true;
  state_ = PolicyState::kWarmup;
  copy_error(error_message, {});
  return true;
}

PolicyResult PolicyRuntime::step(
    const SensorFrame& sensor,
    const JointVector& previous_applied_action) noexcept {
  if (!initialized_ || closed_ || !active_) {
    return PolicyResult{};
  }

  PolicyResult output;
  if (active_kind_ == PolicyKind::kRlTcn) {
    const auto result = rl_tcn_->step(sensor, previous_applied_action);
    output.state = map_rl_state(result.state);
    if (output.state == PolicyState::kReady) {
      output.normalized_action = result.action;
      for (std::size_t joint = 0; joint < contract::kJointCount; ++joint) {
        output.target_torque_nm[joint] =
            result.action[joint] * contract::kRlTrainingActionScaleNm;
      }
      output.confidence = 1.0F;
    } else if (output.state == PolicyState::kFault) {
      output.diagnostic = rl_tcn_->get_error_message();
    }
  } else {
    const auto result = tcn_pd_->step(sensor);
    output.state = map_tcn_pd_state(result.state);
    if (output.state == PolicyState::kReady) {
      output.normalized_action = result.action;
      output.target_torque_nm = result.target_torque_nm;
      output.confidence = result.confidence;
    } else if (output.state == PolicyState::kFault) {
      output.diagnostic = tcn_pd_->get_error_message();
    }
  }
  state_ = output.state;
  return output;
}

bool PolicyRuntime::stop(std::string* error_message) noexcept {
  if (!initialized_ || closed_) {
    copy_error(error_message, "PolicyRuntime is not initialized.");
    return false;
  }
  if (!active_) {
    state_ = PolicyState::kStopped;
    copy_error(error_message, {});
    return true;
  }

  bool ok = true;
  std::string detail;
  if (active_kind_ == PolicyKind::kRlTcn) {
    if (rl_tcn_ != nullptr) {
      rl_tcn_->close();
      rl_tcn_.reset();
    }
  } else if (tcn_pd_ != nullptr) {
    tcn_pd_->request_shutdown("Policy run stopped.");
    tcn_pd_.reset();
  }

  active_ = false;
  state_ = ok ? PolicyState::kStopped : PolicyState::kFault;
  copy_error(error_message, detail);
  return ok;
}

void PolicyRuntime::close() noexcept {
  if (closed_) {
    return;
  }
  closed_ = true;
  active_ = false;
  state_ = PolicyState::kStopped;
  if (tcn_pd_ != nullptr) {
    tcn_pd_->request_shutdown("PolicyRuntime closed.");
    tcn_pd_.reset();
  }
  if (rl_tcn_ != nullptr) {
    rl_tcn_->close();
    rl_tcn_.reset();
  }
  initialized_ = false;
}

bool PolicyRuntime::is_active() const noexcept { return active_; }

PolicyKind PolicyRuntime::active_kind() const noexcept { return active_kind_; }

PolicyState PolicyRuntime::state() const noexcept { return state_; }

bool PolicyRuntime::validate_model_packages(
    std::string* error_message) noexcept {
  auto rl = std::make_unique<gexo::deploy::Runtime>();
  std::string detail;
  if (!rl->initialize(rl_tcn_model_directory_, &detail)) {
    copy_error(error_message, "RL+TCN validation failed: " + detail);
    return false;
  }
  rl->close();

  auto tcn_pd = std::make_unique<gexo::deploy_tcn_pd::Runtime>();
  if (!tcn_pd->initialize(tcn_pd_model_directory_, &detail)) {
    copy_error(error_message, "TCN+PD validation failed: " + detail);
    return false;
  }
  tcn_pd->request_shutdown("Model package validation complete.");
  return true;
}

bool parse_policy_kind(const std::string& value, PolicyKind* kind) noexcept {
  if (kind == nullptr) {
    return false;
  }
  if (value == "rl_tcn") {
    *kind = PolicyKind::kRlTcn;
    return true;
  }
  if (value == "tcn_pd") {
    *kind = PolicyKind::kTcnPd;
    return true;
  }
  return false;
}

const char* to_string(PolicyKind kind) noexcept {
  switch (kind) {
    case PolicyKind::kRlTcn:
      return "rl_tcn";
    case PolicyKind::kTcnPd:
      return "tcn_pd";
  }
  return "unknown";
}

const char* to_string(PolicyState state) noexcept {
  switch (state) {
    case PolicyState::kStopped:
      return "STOPPED";
    case PolicyState::kWarmup:
      return "WARMUP";
    case PolicyState::kReady:
      return "READY";
    case PolicyState::kFault:
      return "FAULT";
  }
  return "UNKNOWN";
}

}  // namespace gexo::control
