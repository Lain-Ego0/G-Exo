#include "rs02_motor.hpp"

#include <algorithm>
#include <cerrno>
#include <cmath>
#include <cstring>
#include <limits>
#include <poll.h>
#include <utility>

#include <fcntl.h>
#include <linux/can/raw.h>
#include <net/if.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <unistd.h>

namespace gexo::motor {
namespace {

constexpr std::uint8_t kCommunicationMotionControl = 0x01;
constexpr std::uint8_t kCommunicationFeedback = 0x02;
constexpr std::uint8_t kCommunicationEnable = 0x03;
constexpr std::uint8_t kCommunicationStop = 0x04;
constexpr std::uint8_t kCommunicationReadParameter = 0x11;
constexpr std::uint8_t kCommunicationWriteParameter = 0x12;

constexpr std::uint16_t kRunModeIndex = 0x7005;
constexpr std::uint16_t kTorqueLimitIndex = 0x700B;
constexpr std::uint16_t kCanTimeoutIndex = 0x7028;
constexpr std::uint16_t kMechanicalPositionIndex = 0x7019;
constexpr std::uint16_t kIqIndex = 0x701A;
constexpr std::uint16_t kMechanicalVelocityIndex = 0x701B;
constexpr std::uint16_t kBusVoltageIndex = 0x701C;

constexpr float kPositionLimitRad = 4.0F * static_cast<float>(M_PI);
constexpr float kVelocityLimitRadS = 44.0F;
constexpr float kTorqueLimitNm = 17.0F;
constexpr float kKpLimit = 500.0F;
constexpr float kKdLimit = 5.0F;

void set_error(std::string* destination, const std::string& message) {
  if (destination != nullptr) {
    *destination = message;
  }
}

std::string errno_message(const char* operation) {
  return std::string(operation) + ": " + std::strerror(errno);
}

std::uint16_t encode_u16(float value, float minimum, float maximum) {
  const float clamped = std::clamp(value, minimum, maximum);
  const float normalized = (clamped - minimum) / (maximum - minimum);
  return static_cast<std::uint16_t>(
      normalized * static_cast<float>(std::numeric_limits<std::uint16_t>::max()));
}

float decode_u16(std::uint16_t value, float minimum, float maximum) {
  const float normalized = static_cast<float>(value) /
                           static_cast<float>(
                               std::numeric_limits<std::uint16_t>::max());
  return minimum + normalized * (maximum - minimum);
}

std::uint16_t read_be_u16(const std::uint8_t* data) {
  return static_cast<std::uint16_t>(
      (static_cast<std::uint16_t>(data[0]) << 8U) |
      static_cast<std::uint16_t>(data[1]));
}

can_frame make_simple_frame(std::uint8_t communication_type,
                            std::uint8_t master_id,
                            std::uint8_t motor_id) {
  can_frame frame{};
  frame.can_id = CAN_EFF_FLAG |
                 (static_cast<canid_t>(communication_type) << 24U) |
                 (static_cast<canid_t>(master_id) << 8U) |
                 static_cast<canid_t>(motor_id);
  frame.can_dlc = CAN_MAX_DLEN;
  return frame;
}

can_frame make_parameter_frame(std::uint8_t communication_type,
                               std::uint8_t master_id, std::uint8_t motor_id,
                               std::uint16_t index) {
  can_frame frame =
      make_simple_frame(communication_type, master_id, motor_id);
  frame.data[0] = static_cast<std::uint8_t>(index & 0xFFU);
  frame.data[1] = static_cast<std::uint8_t>((index >> 8U) & 0xFFU);
  return frame;
}

void write_le_u32(std::uint8_t* destination, std::uint32_t value) {
  destination[0] = static_cast<std::uint8_t>(value & 0xFFU);
  destination[1] = static_cast<std::uint8_t>((value >> 8U) & 0xFFU);
  destination[2] = static_cast<std::uint8_t>((value >> 16U) & 0xFFU);
  destination[3] = static_cast<std::uint8_t>((value >> 24U) & 0xFFU);
}

std::uint32_t read_le_u32(const std::uint8_t* source) {
  return static_cast<std::uint32_t>(source[0]) |
         (static_cast<std::uint32_t>(source[1]) << 8U) |
         (static_cast<std::uint32_t>(source[2]) << 16U) |
         (static_cast<std::uint32_t>(source[3]) << 24U);
}

std::uint16_t read_le_u16(const std::uint8_t* source) {
  return static_cast<std::uint16_t>(
      static_cast<std::uint16_t>(source[0]) |
      (static_cast<std::uint16_t>(source[1]) << 8U));
}

}  // namespace

Rs02Command make_damping_command(float kd) {
  return Rs02Command{0.0F, 0.0F, 0.0F, 0.0F, kd};
}

Rs02Command make_torque_command(float torque_nm) {
  return Rs02Command{0.0F, 0.0F, torque_nm, 0.0F, 0.0F};
}

Rs02Command make_position_command(float position_rad, float kp, float kd) {
  return Rs02Command{position_rad, 0.0F, 0.0F, kp, kd};
}

Rs02Command make_velocity_command(float velocity_rad_s, float kd) {
  return Rs02Command{0.0F, velocity_rad_s, 0.0F, 0.0F, kd};
}

can_frame encode_rs02_motion_frame(std::uint8_t motor_id,
                                   const Rs02Command& command) {
  const std::uint16_t torque =
      encode_u16(command.torque_nm, -kTorqueLimitNm, kTorqueLimitNm);
  const std::uint16_t position = encode_u16(
      command.position_rad, -kPositionLimitRad, kPositionLimitRad);
  const std::uint16_t velocity = encode_u16(
      command.velocity_rad_s, -kVelocityLimitRadS, kVelocityLimitRadS);
  const std::uint16_t kp = encode_u16(command.kp, 0.0F, kKpLimit);
  const std::uint16_t kd = encode_u16(command.kd, 0.0F, kKdLimit);

  can_frame frame{};
  frame.can_id = CAN_EFF_FLAG |
                 (static_cast<canid_t>(kCommunicationMotionControl) << 24U) |
                 (static_cast<canid_t>(torque) << 8U) |
                 static_cast<canid_t>(motor_id);
  frame.can_dlc = CAN_MAX_DLEN;
  frame.data[0] = static_cast<std::uint8_t>(position >> 8U);
  frame.data[1] = static_cast<std::uint8_t>(position & 0xFFU);
  frame.data[2] = static_cast<std::uint8_t>(velocity >> 8U);
  frame.data[3] = static_cast<std::uint8_t>(velocity & 0xFFU);
  frame.data[4] = static_cast<std::uint8_t>(kp >> 8U);
  frame.data[5] = static_cast<std::uint8_t>(kp & 0xFFU);
  frame.data[6] = static_cast<std::uint8_t>(kd >> 8U);
  frame.data[7] = static_cast<std::uint8_t>(kd & 0xFFU);
  return frame;
}

Rs02Motor::Rs02Motor(std::string can_interface, std::uint8_t motor_id,
                     std::uint8_t master_id)
    : can_interface_(std::move(can_interface)),
      motor_id_(motor_id),
      master_id_(master_id) {}

Rs02Motor::~Rs02Motor() { close(); }

bool Rs02Motor::open(std::string* error_message) noexcept {
  if (is_open()) {
    return true;
  }

  socket_fd_ = ::socket(PF_CAN, SOCK_RAW, CAN_RAW);
  if (socket_fd_ < 0) {
    set_error(error_message, errno_message("socket(PF_CAN)"));
    return false;
  }

  ifreq interface_request{};
  if (can_interface_.size() >= IFNAMSIZ) {
    set_error(error_message, "CAN interface name is too long: " + can_interface_);
    close();
    return false;
  }
  std::strncpy(interface_request.ifr_name, can_interface_.c_str(), IFNAMSIZ - 1);
  if (::ioctl(socket_fd_, SIOCGIFINDEX, &interface_request) < 0) {
    set_error(error_message, errno_message("ioctl(SIOCGIFINDEX)"));
    close();
    return false;
  }

  sockaddr_can address{};
  address.can_family = AF_CAN;
  address.can_ifindex = interface_request.ifr_ifindex;
  if (::bind(socket_fd_, reinterpret_cast<sockaddr*>(&address), sizeof(address)) <
      0) {
    set_error(error_message, errno_message("bind(SocketCAN)"));
    close();
    return false;
  }

  can_filter filter{};
  filter.can_id = CAN_EFF_FLAG | (static_cast<canid_t>(motor_id_) << 8U);
  filter.can_mask = CAN_EFF_FLAG | (static_cast<canid_t>(0xFFU) << 8U);
  if (::setsockopt(socket_fd_, SOL_CAN_RAW, CAN_RAW_FILTER, &filter,
                   sizeof(filter)) < 0) {
    set_error(error_message, errno_message("setsockopt(CAN_RAW_FILTER)"));
    close();
    return false;
  }

  const int flags = ::fcntl(socket_fd_, F_GETFL, 0);
  if (flags < 0 || ::fcntl(socket_fd_, F_SETFL, flags | O_NONBLOCK) < 0) {
    set_error(error_message, errno_message("fcntl(O_NONBLOCK)"));
    close();
    return false;
  }
  return true;
}

void Rs02Motor::close() noexcept {
  if (socket_fd_ >= 0) {
    ::close(socket_fd_);
    socket_fd_ = -1;
  }
  feedback_ = {};
}

bool Rs02Motor::is_open() const noexcept { return socket_fd_ >= 0; }

bool Rs02Motor::set_motion_mode(std::string* error_message) noexcept {
  return write_u8_parameter(kRunModeIndex, 0, error_message);
}

bool Rs02Motor::set_torque_limit(float torque_limit_nm,
                                 std::string* error_message) noexcept {
  if (!std::isfinite(torque_limit_nm) || torque_limit_nm <= 0.0F ||
      torque_limit_nm > kTorqueLimitNm) {
    set_error(error_message, "RS02 torque limit must be in (0, 17] Nm");
    return false;
  }
  return write_float_parameter(kTorqueLimitIndex, torque_limit_nm,
                               error_message);
}

bool Rs02Motor::set_can_timeout(std::uint32_t timeout_ticks,
                                std::string* error_message) noexcept {
  if (timeout_ticks == 0) {
    set_error(error_message, "RS02 CAN timeout must be non-zero");
    return false;
  }
  return write_u32_parameter(kCanTimeoutIndex, timeout_ticks, error_message);
}

bool Rs02Motor::enable(std::string* error_message) noexcept {
  const can_frame frame =
      make_simple_frame(kCommunicationEnable, master_id_, motor_id_);
  if (!send_frame(frame, error_message)) {
    return false;
  }

  // Ignore an older Reset-mode feedback frame that may already be queued and
  // require an explicit Motor-mode response to this enable sequence.
  for (int attempt = 0; attempt < 4; ++attempt) {
    if (!wait_for_feedback(std::chrono::milliseconds(50), error_message)) {
      return false;
    }
    if (feedback_.fault_bits != 0) {
      set_error(error_message,
                "motor reported fault bits after enable: " +
                    std::to_string(feedback_.fault_bits));
      return false;
    }
    if (feedback_.mode == 2) {
      return true;
    }
  }
  set_error(error_message, "motor did not enter Motor mode after enable");
  return false;
}

bool Rs02Motor::stop(std::string* error_message) noexcept {
  if (!is_open()) {
    return true;
  }
  can_frame frame = make_simple_frame(kCommunicationStop, master_id_, motor_id_);
  return send_frame(frame, error_message);
}

bool Rs02Motor::clear_fault(std::string* error_message) noexcept {
  if (!is_open()) {
    set_error(error_message, "motor socket is not open");
    return false;
  }
  can_frame frame = make_simple_frame(kCommunicationStop, master_id_, motor_id_);
  frame.data[0] = 1U;
  return send_frame(frame, error_message);
}

bool Rs02Motor::send(const Rs02Command& command,
                     std::string* error_message) noexcept {
  if (!std::isfinite(command.torque_nm) ||
      !std::isfinite(command.position_rad) ||
      !std::isfinite(command.velocity_rad_s) || !std::isfinite(command.kp) ||
      !std::isfinite(command.kd)) {
    set_error(error_message, "motion command contains a non-finite value");
    return false;
  }
  return send_frame(encode_rs02_motion_frame(motor_id_, command), error_message);
}

bool Rs02Motor::damping(float kd, std::string* error_message) noexcept {
  return send(make_damping_command(kd), error_message);
}

bool Rs02Motor::torque(float torque_nm, std::string* error_message) noexcept {
  return send(make_torque_command(torque_nm), error_message);
}

bool Rs02Motor::position(float position_rad, float kp, float kd,
                         std::string* error_message) noexcept {
  return send(make_position_command(position_rad, kp, kd), error_message);
}

bool Rs02Motor::velocity(float velocity_rad_s, float kd,
                         std::string* error_message) noexcept {
  return send(make_velocity_command(velocity_rad_s, kd), error_message);
}

bool Rs02Motor::update_feedback(std::string* error_message) noexcept {
  if (!is_open()) {
    set_error(error_message, "motor socket is not open");
    return false;
  }

  while (true) {
    can_frame frame{};
    const ssize_t received = ::recv(socket_fd_, &frame, sizeof(frame), 0);
    if (received == static_cast<ssize_t>(sizeof(frame))) {
      if (!decode_feedback_frame(frame, error_message)) {
        return false;
      }
      continue;
    }
    if (received < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
      return true;
    }
    if (received < 0 && errno == EINTR) {
      continue;
    }
    if (received < 0) {
      set_error(error_message, errno_message("recv(SocketCAN)"));
      return false;
    }
    set_error(error_message, "received a truncated CAN frame");
    return false;
  }
}

const Rs02Feedback& Rs02Motor::feedback() const noexcept {
  return feedback_;
}

const std::string& Rs02Motor::interface() const noexcept {
  return can_interface_;
}

std::uint8_t Rs02Motor::motor_id() const noexcept { return motor_id_; }

bool Rs02Motor::send_frame(const can_frame& frame,
                           std::string* error_message) noexcept {
  if (!is_open()) {
    set_error(error_message, "motor socket is not open");
    return false;
  }
  const ssize_t written = ::write(socket_fd_, &frame, sizeof(frame));
  if (written != static_cast<ssize_t>(sizeof(frame))) {
    set_error(error_message, errno_message("write(SocketCAN)"));
    return false;
  }
  return true;
}

bool Rs02Motor::write_u8_parameter(std::uint16_t index, std::uint8_t value,
                                   std::string* error_message) noexcept {
  can_frame frame = make_parameter_frame(
      kCommunicationWriteParameter, master_id_, motor_id_, index);
  frame.data[4] = value;
  return send_frame(frame, error_message) &&
         wait_for_feedback(std::chrono::milliseconds(50), error_message);
}

bool Rs02Motor::write_u32_parameter(std::uint16_t index, std::uint32_t value,
                                    std::string* error_message) noexcept {
  can_frame frame = make_parameter_frame(
      kCommunicationWriteParameter, master_id_, motor_id_, index);
  write_le_u32(&frame.data[4], value);
  return send_frame(frame, error_message) &&
         wait_for_feedback(std::chrono::milliseconds(50), error_message);
}

bool Rs02Motor::write_float_parameter(std::uint16_t index, float value,
                                      std::string* error_message) noexcept {
  static_assert(sizeof(float) == sizeof(std::uint32_t),
                "RS02 parameter protocol requires IEEE-754 float32");
  std::uint32_t bits = 0;
  std::memcpy(&bits, &value, sizeof(bits));
  return write_u32_parameter(index, bits, error_message);
}

bool Rs02Motor::read_mechanical_position(float* value,
                                         std::string* error_message) noexcept {
  return read_float_parameter(kMechanicalPositionIndex, value, error_message);
}

bool Rs02Motor::read_mechanical_velocity(float* value,
                                         std::string* error_message) noexcept {
  return read_float_parameter(kMechanicalVelocityIndex, value, error_message);
}

bool Rs02Motor::read_iq(float* value, std::string* error_message) noexcept {
  return read_float_parameter(kIqIndex, value, error_message);
}

bool Rs02Motor::read_bus_voltage(float* value,
                                std::string* error_message) noexcept {
  return read_float_parameter(kBusVoltageIndex, value, error_message);
}

bool Rs02Motor::read_float_parameter(std::uint16_t index, float* value,
                                     std::string* error_message) noexcept {
  if (value == nullptr) {
    set_error(error_message, "parameter output pointer is null");
    return false;
  }

  const can_frame request = make_parameter_frame(
      kCommunicationReadParameter, master_id_, motor_id_, index);
  if (!send_frame(request, error_message)) {
    return false;
  }

  const auto deadline = std::chrono::steady_clock::now() +
                        std::chrono::milliseconds(50);
  while (std::chrono::steady_clock::now() < deadline) {
    const auto remaining = std::chrono::duration_cast<std::chrono::milliseconds>(
        deadline - std::chrono::steady_clock::now());
    pollfd descriptor{socket_fd_, POLLIN, 0};
    const int result =
        ::poll(&descriptor, 1, std::max(1, static_cast<int>(remaining.count())));
    if (result < 0 && errno == EINTR) {
      continue;
    }
    if (result < 0) {
      set_error(error_message, errno_message("poll(SocketCAN)"));
      return false;
    }
    if (result == 0) {
      break;
    }

    can_frame response{};
    const ssize_t received = ::recv(socket_fd_, &response, sizeof(response), 0);
    if (received < 0 && (errno == EAGAIN || errno == EWOULDBLOCK ||
                         errno == EINTR)) {
      continue;
    }
    if (received != static_cast<ssize_t>(sizeof(response))) {
      set_error(error_message, received < 0 ? errno_message("recv(SocketCAN)")
                                             : "received a truncated CAN frame");
      return false;
    }

    const canid_t response_id = response.can_id & CAN_EFF_MASK;
    const std::uint8_t communication_type =
        static_cast<std::uint8_t>((response_id >> 24U) & 0x1FU);
    if (communication_type == kCommunicationFeedback) {
      if (!decode_feedback_frame(response, error_message)) {
        return false;
      }
      continue;
    }
    if ((response.can_id & CAN_EFF_FLAG) == 0 ||
        communication_type != kCommunicationReadParameter ||
        response.can_dlc != CAN_MAX_DLEN ||
        static_cast<std::uint8_t>((response_id >> 8U) & 0xFFU) != motor_id_ ||
        static_cast<std::uint8_t>(response_id & 0xFFU) != master_id_ ||
        read_le_u16(&response.data[0]) != index) {
      continue;
    }

    if (static_cast<std::uint8_t>((response_id >> 16U) & 0xFFU) != 0U) {
      set_error(error_message, "motor rejected parameter read");
      return false;
    }

    const std::uint32_t bits = read_le_u32(&response.data[4]);
    std::memcpy(value, &bits, sizeof(bits));
    if (!std::isfinite(*value)) {
      set_error(error_message, "parameter response is not finite");
      return false;
    }
    return true;
  }

  set_error(error_message, "timed out waiting for RS02 parameter response");
  return false;
}

bool Rs02Motor::wait_for_feedback(
    std::chrono::milliseconds timeout, std::string* error_message) noexcept {
  const std::uint64_t initial_sequence = feedback_.sequence;
  const auto deadline = std::chrono::steady_clock::now() + timeout;

  while (std::chrono::steady_clock::now() < deadline) {
    const auto remaining = std::chrono::duration_cast<std::chrono::milliseconds>(
        deadline - std::chrono::steady_clock::now());
    pollfd descriptor{socket_fd_, POLLIN, 0};
    const int poll_result =
        ::poll(&descriptor, 1, std::max(1, static_cast<int>(remaining.count())));
    if (poll_result < 0 && errno == EINTR) {
      continue;
    }
    if (poll_result < 0) {
      set_error(error_message, errno_message("poll(SocketCAN)"));
      return false;
    }
    if (poll_result == 0) {
      break;
    }
    if (!update_feedback(error_message)) {
      return false;
    }
    if (feedback_.sequence > initial_sequence) {
      return true;
    }
  }
  set_error(error_message, "timed out waiting for RS02 feedback");
  return false;
}

bool Rs02Motor::decode_feedback_frame(
    const can_frame& frame, std::string* error_message) noexcept {
  if ((frame.can_id & CAN_EFF_FLAG) == 0) {
    return true;
  }
  const canid_t id = frame.can_id & CAN_EFF_MASK;
  const std::uint8_t communication_type =
      static_cast<std::uint8_t>((id >> 24U) & 0x1FU);
  if (communication_type != kCommunicationFeedback) {
    return true;
  }
  if (frame.can_dlc != CAN_MAX_DLEN) {
    set_error(error_message, "RS02 feedback DLC is not 8");
    return false;
  }

  const std::uint8_t source_id =
      static_cast<std::uint8_t>((id >> 8U) & 0xFFU);
  const std::uint8_t destination_id = static_cast<std::uint8_t>(id & 0xFFU);
  if (source_id != motor_id_ || destination_id != master_id_) {
    return true;
  }

  feedback_.position_rad = decode_u16(read_be_u16(&frame.data[0]),
                                      -kPositionLimitRad, kPositionLimitRad);
  feedback_.velocity_rad_s = decode_u16(read_be_u16(&frame.data[2]),
                                       -kVelocityLimitRadS, kVelocityLimitRadS);
  feedback_.torque_nm = decode_u16(read_be_u16(&frame.data[4]),
                                  -kTorqueLimitNm, kTorqueLimitNm);
  feedback_.temperature_c =
      static_cast<float>(read_be_u16(&frame.data[6])) * 0.1F;
  feedback_.fault_bits = static_cast<std::uint8_t>((id >> 16U) & 0x3FU);
  feedback_.mode = static_cast<std::uint8_t>((id >> 22U) & 0x03U);
  feedback_.received_at = std::chrono::steady_clock::now();
  feedback_.valid = true;
  ++feedback_.sequence;

  if (feedback_.fault_bits != 0) {
    set_error(error_message,
              "motor reported fault bits: " +
                  std::to_string(feedback_.fault_bits));
    return false;
  }
  return true;
}

}  // namespace gexo::motor
