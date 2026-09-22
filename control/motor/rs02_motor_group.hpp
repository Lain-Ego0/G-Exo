#pragma once

#include "rs02_motor.hpp"

#include <array>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>

namespace gexo::motor {

enum class Joint : std::size_t {
  LeftHip = 0,
  LeftKnee = 1,
  RightHip = 2,
  RightKnee = 3,
};

class Rs02MotorGroup final {
 public:
  static constexpr std::size_t kMotorCount = 4;
  using Commands = std::array<Rs02Command, kMotorCount>;

  Rs02MotorGroup();
  ~Rs02MotorGroup();

  Rs02MotorGroup(const Rs02MotorGroup&) = delete;
  Rs02MotorGroup& operator=(const Rs02MotorGroup&) = delete;

  bool open_all(std::string* error = nullptr) noexcept;
  bool configure_all(float torque_limit_nm = 6.0F,
                     std::uint32_t can_timeout_ticks = 600,
                     std::string* error = nullptr) noexcept;
  bool enable_all(std::string* error = nullptr) noexcept;
  bool stop_all(std::string* error = nullptr) noexcept;
  bool clear_faults(std::string* error = nullptr) noexcept;

  bool send(Joint joint, const Rs02Command& command,
            std::string* error = nullptr) noexcept;
  bool send_all(const Commands& commands,
                std::string* error = nullptr) noexcept;
  bool damping_all(float kd, std::string* error = nullptr) noexcept;
  bool update_all(std::string* error = nullptr) noexcept;

  Rs02Motor& motor(Joint joint) noexcept;
  const Rs02Motor& motor(Joint joint) const noexcept;
  const std::array<std::unique_ptr<Rs02Motor>, kMotorCount>& motors()
      const noexcept;

 private:
  std::array<std::unique_ptr<Rs02Motor>, kMotorCount> motors_;
};

}  // namespace gexo::motor
