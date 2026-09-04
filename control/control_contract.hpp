#pragma once

#include <array>
#include <cstddef>

namespace gexo::control::contract {

inline constexpr std::size_t kJointCount = 4;
inline constexpr std::size_t kImuCount = 4;
inline constexpr std::size_t kAxesPerImu = 3;
inline constexpr std::size_t kSensorDimension = 32;

inline constexpr std::size_t kPositionOffset = 0;
inline constexpr std::size_t kVelocityOffset = 4;
inline constexpr std::size_t kGyroscopeOffset = 8;
inline constexpr std::size_t kSpecificForceOffset = 20;

inline constexpr std::size_t kControlFrequencyHz = 200;
inline constexpr std::size_t kDeployFrequencyHz = 50;
inline constexpr std::size_t kDeployDivider =
    kControlFrequencyHz / kDeployFrequencyHz;
inline constexpr std::size_t kWarmupFrames = 150;
inline constexpr std::size_t kFirstReadyFrame = kWarmupFrames + 1;

inline constexpr float kRlTrainingActionScaleNm = 8.0F;
inline constexpr float kAppliedTorqueLimitNm = 6.0F;
inline constexpr float kSafeDampingKd = 3.0F;
inline constexpr float kPositionExcursionLimitRad = 0.8F;
inline constexpr float kVelocityLimitRadS = 2.0F;

using JointVector = std::array<float, kJointCount>;
using ImuVector = std::array<float, kImuCount * kAxesPerImu>;
using SensorFrame = std::array<float, kSensorDimension>;

// Fixed order: left hip, left knee, right hip, right knee.
inline constexpr std::array<const char*, kJointCount> kJointNames{
    "left_hip", "left_knee", "right_hip", "right_knee"};

// Fixed order: A1 left thigh, A2 left shank, B1 right thigh, B2 right shank.
inline constexpr std::array<const char*, kImuCount> kImuNames{
    "left_thigh", "left_shank", "right_thigh", "right_shank"};

inline constexpr JointVector kMotorToUrdfDirection{
    -1.0F, -1.0F, 1.0F, 1.0F};
inline constexpr JointVector kUrdfToLogicalDirection{
    -1.0F, 1.0F, 1.0F, -1.0F};
inline constexpr JointVector kMotorToLogicalDirection{
    1.0F, -1.0F, 1.0F, -1.0F};

// Inverse of ess_imu_driver2: pub=(-raw_y, raw_z, -raw_x).
inline constexpr std::array<float, 9> kPublishedToLinkRotation{
    0.0F, 0.0F, -1.0F,
    -1.0F, 0.0F, 0.0F,
    0.0F, 1.0F, 0.0F};

inline JointVector motor_position_to_logical(
    const JointVector& motor_position,
    const JointVector& zero_offset) noexcept {
  JointVector logical{};
  for (std::size_t joint = 0; joint < kJointCount; ++joint) {
    logical[joint] = kMotorToLogicalDirection[joint] *
                     (motor_position[joint] - zero_offset[joint]);
  }
  return logical;
}

inline JointVector motor_velocity_to_logical(
    const JointVector& motor_velocity) noexcept {
  JointVector logical{};
  for (std::size_t joint = 0; joint < kJointCount; ++joint) {
    logical[joint] =
        kMotorToLogicalDirection[joint] * motor_velocity[joint];
  }
  return logical;
}

inline JointVector logical_torque_to_motor(
    const JointVector& logical_torque) noexcept {
  JointVector motor{};
  for (std::size_t joint = 0; joint < kJointCount; ++joint) {
    motor[joint] = kMotorToLogicalDirection[joint] * logical_torque[joint];
  }
  return motor;
}

inline std::array<float, 3> published_imu_to_link(
    const std::array<float, 3>& published) noexcept {
  return {-published[2], -published[0], published[1]};
}

inline SensorFrame make_sensor_frame(
    const JointVector& logical_position,
    const JointVector& logical_velocity,
    const ImuVector& link_angular_velocity,
    const ImuVector& link_specific_force) noexcept {
  SensorFrame sensor{};
  for (std::size_t joint = 0; joint < kJointCount; ++joint) {
    sensor[kPositionOffset + joint] = logical_position[joint];
    sensor[kVelocityOffset + joint] = logical_velocity[joint];
  }
  for (std::size_t value = 0; value < kImuCount * kAxesPerImu; ++value) {
    sensor[kGyroscopeOffset + value] = link_angular_velocity[value];
    sensor[kSpecificForceOffset + value] = link_specific_force[value];
  }
  return sensor;
}

}  // namespace gexo::control::contract
