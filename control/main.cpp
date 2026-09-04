#include "control_contract.hpp"
#include "policy_runtime.hpp"
#include "rs02_motor_group.hpp"

#include <ament_index_cpp/get_package_share_directory.hpp>
#include <rclcpp/executors/single_threaded_executor.hpp>
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/imu.hpp>
#include <std_srvs/srv/set_bool.hpp>

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace gexo::control {
namespace {

using namespace std::chrono_literals;
using contract::kAxesPerImu;
using contract::kDeployDivider;
using contract::kImuCount;
using contract::kImuNames;
using contract::kJointCount;

constexpr auto kControlPeriod = 5ms;

struct ImuSample {
  std::array<float, kAxesPerImu> angular_velocity{};
  std::array<float, kAxesPerImu> specific_force{};
  std::chrono::steady_clock::time_point received_at{};
  std::uint64_t sequence{0};
  bool valid{false};
};

struct MotorState {
  JointVector position_rad{};
  JointVector velocity_rad_s{};
  bool valid{false};
};

struct SafetyDecision {
  JointVector torque_nm{};
  bool policy_output_allowed{false};
  bool stop_required{false};
  std::string reason;
};

enum class SafeMotorMode { kZeroTorque, kDamping };

class SafetyLayer final {
 public:
  SafetyLayer(bool allow_nonzero_output, JointVector torque_limit_nm)
      : allow_nonzero_output_(allow_nonzero_output),
        torque_limit_nm_(torque_limit_nm) {
    for (float limit : torque_limit_nm_) {
      if (!std::isfinite(limit) || limit < 0.0F ||
          limit > contract::kAppliedTorqueLimitNm) {
        throw std::invalid_argument(
            "Safety torque limits must be finite and in [0, 6] Nm.");
      }
    }
  }

  bool arm(const JointVector& current_position, std::string* error) {
    if (!all_finite(current_position)) {
      if (error != nullptr) {
        *error = "Cannot record q_enable from non-finite joint position.";
      }
      return false;
    }
    q_enable_ = current_position;
    armed_ = true;
    return true;
  }

  void disarm() noexcept {
    armed_ = false;
    q_enable_.fill(0.0F);
  }

  SafetyDecision evaluate(bool policy_ready, bool imu_healthy,
                          bool motor_healthy,
                          const JointVector& position_rad,
                          const JointVector& velocity_rad_s,
                          const JointVector& requested_torque_nm) const {
    SafetyDecision decision;
    if (!armed_) {
      decision.reason = "safety layer is not armed";
      return decision;
    }
    if (!motor_healthy) {
      decision.reason = "motor feedback is incomplete or stale";
      return decision;
    }
    for (std::size_t joint = 0; joint < kJointCount; ++joint) {
      if (!std::isfinite(position_rad[joint]) ||
          !std::isfinite(velocity_rad_s[joint])) {
        decision.reason = "joint state contains NaN or Inf";
        decision.stop_required = true;
        return decision;
      }
      if (std::fabs(position_rad[joint] - q_enable_[joint]) >
          contract::kPositionExcursionLimitRad) {
        decision.reason = "joint position exceeded q_enable +/- 0.8 rad";
        decision.stop_required = true;
        return decision;
      }
      if (std::fabs(velocity_rad_s[joint]) >
          contract::kVelocityLimitRadS) {
        decision.reason = "joint velocity exceeded 2.0 rad/s";
        decision.stop_required = true;
        return decision;
      }
    }
    if (!policy_ready) {
      decision.reason = "policy is not READY";
      return decision;
    }
    if (!imu_healthy) {
      decision.reason = "IMU snapshot is incomplete or stale";
      return decision;
    }
    if (!allow_nonzero_output_) {
      decision.reason = "nonzero policy output is disabled";
      return decision;
    }
    for (std::size_t joint = 0; joint < kJointCount; ++joint) {
      if (!std::isfinite(requested_torque_nm[joint])) {
        decision.reason = "policy torque contains NaN or Inf";
        decision.stop_required = true;
        return decision;
      }
      decision.torque_nm[joint] = std::clamp(
          requested_torque_nm[joint], -torque_limit_nm_[joint],
          torque_limit_nm_[joint]);
    }
    decision.policy_output_allowed = true;
    return decision;
  }

 private:
  static bool all_finite(const JointVector& values) noexcept {
    return std::all_of(values.begin(), values.end(),
                       [](float value) { return std::isfinite(value); });
  }

  bool allow_nonzero_output_{false};
  bool armed_{false};
  JointVector torque_limit_nm_{};
  JointVector q_enable_{};
};

JointVector joint_parameter(const std::vector<double>& values,
                            const char* name) {
  if (values.size() != kJointCount) {
    throw std::invalid_argument(std::string(name) + " must have four values.");
  }
  JointVector result{};
  for (std::size_t joint = 0; joint < kJointCount; ++joint) {
    if (!std::isfinite(values[joint])) {
      throw std::invalid_argument(std::string(name) + " must be finite.");
    }
    result[joint] = static_cast<float>(values[joint]);
  }
  return result;
}

std::array<std::array<float, 9>, kImuCount> imu_rotations(
    const std::vector<double>& values) {
  if (values.size() != kImuCount * 9) {
    throw std::invalid_argument("imu_axis_rotation must have 36 values.");
  }
  std::array<std::array<float, 9>, kImuCount> result{};
  for (std::size_t imu = 0; imu < kImuCount; ++imu) {
    for (std::size_t element = 0; element < 9; ++element) {
      const double value = values[imu * 9 + element];
      if (!std::isfinite(value)) {
        throw std::invalid_argument("imu_axis_rotation must be finite.");
      }
      result[imu][element] = static_cast<float>(value);
    }
  }
  return result;
}

std::array<float, 3> rotate(const std::array<float, 9>& matrix,
                            const std::array<float, 3>& input) {
  std::array<float, 3> output{};
  for (std::size_t row = 0; row < 3; ++row) {
    for (std::size_t column = 0; column < 3; ++column) {
      output[row] += matrix[row * 3 + column] * input[column];
    }
  }
  return output;
}

bool finite3(const std::array<float, 3>& values) {
  return std::all_of(values.begin(), values.end(),
                     [](float value) { return std::isfinite(value); });
}

}  // namespace

class GexoControlNode final : public rclcpp::Node {
 public:
  GexoControlNode() : Node("gexo_control_node"), safety_(load_safety()) {
    const auto share = std::filesystem::path(
        ament_index_cpp::get_package_share_directory("gexo_control"));
    const auto rl_parameter =
        declare_parameter<std::string>("rl_model_directory", "");
    const auto pd_parameter =
        declare_parameter<std::string>("tcn_pd_model_directory", "");
    const auto rl_directory = rl_parameter.empty()
                                  ? share / "models/rl_tcn"
                                  : std::filesystem::path(rl_parameter);
    const auto pd_directory = pd_parameter.empty()
                                  ? share / "models/tcn_pd"
                                  : std::filesystem::path(pd_parameter);
    declare_parameter<std::string>("policy_mode", "rl_tcn");

    std::string error;
    if (!policy_.initialize(rl_directory, pd_directory, &error)) {
      throw std::runtime_error(error);
    }
    configure_imu();
    configure_motor();
    enable_service_ = create_service<std_srvs::srv::SetBool>(
        "~/set_policy_enabled",
        [this](const std_srvs::srv::SetBool::Request::SharedPtr request,
               std_srvs::srv::SetBool::Response::SharedPtr response) {
          set_policy_enabled(request->data, response.get());
        });
    control_timer_ =
        create_wall_timer(kControlPeriod, [this] { control_tick(); });
    RCLCPP_INFO(get_logger(), "Control node ready; hardware output is disabled by default.");
  }

  ~GexoControlNode() override { shutdown(); }

  void shutdown() noexcept {
    if (shutdown_complete_) {
      return;
    }
    shutdown_complete_ = true;
    requested_torque_nm_.fill(0.0F);
    applied_logical_torque_nm_.fill(0.0F);
    safety_.disarm();
    send_safe_motor_command();
    if (motor_initialized_) {
      motors_.stop_all();
      motor_initialized_ = false;
    }
    policy_.close();
  }

 private:
  SafetyLayer load_safety() {
    const bool allow =
        declare_parameter<bool>("safety.allow_nonzero_output", false);
    const auto limits = joint_parameter(
        declare_parameter<std::vector<double>>(
            "safety.torque_limit_nm", {6.0, 6.0, 6.0, 6.0}),
        "safety.torque_limit_nm");
    return SafetyLayer(allow, limits);
  }

  void configure_imu() {
    const auto topics = declare_parameter<std::vector<std::string>>(
        "imu_topics", {"/A1/ahrs", "/A2/ahrs", "/B1/ahrs", "/B2/ahrs"});
    if (topics.size() != kImuCount) {
      throw std::invalid_argument("imu_topics must have four entries.");
    }
    std::vector<double> default_rotation;
    for (std::size_t imu = 0; imu < kImuCount; ++imu) {
      default_rotation.insert(default_rotation.end(),
                              contract::kPublishedToLinkRotation.begin(),
                              contract::kPublishedToLinkRotation.end());
    }
    imu_axis_rotation_ = imu_rotations(
        declare_parameter<std::vector<double>>("imu_axis_rotation",
                                               default_rotation));
    const int timeout_ms = declare_parameter<int>("imu_timeout_ms", 30);
    if (timeout_ms <= 0) {
      throw std::invalid_argument("imu_timeout_ms must be positive.");
    }
    imu_timeout_ = std::chrono::milliseconds(timeout_ms);

    auto qos = rclcpp::QoS(rclcpp::KeepLast(1));
    qos.reliable().durability_volatile();
    for (std::size_t imu = 0; imu < kImuCount; ++imu) {
      imu_subscriptions_[imu] = create_subscription<sensor_msgs::msg::Imu>(
          topics[imu], qos,
          [this, imu](sensor_msgs::msg::Imu::SharedPtr message) {
            receive_imu(imu, *message);
          });
      RCLCPP_INFO(get_logger(), "%s <- %s", kImuNames[imu], topics[imu].c_str());
    }
  }

  void configure_motor() {
    motor_hardware_enabled_ =
        declare_parameter<bool>("motor.hardware_enabled", false);
    const bool mapping_confirmed =
        declare_parameter<bool>("motor.mapping_confirmed", false);
    const bool zero_calibrated =
        declare_parameter<bool>("motor.zero_offset_calibrated", false);
    const auto safe_mode =
        declare_parameter<std::string>("motor.safe_output_mode", "zero_torque");
    if (safe_mode == "zero_torque") {
      safe_motor_mode_ = SafeMotorMode::kZeroTorque;
    } else if (safe_mode == "damping") {
      safe_motor_mode_ = SafeMotorMode::kDamping;
    } else {
      throw std::invalid_argument(
          "motor.safe_output_mode must be zero_torque or damping.");
    }
    motor_zero_offset_rad_ = joint_parameter(
        declare_parameter<std::vector<double>>(
            "motor.zero_offset_rad", {0.0, 0.0, 0.0, 0.0}),
        "motor.zero_offset_rad");
    dry_run_position_rad_ = joint_parameter(
        declare_parameter<std::vector<double>>(
            "dry_run.position_rad", {0.0, 0.0, 0.0, 0.0}),
        "dry_run.position_rad");
    dry_run_velocity_rad_s_ = joint_parameter(
        declare_parameter<std::vector<double>>(
            "dry_run.velocity_rad_s", {0.0, 0.0, 0.0, 0.0}),
        "dry_run.velocity_rad_s");

    const int timeout_ms =
        declare_parameter<int>("motor.feedback_timeout_ms", 30);
    const int can_timeout =
        declare_parameter<int>("motor.can_timeout_ticks", 600);
    const double torque_limit =
        declare_parameter<double>("motor.protocol_torque_limit_nm", 6.0);
    if (timeout_ms <= 0 || can_timeout <= 0 ||
        !std::isfinite(torque_limit) || torque_limit <= 0.0 ||
        torque_limit > contract::kAppliedTorqueLimitNm) {
      throw std::invalid_argument("Motor timing or torque limit is invalid.");
    }
    motor_feedback_timeout_ = std::chrono::milliseconds(timeout_ms);

    if (!motor_hardware_enabled_) {
      RCLCPP_WARN(get_logger(), "Motor hardware disabled; using logical dry-run q/dq.");
      return;
    }
    if (!mapping_confirmed || !zero_calibrated) {
      throw std::runtime_error(
          "Motor mapping and zero offsets must be confirmed before hardware enable.");
    }
    std::string error;
    if (!motors_.open_all(&error) ||
        !motors_.configure_all(static_cast<float>(torque_limit),
                               static_cast<std::uint32_t>(can_timeout), &error) ||
        !motors_.enable_all(&error)) {
      motors_.stop_all();
      throw std::runtime_error("RS02 initialization failed: " + error);
    }
    motor_initialized_ = true;
    if (!send_safe_motor_command()) {
      motors_.stop_all();
      motor_initialized_ = false;
      throw std::runtime_error("RS02 initial safe command failed.");
    }
  }

  void receive_imu(std::size_t imu, const sensor_msgs::msg::Imu& message) {
    const std::array<float, 3> gyro{
        static_cast<float>(message.angular_velocity.x),
        static_cast<float>(message.angular_velocity.y),
        static_cast<float>(message.angular_velocity.z)};
    const std::array<float, 3> acceleration{
        static_cast<float>(message.linear_acceleration.x),
        static_cast<float>(message.linear_acceleration.y),
        static_cast<float>(message.linear_acceleration.z)};
    auto& sample = imu_samples_[imu];
    if (!finite3(gyro) || !finite3(acceleration)) {
      sample.valid = false;
      return;
    }
    sample.angular_velocity = rotate(imu_axis_rotation_[imu], gyro);
    sample.specific_force = rotate(imu_axis_rotation_[imu], acceleration);
    sample.received_at = std::chrono::steady_clock::now();
    ++sample.sequence;
    sample.valid = true;
  }

  bool imu_healthy(bool require_new) const {
    const auto now = std::chrono::steady_clock::now();
    for (std::size_t imu = 0; imu < kImuCount; ++imu) {
      const auto& sample = imu_samples_[imu];
      if (!sample.valid || now - sample.received_at > imu_timeout_ ||
          (require_new && sample.sequence == consumed_imu_sequence_[imu])) {
        return false;
      }
    }
    return true;
  }

  void consume_imu() {
    for (std::size_t imu = 0; imu < kImuCount; ++imu) {
      consumed_imu_sequence_[imu] = imu_samples_[imu].sequence;
    }
  }

  bool read_motor_state(MotorState* state) {
    if (!motor_hardware_enabled_) {
      state->position_rad = dry_run_position_rad_;
      state->velocity_rad_s = dry_run_velocity_rad_s_;
      state->valid = true;
      return true;
    }
    std::string error;
    if (!motor_initialized_ || !motors_.update_all(&error)) {
      RCLCPP_ERROR_THROTTLE(get_logger(), *get_clock(), 1000,
                            "RS02 feedback failed: %s", error.c_str());
      return false;
    }
    const auto now = std::chrono::steady_clock::now();
    JointVector motor_position{};
    JointVector motor_velocity{};
    for (std::size_t joint = 0; joint < kJointCount; ++joint) {
      const auto& feedback = motors_.motors()[joint]->feedback();
      if (!feedback.valid || feedback.fault_bits != 0 ||
          now - feedback.received_at > motor_feedback_timeout_) {
        return false;
      }
      motor_position[joint] = feedback.position_rad;
      motor_velocity[joint] = feedback.velocity_rad_s;
    }
    state->position_rad = contract::motor_position_to_logical(
        motor_position, motor_zero_offset_rad_);
    state->velocity_rad_s = contract::motor_velocity_to_logical(motor_velocity);
    state->valid = true;
    return true;
  }

  SensorFrame sensor_frame(const MotorState& motor) const {
    contract::ImuVector gyro{};
    contract::ImuVector acceleration{};
    for (std::size_t imu = 0; imu < kImuCount; ++imu) {
      std::copy(imu_samples_[imu].angular_velocity.begin(),
                imu_samples_[imu].angular_velocity.end(),
                gyro.begin() + imu * kAxesPerImu);
      std::copy(imu_samples_[imu].specific_force.begin(),
                imu_samples_[imu].specific_force.end(),
                acceleration.begin() + imu * kAxesPerImu);
    }
    return contract::make_sensor_frame(motor.position_rad, motor.velocity_rad_s,
                                       gyro, acceleration);
  }

  JointVector previous_applied_action() const {
    JointVector action{};
    if (!policy_.is_active() || policy_.active_kind() != PolicyKind::kRlTcn) {
      return action;
    }
    for (std::size_t joint = 0; joint < kJointCount; ++joint) {
      action[joint] = std::clamp(
          applied_logical_torque_nm_[joint] /
              contract::kRlTrainingActionScaleNm,
          -1.0F, 1.0F);
    }
    return action;
  }

  void control_tick() {
    if (shutdown_complete_) {
      return;
    }
    MotorState motor;
    const bool motor_healthy = read_motor_state(&motor);
    if (motor_healthy) {
      latest_motor_state_ = motor;
    }

    if (policy_.is_active() && tick_ % kDeployDivider == 0) {
      if (motor_healthy && imu_healthy(true)) {
        const auto result =
            policy_.step(sensor_frame(motor), previous_applied_action());
        consume_imu();
        requested_torque_nm_ = result.state == PolicyState::kReady
                                   ? result.target_torque_nm
                                   : JointVector{};
        if (result.state != last_policy_state_) {
          RCLCPP_INFO(get_logger(), "%s policy state: %s",
                      to_string(policy_.active_kind()), to_string(result.state));
          last_policy_state_ = result.state;
        }
        if (result.state == PolicyState::kFault) {
          RCLCPP_ERROR(get_logger(), "Deploy fault: %s", result.diagnostic.c_str());
          safe_stop(true);
          ++tick_;
          return;
        }
      } else {
        requested_torque_nm_.fill(0.0F);
      }
    }

    const bool ready = policy_.is_active() &&
                       policy_.state() == PolicyState::kReady &&
                       !fault_latched_;
    const auto decision = safety_.evaluate(
        ready, imu_healthy(false), motor_healthy, motor.position_rad,
        motor.velocity_rad_s, requested_torque_nm_);
    if (decision.stop_required) {
      RCLCPP_ERROR(get_logger(), "Safety stop: %s", decision.reason.c_str());
      safe_stop(true);
      ++tick_;
      return;
    }
    const bool sent = decision.policy_output_allowed
                          ? send_motor_torque(decision.torque_nm)
                          : send_safe_motor_command();
    if (!sent) {
      safe_stop(true);
      motors_.stop_all();
    } else {
      applied_logical_torque_nm_ = decision.policy_output_allowed
                                       ? decision.torque_nm
                                       : JointVector{};
    }
    ++tick_;
  }

  bool send_motor_torque(const JointVector& logical_torque) noexcept {
    if (!motor_hardware_enabled_ || !motor_initialized_) {
      return true;
    }
    const auto motor_torque = contract::logical_torque_to_motor(logical_torque);
    gexo::motor::Rs02MotorGroup::Commands commands{};
    for (std::size_t joint = 0; joint < kJointCount; ++joint) {
      commands[joint] = gexo::motor::make_torque_command(motor_torque[joint]);
    }
    std::string error;
    if (!motors_.send_all(commands, &error)) {
      RCLCPP_ERROR(get_logger(), "RS02 torque command failed: %s", error.c_str());
      return false;
    }
    return true;
  }

  bool send_safe_motor_command() noexcept {
    if (!motor_hardware_enabled_ || !motor_initialized_) {
      return true;
    }
    gexo::motor::Rs02MotorGroup::Commands commands{};
    if (safe_motor_mode_ == SafeMotorMode::kDamping) {
      commands.fill(gexo::motor::make_damping_command(contract::kSafeDampingKd));
    } else {
      commands.fill(gexo::motor::make_torque_command(0.0F));
    }
    std::string error;
    if (!motors_.send_all(commands, &error)) {
      RCLCPP_ERROR(get_logger(), "RS02 safe command failed: %s", error.c_str());
      return false;
    }
    return true;
  }

  bool safe_stop(bool latch_fault) noexcept {
    requested_torque_nm_.fill(0.0F);
    applied_logical_torque_nm_.fill(0.0F);
    safety_.disarm();
    std::string error;
    const bool stopped = policy_.stop(&error);
    const bool safe_sent = send_safe_motor_command();
    fault_latched_ = fault_latched_ || latch_fault || !stopped || !safe_sent;
    last_policy_state_ = PolicyState::kStopped;
    return stopped && safe_sent;
  }

  void set_policy_enabled(bool enabled,
                          std_srvs::srv::SetBool::Response* response) {
    if (!enabled) {
      response->success = safe_stop(false);
      response->message = response->success
                              ? "Policy closed and safe output applied."
                              : "Policy close failed.";
      return;
    }
    if (fault_latched_) {
      response->success = false;
      response->message = "A fault is latched; restart the node.";
      return;
    }
    if (!latest_motor_state_.valid) {
      response->success = false;
      response->message = "No valid motor state is available for q_enable.";
      return;
    }
    if (policy_.is_active() && !safe_stop(false)) {
      response->success = false;
      response->message = "Previous policy run could not be closed.";
      return;
    }
    PolicyKind kind{};
    if (!parse_policy_kind(get_parameter("policy_mode").as_string(), &kind)) {
      response->success = false;
      response->message = "policy_mode must be rl_tcn or tcn_pd.";
      return;
    }
    std::string error;
    if (!safety_.arm(latest_motor_state_.position_rad, &error) ||
        !policy_.start(kind, &error)) {
      safety_.disarm();
      fault_latched_ = true;
      response->success = false;
      response->message = error;
      return;
    }
    applied_logical_torque_nm_.fill(0.0F);
    for (std::size_t imu = 0; imu < kImuCount; ++imu) {
      consumed_imu_sequence_[imu] = imu_samples_[imu].sequence;
    }
    last_policy_state_ = PolicyState::kStopped;
    response->success = true;
    response->message = std::string("Started ") + to_string(kind) +
                        "; q_enable recorded and warmup started.";
  }

  SafetyLayer safety_;
  PolicyRuntime policy_;
  gexo::motor::Rs02MotorGroup motors_;
  std::array<ImuSample, kImuCount> imu_samples_{};
  std::array<std::uint64_t, kImuCount> consumed_imu_sequence_{};
  std::array<std::array<float, 9>, kImuCount> imu_axis_rotation_{};
  std::array<rclcpp::Subscription<sensor_msgs::msg::Imu>::SharedPtr, kImuCount>
      imu_subscriptions_{};
  rclcpp::Service<std_srvs::srv::SetBool>::SharedPtr enable_service_;
  rclcpp::TimerBase::SharedPtr control_timer_;
  JointVector motor_zero_offset_rad_{};
  JointVector dry_run_position_rad_{};
  JointVector dry_run_velocity_rad_s_{};
  JointVector requested_torque_nm_{};
  JointVector applied_logical_torque_nm_{};
  MotorState latest_motor_state_{};
  std::chrono::milliseconds imu_timeout_{30};
  std::chrono::milliseconds motor_feedback_timeout_{30};
  PolicyState last_policy_state_{PolicyState::kStopped};
  SafeMotorMode safe_motor_mode_{SafeMotorMode::kZeroTorque};
  std::uint64_t tick_{0};
  bool motor_hardware_enabled_{false};
  bool motor_initialized_{false};
  bool fault_latched_{false};
  bool shutdown_complete_{false};
};

}  // namespace gexo::control

int main(int argc, char** argv) {
  rclcpp::init(argc, argv);
  try {
    auto node = std::make_shared<gexo::control::GexoControlNode>();
    rclcpp::executors::SingleThreadedExecutor executor;
    executor.add_node(node);
    executor.spin();
    node->shutdown();
    executor.remove_node(node);
    node.reset();
    rclcpp::shutdown();
    return 0;
  } catch (const std::exception& error) {
    RCLCPP_FATAL(rclcpp::get_logger("gexo_control"), "%s", error.what());
    rclcpp::shutdown();
    return 1;
  }
}
