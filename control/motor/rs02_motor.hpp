#pragma once

#include <chrono>
#include <cstdint>
#include <string>

#include <linux/can.h>

namespace gexo::motor {

struct Rs02Command {
  float position_rad{0.0F};
  float velocity_rad_s{0.0F};
  float torque_nm{0.0F};
  float kp{0.0F};
  float kd{0.0F};
};

struct Rs02Feedback {
  float position_rad{0.0F};
  float velocity_rad_s{0.0F};
  float torque_nm{0.0F};
  float temperature_c{0.0F};
  std::uint8_t mode{0};
  std::uint8_t fault_bits{0};
  std::uint64_t sequence{0};
  bool valid{false};
  std::chrono::steady_clock::time_point received_at{};
};

// All helpers use RS02 run_mode=0. They only select fields in the same
// five-parameter motion-control frame.
Rs02Command make_damping_command(float kd);
Rs02Command make_torque_command(float torque_nm);
Rs02Command make_position_command(float position_rad, float kp, float kd);
Rs02Command make_velocity_command(float velocity_rad_s, float kd);

can_frame encode_rs02_motion_frame(std::uint8_t motor_id,
                                   const Rs02Command& command);

class Rs02Motor final {
 public:
  Rs02Motor(std::string can_interface, std::uint8_t motor_id,
            std::uint8_t master_id = 0xFD);
  ~Rs02Motor();

  Rs02Motor(const Rs02Motor&) = delete;
  Rs02Motor& operator=(const Rs02Motor&) = delete;

  bool open(std::string* error = nullptr) noexcept;
  void close() noexcept;
  bool is_open() const noexcept;

  bool set_motion_mode(std::string* error = nullptr) noexcept;
  bool set_torque_limit(float torque_limit_nm,
                        std::string* error = nullptr) noexcept;
  bool set_can_timeout(std::uint32_t timeout_ticks,
                       std::string* error = nullptr) noexcept;
  bool enable(std::string* error = nullptr) noexcept;
  bool stop(std::string* error = nullptr) noexcept;
  bool clear_fault(std::string* error = nullptr) noexcept;

  bool send(const Rs02Command& command,
            std::string* error = nullptr) noexcept;
  bool damping(float kd, std::string* error = nullptr) noexcept;
  bool torque(float torque_nm, std::string* error = nullptr) noexcept;
  bool position(float position_rad, float kp, float kd,
                std::string* error = nullptr) noexcept;
  bool velocity(float velocity_rad_s, float kd,
                std::string* error = nullptr) noexcept;

  bool update_feedback(std::string* error = nullptr) noexcept;
  const Rs02Feedback& feedback() const noexcept;

  // Slow, on-demand parameter reads. Do not call these inside the 200 Hz loop.
  bool read_mechanical_position(float* value,
                                std::string* error = nullptr) noexcept;
  bool read_mechanical_velocity(float* value,
                                std::string* error = nullptr) noexcept;
  bool read_iq(float* value, std::string* error = nullptr) noexcept;
  bool read_bus_voltage(float* value,
                        std::string* error = nullptr) noexcept;

  const std::string& interface() const noexcept;
  std::uint8_t motor_id() const noexcept;

 private:
  bool send_frame(const can_frame& frame, std::string* error) noexcept;
  bool write_u8_parameter(std::uint16_t index, std::uint8_t value,
                          std::string* error) noexcept;
  bool write_u32_parameter(std::uint16_t index, std::uint32_t value,
                           std::string* error) noexcept;
  bool write_float_parameter(std::uint16_t index, float value,
                             std::string* error) noexcept;
  bool read_float_parameter(std::uint16_t index, float* value,
                            std::string* error) noexcept;
  bool wait_for_feedback(std::chrono::milliseconds timeout,
                         std::string* error) noexcept;
  bool decode_feedback_frame(const can_frame& frame,
                             std::string* error) noexcept;

  std::string can_interface_;
  std::uint8_t motor_id_;
  std::uint8_t master_id_;
  int socket_fd_{-1};
  Rs02Feedback feedback_{};
};

}  // namespace gexo::motor
