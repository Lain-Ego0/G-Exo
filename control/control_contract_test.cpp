#include "control_contract.hpp"

#include <cstdlib>
#include <iostream>
#include <stdexcept>

namespace {

void require(bool condition, const char* message) {
  if (!condition) {
    throw std::runtime_error(message);
  }
}

}  // namespace

int main() try {
  using namespace gexo::control::contract;
  static_assert(kDeployDivider == 4);
  static_assert(kFirstReadyFrame == 151);
  static_assert(kSensorDimension == 32);

  const JointVector motor_q{1.0F, 2.0F, 3.0F, 4.0F};
  const JointVector zero{0.1F, 0.2F, 0.3F, 0.4F};
  require(motor_position_to_logical(motor_q, zero) ==
              JointVector{0.9F, -1.8F, 2.7F, -3.6F},
          "motor position direction contract mismatch");
  require(motor_velocity_to_logical(motor_q) ==
              JointVector{1.0F, -2.0F, 3.0F, -4.0F},
          "motor velocity direction contract mismatch");
  require(logical_torque_to_motor(motor_q) ==
              JointVector{1.0F, -2.0F, 3.0F, -4.0F},
          "logical torque direction contract mismatch");
  require(published_imu_to_link({1.0F, 2.0F, 3.0F}) ==
              std::array<float, 3>{-3.0F, -1.0F, 2.0F},
          "IMU inverse rotation contract mismatch");

  ImuVector gyro{};
  ImuVector acceleration{};
  for (std::size_t index = 0; index < gyro.size(); ++index) {
    gyro[index] = static_cast<float>(10 + index);
    acceleration[index] = static_cast<float>(30 + index);
  }
  const auto sensor = make_sensor_frame(motor_q, zero, gyro, acceleration);
  require(sensor[0] == 1.0F && sensor[4] == 0.1F && sensor[8] == 10.0F &&
              sensor[19] == 21.0F && sensor[20] == 30.0F &&
              sensor[31] == 41.0F,
          "sensor32 ordering contract mismatch");
  return EXIT_SUCCESS;
} catch (const std::exception& error) {
  std::cerr << "Control contract test failed: " << error.what() << '\n';
  return EXIT_FAILURE;
}
