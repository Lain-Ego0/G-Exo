#include "rs02_motor_group.hpp"

#include <cmath>

namespace gexo::motor {
namespace {

constexpr float kGroupTorqueLimitNm = 6.0F;

void set_error(std::string* destination, const Rs02Motor& motor,
               const std::string& message) {
  if (destination != nullptr) {
    *destination = motor.interface() + "/" +
                   std::to_string(motor.motor_id()) + ": " + message;
  }
}

}  // namespace

Rs02MotorGroup::Rs02MotorGroup()
    : motors_{std::make_unique<Rs02Motor>("can0", 0x01),
              std::make_unique<Rs02Motor>("can0", 0x02),
              std::make_unique<Rs02Motor>("can1", 0x03),
              std::make_unique<Rs02Motor>("can1", 0x04)} {}

Rs02MotorGroup::~Rs02MotorGroup() { stop_all(); }

bool Rs02MotorGroup::open_all(std::string* error) noexcept {
  std::string detail;
  for (const auto& motor_ptr : motors_) {
    if (!motor_ptr->open(&detail)) {
      set_error(error, *motor_ptr, detail);
      return false;
    }
  }
  return true;
}

bool Rs02MotorGroup::configure_all(float torque_limit_nm,
                                   std::uint32_t can_timeout_ticks,
                                   std::string* error) noexcept {
  if (!stop_all(error)) {
    return false;
  }

  std::string detail;
  for (const auto& motor_ptr : motors_) {
    if (!motor_ptr->set_motion_mode(&detail) ||
        !motor_ptr->set_torque_limit(torque_limit_nm, &detail) ||
        !motor_ptr->set_can_timeout(can_timeout_ticks, &detail)) {
      set_error(error, *motor_ptr, detail);
      return false;
    }
  }
  return true;
}

bool Rs02MotorGroup::enable_all(std::string* error) noexcept {
  std::string detail;
  for (const auto& motor_ptr : motors_) {
    if (!motor_ptr->enable(&detail)) {
      set_error(error, *motor_ptr, detail);
      stop_all();
      return false;
    }
  }
  return true;
}

bool Rs02MotorGroup::stop_all(std::string* error) noexcept {
  bool ok = true;
  std::string detail;
  for (const auto& motor_ptr : motors_) {
    if (motor_ptr != nullptr && motor_ptr->is_open() &&
        !motor_ptr->stop(&detail)) {
      if (ok) {
        set_error(error, *motor_ptr, detail);
      }
      ok = false;
    }
  }
  return ok;
}

bool Rs02MotorGroup::clear_faults(std::string* error) noexcept {
  std::string detail;
  for (const auto& motor_ptr : motors_) {
    if (!motor_ptr->clear_fault(&detail)) {
      set_error(error, *motor_ptr, detail);
      return false;
    }
  }
  return true;
}

bool Rs02MotorGroup::send(Joint joint, const Rs02Command& command,
                          std::string* error) noexcept {
  Rs02Motor& selected_motor = motor(joint);
  if (!std::isfinite(command.torque_nm) ||
      std::fabs(command.torque_nm) > kGroupTorqueLimitNm) {
    set_error(error, selected_motor, "command torque exceeds 6 Nm");
    return false;
  }
  std::string detail;
  if (!selected_motor.send(command, &detail)) {
    set_error(error, selected_motor, detail);
    return false;
  }
  return true;
}

bool Rs02MotorGroup::send_all(const Commands& commands,
                              std::string* error) noexcept {
  std::string detail;
  for (std::size_t index = 0; index < motors_.size(); ++index) {
    if (!std::isfinite(commands[index].torque_nm) ||
        std::fabs(commands[index].torque_nm) > kGroupTorqueLimitNm) {
      set_error(error, *motors_[index], "command torque exceeds 6 Nm");
      return false;
    }
    if (!motors_[index]->send(commands[index], &detail)) {
      set_error(error, *motors_[index], detail);
      return false;
    }
  }
  return true;
}

bool Rs02MotorGroup::damping_all(float kd, std::string* error) noexcept {
  Commands commands{};
  commands.fill(make_damping_command(kd));
  return send_all(commands, error);
}

bool Rs02MotorGroup::update_all(std::string* error) noexcept {
  std::string detail;
  for (const auto& motor_ptr : motors_) {
    if (!motor_ptr->update_feedback(&detail)) {
      set_error(error, *motor_ptr, detail);
      return false;
    }
  }
  return true;
}

Rs02Motor& Rs02MotorGroup::motor(Joint joint) noexcept {
  return *motors_[static_cast<std::size_t>(joint)];
}

const Rs02Motor& Rs02MotorGroup::motor(Joint joint) const noexcept {
  return *motors_[static_cast<std::size_t>(joint)];
}

const std::array<std::unique_ptr<Rs02Motor>, Rs02MotorGroup::kMotorCount>&
Rs02MotorGroup::motors() const noexcept {
  return motors_;
}

}  // namespace gexo::motor
