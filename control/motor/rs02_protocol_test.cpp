#include "rs02_motor_group.hpp"

#include <array>
#include <cstdlib>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {

void require(bool condition, const char* message) {
  if (!condition) {
    throw std::runtime_error(message);
  }
}

}  // namespace

int main() try {
  const auto damping = gexo::motor::make_damping_command(1.0F);
  require(damping.position_rad == 0.0F, "damping position must be zero");
  require(damping.velocity_rad_s == 0.0F, "damping velocity must be zero");
  require(damping.torque_nm == 0.0F, "damping torque must be zero");
  require(damping.kp == 0.0F, "damping kp must be zero");
  require(damping.kd == 1.0F, "damping kd mismatch");

  const can_frame frame =
      gexo::motor::encode_rs02_motion_frame(0x01, damping);
  require((frame.can_id & CAN_EFF_FLAG) != 0, "extended CAN flag missing");
  require((frame.can_id & CAN_EFF_MASK) == 0x017FFF01U,
          "encoded CAN id mismatch");
  require(frame.can_dlc == 8, "encoded CAN payload length mismatch");

  constexpr std::array<std::uint8_t, 8> expected{
      0x7F, 0xFF, 0x7F, 0xFF, 0x00, 0x00, 0x33, 0x33};
  for (std::size_t index = 0; index < expected.size(); ++index) {
    require(frame.data[index] == expected[index],
            "encoded CAN payload mismatch");
  }

  const auto torque = gexo::motor::make_torque_command(2.0F);
  require(torque.torque_nm == 2.0F && torque.kp == 0.0F &&
              torque.kd == 0.0F,
          "torque command mismatch");

  const auto position =
      gexo::motor::make_position_command(0.5F, 20.0F, 0.8F);
  require(position.position_rad == 0.5F && position.kp == 20.0F &&
              position.kd == 0.8F,
          "position command mismatch");

  const auto velocity = gexo::motor::make_velocity_command(-0.5F, 0.4F);
  require(velocity.velocity_rad_s == -0.5F && velocity.kd == 0.4F,
          "velocity command mismatch");

  gexo::motor::Rs02MotorGroup motors;
  require(motors.motor(gexo::motor::Joint::LeftHip).interface() == "can0" &&
              motors.motor(gexo::motor::Joint::LeftHip).motor_id() == 0x01,
          "left hip motor mapping mismatch");
  require(motors.motor(gexo::motor::Joint::LeftKnee).interface() == "can0" &&
              motors.motor(gexo::motor::Joint::LeftKnee).motor_id() == 0x02,
          "left knee motor mapping mismatch");
  require(motors.motor(gexo::motor::Joint::RightHip).interface() == "can1" &&
              motors.motor(gexo::motor::Joint::RightHip).motor_id() == 0x03,
          "right hip motor mapping mismatch");
  require(motors.motor(gexo::motor::Joint::RightKnee).interface() == "can1" &&
              motors.motor(gexo::motor::Joint::RightKnee).motor_id() == 0x04,
          "right knee motor mapping mismatch");

  std::string error;
  require(!motors.send(gexo::motor::Joint::LeftHip,
                       gexo::motor::make_torque_command(6.1F), &error),
          "over-limit torque must be rejected");
  require(error.find("6 Nm") != std::string::npos,
          "over-limit rejection must report the limit");
  return EXIT_SUCCESS;
} catch (const std::exception& error) {
  std::cerr << "RS02 protocol test failed: " << error.what() << '\n';
  return EXIT_FAILURE;
}
