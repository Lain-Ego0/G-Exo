#include "gexo_deploy.hpp"
#include "sha256.hpp"

#include <onnxruntime_cxx_api.h>

#include <json/json.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <utility>
#include <vector>

namespace gexo::deploy {
namespace {

constexpr std::size_t kJointCount = 4;
constexpr std::size_t kImuCount = 4;
constexpr std::size_t kImuAxisCount = 3;
constexpr std::size_t kTcnHistoryLength = 50;
constexpr std::size_t kTcnTargetDimension = 12;
constexpr std::size_t kTcnHorizonCount = 2;
constexpr std::size_t kTcnOutputDimension =
    kTcnTargetDimension * kTcnHorizonCount;
constexpr std::size_t kTcnFeatureDimension = 16;
constexpr std::size_t kActorFrameDimension = 36;
constexpr std::size_t kActorHistoryLength = 4;
constexpr std::size_t kActorHistoryDimension =
    kActorFrameDimension * kActorHistoryLength;
constexpr std::size_t kActorObservationDimension = 160;

constexpr std::array<int64_t, 3> kTcnInputShape{1, 32, 50};
constexpr std::array<int64_t, 3> kTcnOutputShape{1, 2, 12};
constexpr std::array<int64_t, 2> kActorInputShape{1, 160};
constexpr std::array<int64_t, 2> kActorOutputShape{1, 4};

class ConfigurationError final : public std::runtime_error {
 public:
  using std::runtime_error::runtime_error;
};

class ModelInterfaceError final : public std::runtime_error {
 public:
  using std::runtime_error::runtime_error;
};

class ModelIntegrityError final : public std::runtime_error {
 public:
  using std::runtime_error::runtime_error;
};

class NonFiniteError final : public std::runtime_error {
 public:
  using std::runtime_error::runtime_error;
};

template <std::size_t FrameDimension, std::size_t Capacity>
class FrameRing final {
 public:
  using Frame = std::array<float, FrameDimension>;

  void append(const Frame& frame) noexcept {
    frames_[next_] = frame;
    next_ = (next_ + 1) % Capacity;
    count_ = std::min(count_ + 1, Capacity);
  }

  const Frame& chronological(std::size_t index) const {
    if (index >= count_) {
      throw std::out_of_range("History index is out of range.");
    }
    const std::size_t oldest = count_ == Capacity ? next_ : 0;
    return frames_[(oldest + index) % Capacity];
  }

  std::size_t size() const noexcept { return count_; }

  void clear() noexcept {
    for (auto& frame : frames_) {
      frame.fill(0.0F);
    }
    next_ = 0;
    count_ = 0;
  }

 private:
  std::array<Frame, Capacity> frames_{};
  std::size_t next_{0};
  std::size_t count_{0};
};

struct TensorInterface {
  std::string name;
  std::vector<int64_t> shape;
};

struct ModelInterface {
  std::string file;
  std::string sha256;
  TensorInterface input;
  TensorInterface output;
};

struct Config {
  std::size_t warmup_steps{0};
  ModelInterface tcn_model;
  ModelInterface actor_model;

  std::array<float, kSensorDimension> tcn_input_mean{};
  std::array<float, kSensorDimension> tcn_input_std{};
  std::array<float, kTcnTargetDimension> tcn_target_mean{};
  std::array<float, kTcnTargetDimension> tcn_target_std{};

  std::array<float, kJointCount> motor_position_scale{};
  std::array<float, kJointCount> motor_position_offset{};
  std::array<float, kJointCount> motor_velocity_scale{};
  std::array<float, kImuCount * kImuAxisCount * kImuAxisCount>
      imu_rotation{};

  std::array<float, kJointCount> target_position_scale{};
  std::array<float, kJointCount> target_position_offset{};
  std::array<float, kJointCount> target_velocity_scale{};

  std::array<float, kTcnFeatureDimension> feature_mean{};
  std::array<float, kTcnFeatureDimension> feature_std{};
  std::array<float, kTcnFeatureDimension> feature_clip{};

  std::array<float, kActorFrameDimension> actor_frame_scale{};
  float actor_frame_clip{0.0F};
};

const Json::Value& require_member(const Json::Value& parent,
                                  const char* key,
                                  Json::ValueType type,
                                  const std::string& path) {
  if (!parent.isMember(key)) {
    throw ConfigurationError("Missing configuration field: " + path + "." +
                             key);
  }
  const Json::Value& value = parent[key];
  if (value.type() != type) {
    throw ConfigurationError("Invalid type for configuration field: " + path +
                             "." + key);
  }
  return value;
}

const Json::Value& require_object(const Json::Value& parent,
                                  const char* key,
                                  const std::string& path) {
  return require_member(parent, key, Json::objectValue, path);
}

std::string require_string(const Json::Value& parent,
                           const char* key,
                           const std::string& path) {
  return require_member(parent, key, Json::stringValue, path).asString();
}

template <std::size_t Size>
std::array<float, Size> require_float_array(const Json::Value& parent,
                                            const char* key,
                                            const std::string& path,
                                            bool positive = false) {
  const Json::Value& value =
      require_member(parent, key, Json::arrayValue, path);
  if (value.size() != Size) {
    throw ConfigurationError("Configuration field " + path + "." + key +
                             " must contain " + std::to_string(Size) +
                             " values.");
  }
  std::array<float, Size> result{};
  for (std::size_t index = 0; index < Size; ++index) {
    if (!value[static_cast<Json::ArrayIndex>(index)].isNumeric()) {
      throw ConfigurationError("Configuration field " + path + "." + key +
                               " must contain only numbers.");
    }
    const float parsed =
        value[static_cast<Json::ArrayIndex>(index)].asFloat();
    if (!std::isfinite(parsed) || (positive && parsed <= 0.0F)) {
      throw ConfigurationError("Configuration field " + path + "." + key +
                               " contains an invalid value.");
    }
    result[index] = parsed;
  }
  return result;
}

template <std::size_t Size>
void require_string_array(
    const Json::Value& parent, const char* key, const std::string& path,
    const std::array<const char*, Size>& expected) {
  const Json::Value& value =
      require_member(parent, key, Json::arrayValue, path);
  if (value.size() != Size) {
    throw ConfigurationError("Configuration field " + path + "." + key +
                             " has the wrong length.");
  }
  for (std::size_t index = 0; index < Size; ++index) {
    const Json::Value& element = value[static_cast<Json::ArrayIndex>(index)];
    if (!element.isString() || element.asString() != expected[index]) {
      throw ConfigurationError("Configuration field " + path + "." + key +
                               " has an incompatible order.");
    }
  }
}

template <std::size_t Size>
void require_integer_array(const Json::Value& parent, const char* key,
                           const std::string& path,
                           const std::array<int64_t, Size>& expected) {
  const Json::Value& value =
      require_member(parent, key, Json::arrayValue, path);
  if (value.size() != Size) {
    throw ConfigurationError("Configuration field " + path + "." + key +
                             " has the wrong length.");
  }
  for (std::size_t index = 0; index < Size; ++index) {
    const Json::Value& element = value[static_cast<Json::ArrayIndex>(index)];
    if (!element.isIntegral() || element.asInt64() != expected[index]) {
      throw ConfigurationError("Configuration field " + path + "." + key +
                               " has incompatible values.");
    }
  }
}

std::vector<int64_t> require_shape(const Json::Value& parent,
                                   const std::string& path) {
  const Json::Value& value =
      require_member(parent, "shape", Json::arrayValue, path);
  if (value.empty()) {
    throw ConfigurationError("Configuration tensor shape cannot be empty: " +
                             path + ".shape");
  }
  std::vector<int64_t> shape;
  shape.reserve(value.size());
  for (const auto& dimension : value) {
    if (!dimension.isIntegral() || dimension.asInt64() <= 0) {
      throw ConfigurationError("Configuration tensor shape must be static and "
                               "positive: " +
                               path + ".shape");
    }
    shape.push_back(dimension.asInt64());
  }
  return shape;
}

TensorInterface parse_tensor_interface(const Json::Value& value,
                                       const std::string& path) {
  TensorInterface interface;
  interface.name = require_string(value, "name", path);
  interface.shape = require_shape(value, path);
  const std::string dtype = require_string(value, "dtype", path);
  if (interface.name.empty() || dtype != "float32") {
    throw ConfigurationError(path +
                             " must declare a non-empty name and float32 dtype.");
  }
  return interface;
}

ModelInterface parse_model_interface(const Json::Value& value,
                                     const std::string& path) {
  ModelInterface interface;
  interface.file = require_string(value, "file", path);
  interface.sha256 = require_string(value, "sha256", path);
  interface.input = parse_tensor_interface(
      require_object(value, "input", path), path + ".input");
  interface.output = parse_tensor_interface(
      require_object(value, "output", path), path + ".output");
  const std::filesystem::path relative_file(interface.file);
  if (interface.file.empty() || relative_file.has_parent_path() ||
      interface.sha256.size() != 64 ||
      interface.sha256.find_first_not_of("0123456789abcdef") !=
          std::string::npos) {
    throw ConfigurationError(path +
                             " has an invalid model filename or SHA-256 value.");
  }
  return interface;
}

template <std::size_t Size>
void require_exact_shape(const std::vector<int64_t>& actual,
                         const std::array<int64_t, Size>& expected,
                         const std::string& label) {
  if (actual.size() != expected.size() ||
      !std::equal(actual.begin(), actual.end(), expected.begin())) {
    throw ConfigurationError(label + " does not match the fixed Deploy contract.");
  }
}

Config load_config(const std::filesystem::path& path) {
  std::ifstream stream(path);
  if (!stream) {
    throw ConfigurationError("Cannot open model configuration: " +
                             path.string());
  }
  Json::CharReaderBuilder builder;
  builder["collectComments"] = false;
  Json::Value root;
  JSONCPP_STRING errors;
  if (!Json::parseFromStream(builder, stream, &root, &errors) ||
      !root.isObject()) {
    throw ConfigurationError("Cannot parse model configuration: " + errors);
  }
  if (require_string(root, "schema", "root") != "gexo_deploy_model_v1") {
    throw ConfigurationError("Unsupported model configuration schema.");
  }
  const Json::Value& warmup = root["warmup_steps"];
  if (!warmup.isIntegral() || warmup.asInt64() != 150) {
    throw ConfigurationError("warmup_steps must be exactly 150.");
  }

  const Json::Value& schema_version = root["schema_version"];
  if (!schema_version.isIntegral() || schema_version.asInt() != 1) {
    throw ConfigurationError("Unsupported model configuration schema version.");
  }
  const Json::Value& contracts = require_object(root, "protocols", "root");
  if (require_string(contracts, "runtime_sensor", "root.protocols") !=
          "gexo_sensor32_runtime_v1" ||
      require_string(contracts, "tcn_sensor", "root.protocols") !=
          "phase12_tcn32_interleaved_v1" ||
      require_string(contracts, "actor_observation", "root.protocols") !=
          "gexo_actor160_explicit_tcn_v1") {
    throw ConfigurationError("Model package protocol is incompatible.");
  }
  if (require_string(contracts, "warmup", "root.protocols") !=
      "gexo_zero_assist_preroll150_v1") {
    throw ConfigurationError("Model package warmup protocol is incompatible.");
  }
  const Json::Value& frequency = root["control_frequency_hz"];
  if (!frequency.isNumeric() || !std::isfinite(frequency.asDouble()) ||
      std::fabs(frequency.asDouble() - 50.0) > 1.0e-9) {
    throw ConfigurationError("Model package control frequency must be 50 Hz.");
  }
  require_string_array<kJointCount>(
      root, "joint_order", "root",
      {"left_hip", "left_knee", "right_hip", "right_knee"});

  Config config;
  config.warmup_steps = static_cast<std::size_t>(warmup.asUInt64());
  const Json::Value& models = require_object(root, "models", "root");
  config.tcn_model = parse_model_interface(
      require_object(models, "tcn", "root.models"), "root.models.tcn");
  config.actor_model = parse_model_interface(
      require_object(models, "actor", "root.models"), "root.models.actor");
  require_exact_shape(config.tcn_model.input.shape, kTcnInputShape,
                      "TCN input shape");
  require_exact_shape(config.tcn_model.output.shape, kTcnOutputShape,
                      "TCN output shape");
  require_exact_shape(config.actor_model.input.shape, kActorInputShape,
                      "Actor input shape");
  require_exact_shape(config.actor_model.output.shape, kActorOutputShape,
                      "Actor output shape");

  const Json::Value& tcn =
      require_object(root, "tcn_preprocessing", "root");
  const Json::Value& tcn_history = tcn["history_length"];
  if (!tcn_history.isIntegral() ||
      tcn_history.asInt64() != static_cast<int64_t>(kTcnHistoryLength)) {
    throw ConfigurationError("TCN history_length must be 50.");
  }
  require_integer_array<kTcnHorizonCount>(tcn, "horizon_steps",
                                          "root.tcn_preprocessing", {5, 10});
  require_string_array<3>(
      tcn, "target_order", "root.tcn_preprocessing",
      {"q4", "dq4", "biological_moment4"});
  require_string_array<4>(
      tcn, "feature_order", "root.tcn_preprocessing",
      {"delta_q(+5)", "delta_dq(+5)", "delta_q(+10)",
       "delta_dq(+10)"});
  config.tcn_input_mean = require_float_array<kSensorDimension>(
      tcn, "input_mean", "root.tcn_preprocessing");
  config.tcn_input_std = require_float_array<kSensorDimension>(
      tcn, "input_std", "root.tcn_preprocessing", true);
  config.tcn_target_mean = require_float_array<kTcnTargetDimension>(
      tcn, "target_mean", "root.tcn_preprocessing");
  config.tcn_target_std = require_float_array<kTcnTargetDimension>(
      tcn, "target_std", "root.tcn_preprocessing", true);

  config.motor_position_scale = require_float_array<kJointCount>(
      tcn, "motor_position_scale", "root.tcn_preprocessing");
  config.motor_position_offset = require_float_array<kJointCount>(
      tcn, "motor_position_offset", "root.tcn_preprocessing");
  config.motor_velocity_scale = require_float_array<kJointCount>(
      tcn, "motor_velocity_scale", "root.tcn_preprocessing");

  const Json::Value& rotation = require_member(
      tcn, "imu_rotation", Json::arrayValue, "root.tcn_preprocessing");
  if (rotation.size() != kImuCount) {
    throw ConfigurationError("imu_rotation must have shape [4, 3, 3].");
  }
  for (std::size_t imu = 0; imu < kImuCount; ++imu) {
    const Json::Value& matrix = rotation[static_cast<Json::ArrayIndex>(imu)];
    if (!matrix.isArray() || matrix.size() != kImuAxisCount) {
      throw ConfigurationError("imu_rotation must have shape [4, 3, 3].");
    }
    for (std::size_t row = 0; row < kImuAxisCount; ++row) {
      const Json::Value& row_value =
          matrix[static_cast<Json::ArrayIndex>(row)];
      if (!row_value.isArray() || row_value.size() != kImuAxisCount) {
        throw ConfigurationError("imu_rotation must have shape [4, 3, 3].");
      }
      for (std::size_t column = 0; column < kImuAxisCount; ++column) {
        const Json::Value& element =
            row_value[static_cast<Json::ArrayIndex>(column)];
        if (!element.isNumeric()) {
          throw ConfigurationError("imu_rotation contains an invalid value.");
        }
        const float parsed = element.asFloat();
        if (!std::isfinite(parsed)) {
          throw ConfigurationError("imu_rotation contains an invalid value.");
        }
        config.imu_rotation[(imu * 3 + row) * 3 + column] = parsed;
      }
    }
  }

  config.target_position_scale = require_float_array<kJointCount>(
      tcn, "target_position_scale", "root.tcn_preprocessing");
  config.target_position_offset = require_float_array<kJointCount>(
      tcn, "target_position_offset", "root.tcn_preprocessing");
  config.target_velocity_scale = require_float_array<kJointCount>(
      tcn, "target_velocity_scale", "root.tcn_preprocessing");

  config.feature_mean = require_float_array<kTcnFeatureDimension>(
      tcn, "feature_mean", "root.tcn_preprocessing");
  config.feature_std = require_float_array<kTcnFeatureDimension>(
      tcn, "feature_std", "root.tcn_preprocessing", true);
  config.feature_clip = require_float_array<kTcnFeatureDimension>(
      tcn, "feature_clip", "root.tcn_preprocessing", true);

  const Json::Value& actor =
      require_object(root, "actor_preprocessing", "root");
  const Json::Value& actor_history = actor["history_length"];
  if (!actor_history.isIntegral() ||
      actor_history.asInt64() != static_cast<int64_t>(kActorHistoryLength)) {
    throw ConfigurationError("Actor history_length must be 4.");
  }
  require_string_array<5>(
      actor, "frame_order", "root.actor_preprocessing",
      {"q4", "dq4", "gyro12", "specific_force12",
       "previous_applied_action4"});
  config.actor_frame_scale = require_float_array<kActorFrameDimension>(
      actor, "frame_scale", "root.actor_preprocessing", true);
  const Json::Value& actor_clip = actor["frame_clip"];
  if (!actor_clip.isNumeric() || !std::isfinite(actor_clip.asFloat()) ||
      actor_clip.asFloat() <= 0.0F) {
    throw ConfigurationError("actor.frame_clip must be positive and finite.");
  }
  config.actor_frame_clip = actor_clip.asFloat();
  const auto output_clip = require_float_array<2>(
      actor, "output_clip", "root.actor_preprocessing");
  if (output_clip[0] != -1.0F || output_clip[1] != 1.0F) {
    throw ConfigurationError("Actor output_clip must be [-1, 1].");
  }
  return config;
}

template <std::size_t Size>
bool all_finite(const std::array<float, Size>& values) noexcept {
  return std::all_of(values.begin(), values.end(),
                     [](float value) { return std::isfinite(value); });
}

void validate_session_interface(Ort::Session& session,
                                const ModelInterface& expected,
                                const std::string& label) {
  if (session.GetInputCount() != 1 || session.GetOutputCount() != 1) {
    throw ModelInterfaceError(label +
                              " must have exactly one input and one output.");
  }
  Ort::AllocatorWithDefaultOptions allocator;
  const auto input_name = session.GetInputNameAllocated(0, allocator);
  const auto output_name = session.GetOutputNameAllocated(0, allocator);
  if (expected.input.name != input_name.get() ||
      expected.output.name != output_name.get()) {
    throw ModelInterfaceError(label + " tensor names do not match config.");
  }
  const auto input_type = session.GetInputTypeInfo(0);
  const auto output_type = session.GetOutputTypeInfo(0);
  const auto input_info = input_type.GetTensorTypeAndShapeInfo();
  const auto output_info = output_type.GetTensorTypeAndShapeInfo();
  if (input_info.GetElementType() != ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT ||
      output_info.GetElementType() != ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT) {
    throw ModelInterfaceError(label + " tensor dtype must be float32.");
  }
  const auto input_shape = input_info.GetShape();
  const auto output_shape = output_info.GetShape();
  if (input_shape != expected.input.shape ||
      output_shape != expected.output.shape) {
    const auto format_shape = [](const std::vector<int64_t>& shape) {
      std::ostringstream stream;
      stream << '[';
      for (std::size_t index = 0; index < shape.size(); ++index) {
        if (index != 0) {
          stream << ',';
        }
        stream << shape[index];
      }
      stream << ']';
      return stream.str();
    };
    throw ModelInterfaceError(
        label + " tensor shape does not match config: input=" +
        format_shape(input_shape) + ", expected_input=" +
        format_shape(expected.input.shape) + ", output=" +
        format_shape(output_shape) + ", expected_output=" +
        format_shape(expected.output.shape) + ".");
  }
}

}  // namespace

class Runtime::Impl final {
 public:
  bool initialize(const std::filesystem::path& model_directory,
                  std::string* error_message) noexcept {
    if (closed_) {
      copy_error(error_message);
      return false;
    }
    if (initialization_attempted_) {
      set_fault(ErrorCode::kConfiguration,
                "A Runtime instance cannot be initialized more than once.");
      copy_error(error_message);
      return false;
    }
    initialization_attempted_ = true;

    try {
      if (!std::filesystem::is_directory(model_directory)) {
        throw ConfigurationError("Model directory does not exist: " +
                                 model_directory.string());
      }
      config_.emplace(load_config(model_directory / "model_config.json"));
      const auto tcn_path = model_directory / config_->tcn_model.file;
      const auto actor_path = model_directory / config_->actor_model.file;
      if (!std::filesystem::is_regular_file(tcn_path) ||
          !std::filesystem::is_regular_file(actor_path)) {
        throw ConfigurationError("Model package is missing tcn.onnx or actor.onnx.");
      }
      if (detail::sha256_file(tcn_path) != config_->tcn_model.sha256) {
        throw ModelIntegrityError("TCN SHA-256 does not match model_config.json.");
      }
      if (detail::sha256_file(actor_path) != config_->actor_model.sha256) {
        throw ModelIntegrityError(
            "Actor SHA-256 does not match model_config.json.");
      }

      env_ = std::make_unique<Ort::Env>(ORT_LOGGING_LEVEL_WARNING,
                                        "gexo_deploy");
      Ort::SessionOptions options;
      options.SetExecutionMode(ExecutionMode::ORT_SEQUENTIAL);
      options.SetIntraOpNumThreads(1);
      options.SetInterOpNumThreads(1);
      options.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);
      tcn_session_ =
          std::make_unique<Ort::Session>(*env_, tcn_path.c_str(), options);
      actor_session_ =
          std::make_unique<Ort::Session>(*env_, actor_path.c_str(), options);
      validate_session_interface(*tcn_session_, config_->tcn_model, "TCN");
      validate_session_interface(*actor_session_, config_->actor_model, "Actor");

      memory_info_ = std::make_unique<Ort::MemoryInfo>(
          Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault));
      tcn_input_tensor_ = std::make_unique<Ort::Value>(
          Ort::Value::CreateTensor<float>(*memory_info_, tcn_input_.data(),
                                          tcn_input_.size(),
                                          kTcnInputShape.data(),
                                          kTcnInputShape.size()));
      tcn_output_tensor_ = std::make_unique<Ort::Value>(
          Ort::Value::CreateTensor<float>(*memory_info_, tcn_output_.data(),
                                          tcn_output_.size(),
                                          kTcnOutputShape.data(),
                                          kTcnOutputShape.size()));
      actor_input_tensor_ = std::make_unique<Ort::Value>(
          Ort::Value::CreateTensor<float>(*memory_info_, actor_input_.data(),
                                          actor_input_.size(),
                                          kActorInputShape.data(),
                                          kActorInputShape.size()));
      actor_output_tensor_ = std::make_unique<Ort::Value>(
          Ort::Value::CreateTensor<float>(*memory_info_, actor_output_.data(),
                                          actor_output_.size(),
                                          kActorOutputShape.data(),
                                          kActorOutputShape.size()));

      initialized_ = true;
      state_ = State::kWarmup;
      error_code_ = ErrorCode::kNone;
      error_message_.clear();
      copy_error(error_message);
      return true;
    } catch (const ConfigurationError& error) {
      set_fault(ErrorCode::kConfiguration, error.what());
    } catch (const ModelIntegrityError& error) {
      set_fault(ErrorCode::kModelIntegrity, error.what());
    } catch (const ModelInterfaceError& error) {
      set_fault(ErrorCode::kModelInterface, error.what());
    } catch (const Ort::Exception& error) {
      set_fault(ErrorCode::kModelInterface, error.what());
    } catch (const std::exception& error) {
      set_fault(ErrorCode::kConfiguration, error.what());
    } catch (...) {
      set_fault(ErrorCode::kConfiguration,
                "Unknown error while initializing Deploy.");
    }
    release_resources();
    copy_error(error_message);
    return false;
  }

  StepResult step(const SensorFrame& sensor,
                  const Action& previous_applied_action) noexcept {
    if (state_ == State::kFault) {
      return zero_result();
    }
    if (!initialized_ || !config_) {
      set_fault(ErrorCode::kNotInitialized, "Deploy is not initialized.");
      return zero_result();
    }
    if (!all_finite(sensor) || !all_finite(previous_applied_action)) {
      set_fault(ErrorCode::kInvalidInput,
                "sensor32 or previous_applied_action contains NaN or Inf.");
      return zero_result();
    }

    try {
      const bool should_infer =
          state_ == State::kReady || valid_steps_ >= config_->warmup_steps;
      const Action actor_history_action =
          should_infer ? previous_applied_action : Action{};
      const auto tcn_frame = make_tcn_frame(sensor);
      const auto actor_frame = make_actor_frame(sensor, actor_history_action);
      tcn_history_.append(tcn_frame);
      actor_history_.append(actor_frame);
      ++valid_steps_;

      if (tcn_history_.size() !=
              std::min(valid_steps_, kTcnHistoryLength) ||
          actor_history_.size() !=
              std::min(valid_steps_, kActorHistoryLength)) {
        set_fault(ErrorCode::kHistory, "Internal history size is inconsistent.");
        return zero_result();
      }

      if (!should_infer) {
        last_action_.fill(0.0F);
        return zero_result();
      }

      if (tcn_history_.size() != kTcnHistoryLength ||
          actor_history_.size() != kActorHistoryLength) {
        set_fault(ErrorCode::kHistory,
                  "READY requires complete TCN and Actor histories.");
        return zero_result();
      }
      ++inference_steps_;
      run_tcn(sensor);
      run_actor();
      for (std::size_t index = 0; index < kActionDimension; ++index) {
        last_action_[index] =
            std::clamp(actor_output_[index], -1.0F, 1.0F);
      }
      if (!all_finite(last_action_)) {
        set_fault(ErrorCode::kNonFinite,
                  "Clipped Actor output contains NaN or Inf.");
        return zero_result();
      }
      state_ = State::kReady;
      return StepResult{state_, last_action_, error_code_};
    } catch (const Ort::Exception& error) {
      set_fault(ErrorCode::kInference, error.what());
    } catch (const NonFiniteError& error) {
      set_fault(ErrorCode::kNonFinite, error.what());
    } catch (const std::exception& error) {
      if (state_ != State::kFault) {
        set_fault(ErrorCode::kHistory, error.what());
      }
    } catch (...) {
      set_fault(ErrorCode::kInference, "Unknown Deploy inference error.");
    }
    return zero_result();
  }

  bool reset() noexcept {
    if (!initialized_ || closed_ || state_ == State::kFault) {
      return false;
    }
    clear_run_state();
    state_ = State::kWarmup;
    error_code_ = ErrorCode::kNone;
    error_message_.clear();
    return true;
  }

  void close() noexcept {
    if (closed_) {
      return;
    }
    closed_ = true;
    if (state_ != State::kFault) {
      state_ = State::kFault;
      error_code_ = ErrorCode::kNotInitialized;
      error_message_ = "Deploy is closed.";
    }
    release_resources();
  }

  State state() const noexcept { return state_; }
  ErrorCode error_code() const noexcept { return error_code_; }
  std::string error_message() const { return error_message_; }
  std::size_t valid_steps() const noexcept { return valid_steps_; }
  std::size_t inference_steps() const noexcept { return inference_steps_; }

 private:
  std::array<float, kSensorDimension> make_tcn_frame(
      const SensorFrame& sensor) const {
    std::array<float, kSensorDimension> calibrated{};
    for (std::size_t joint = 0; joint < kJointCount; ++joint) {
      calibrated[joint] = sensor[joint] * config_->motor_position_scale[joint] +
                          config_->motor_position_offset[joint];
      calibrated[4 + joint] =
          sensor[4 + joint] * config_->motor_velocity_scale[joint];
    }
    for (std::size_t imu = 0; imu < kImuCount; ++imu) {
      for (std::size_t row = 0; row < kImuAxisCount; ++row) {
        float gyro = 0.0F;
        float acceleration = 0.0F;
        for (std::size_t column = 0; column < kImuAxisCount; ++column) {
          const float rotation =
              config_->imu_rotation[(imu * 3 + row) * 3 + column];
          gyro += rotation * sensor[8 + imu * 3 + column];
          acceleration += rotation * sensor[20 + imu * 3 + column];
        }
        calibrated[8 + imu * 3 + row] = gyro;
        calibrated[20 + imu * 3 + row] = acceleration;
      }
    }

    std::array<float, kSensorDimension> interleaved{};
    std::copy_n(calibrated.begin(), 8, interleaved.begin());
    for (std::size_t imu = 0; imu < kImuCount; ++imu) {
      const std::size_t output_base = 8 + imu * 6;
      for (std::size_t axis = 0; axis < kImuAxisCount; ++axis) {
        interleaved[output_base + axis] = calibrated[8 + imu * 3 + axis];
        interleaved[output_base + 3 + axis] =
            calibrated[20 + imu * 3 + axis];
      }
    }
    for (std::size_t index = 0; index < interleaved.size(); ++index) {
      interleaved[index] =
          (interleaved[index] - config_->tcn_input_mean[index]) /
          config_->tcn_input_std[index];
    }
    if (!all_finite(interleaved)) {
      throw NonFiniteError("Normalized TCN input contains NaN or Inf.");
    }
    return interleaved;
  }

  std::array<float, kActorFrameDimension> make_actor_frame(
      const SensorFrame& sensor, const Action& previous_action) const {
    std::array<float, kActorFrameDimension> frame{};
    for (std::size_t index = 0; index < kSensorDimension; ++index) {
      const float normalized =
          sensor[index] / config_->actor_frame_scale[index];
      if (!std::isfinite(normalized)) {
        throw NonFiniteError("Normalized Actor frame contains NaN or Inf.");
      }
      frame[index] = std::clamp(normalized, -config_->actor_frame_clip,
                                config_->actor_frame_clip);
    }
    for (std::size_t index = 0; index < kActionDimension; ++index) {
      const std::size_t frame_index = kSensorDimension + index;
      const float normalized =
          previous_action[index] / config_->actor_frame_scale[frame_index];
      if (!std::isfinite(normalized)) {
        throw NonFiniteError("Normalized Actor frame contains NaN or Inf.");
      }
      frame[frame_index] =
          std::clamp(normalized, -config_->actor_frame_clip,
                     config_->actor_frame_clip);
    }
    if (!all_finite(frame)) {
      throw NonFiniteError("Normalized Actor frame contains NaN or Inf.");
    }
    return frame;
  }

  void run_tcn(const SensorFrame& current_sensor) {
    for (std::size_t time = 0; time < kTcnHistoryLength; ++time) {
      const auto& frame = tcn_history_.chronological(time);
      for (std::size_t channel = 0; channel < kSensorDimension; ++channel) {
        tcn_input_[channel * kTcnHistoryLength + time] = frame[channel];
      }
    }
    const char* input_names[] = {config_->tcn_model.input.name.c_str()};
    const char* output_names[] = {config_->tcn_model.output.name.c_str()};
    tcn_session_->Run(Ort::RunOptions{nullptr}, input_names,
                      tcn_input_tensor_.get(), 1, output_names,
                      tcn_output_tensor_.get(), 1);
    if (!all_finite(tcn_output_)) {
      throw NonFiniteError("TCN output contains NaN or Inf.");
    }

    for (std::size_t horizon = 0; horizon < kTcnHorizonCount; ++horizon) {
      for (std::size_t joint = 0; joint < kJointCount; ++joint) {
        const std::size_t output_base = horizon * kTcnTargetDimension;
        const float predicted_q =
            (tcn_output_[output_base + joint] *
                 config_->tcn_target_std[joint] +
             config_->tcn_target_mean[joint]) *
                config_->target_position_scale[joint] +
            config_->target_position_offset[joint];
        const float predicted_dq =
            (tcn_output_[output_base + 4 + joint] *
                 config_->tcn_target_std[4 + joint] +
             config_->tcn_target_mean[4 + joint]) *
            config_->target_velocity_scale[joint];
        if (!std::isfinite(predicted_q) || !std::isfinite(predicted_dq)) {
          throw NonFiniteError(
              "Denormalized TCN prediction contains NaN or Inf.");
        }
        delta16_[horizon * 8 + joint] =
            predicted_q - current_sensor[joint];
        delta16_[horizon * 8 + 4 + joint] =
            predicted_dq - current_sensor[4 + joint];
      }
    }
    if (!all_finite(delta16_)) {
      throw NonFiniteError("Raw TCN delta contains NaN or Inf.");
    }
    for (std::size_t index = 0; index < kTcnFeatureDimension; ++index) {
      const float normalized =
          (delta16_[index] - config_->feature_mean[index]) /
          config_->feature_std[index];
      if (!std::isfinite(normalized)) {
        throw NonFiniteError("Normalized TCN feature contains NaN or Inf.");
      }
      delta16_[index] =
          std::clamp(normalized, -config_->feature_clip[index],
                     config_->feature_clip[index]);
    }
    if (!all_finite(delta16_)) {
      throw NonFiniteError("Normalized TCN feature contains NaN or Inf.");
    }
  }

  void run_actor() {
    if (actor_history_.size() != kActorHistoryLength) {
      throw std::runtime_error("Actor history is incomplete.");
    }
    for (std::size_t time = 0; time < kActorHistoryLength; ++time) {
      const auto& frame = actor_history_.chronological(time);
      std::copy(frame.begin(), frame.end(),
                actor_input_.begin() + time * kActorFrameDimension);
    }
    std::copy(delta16_.begin(), delta16_.end(),
              actor_input_.begin() + kActorHistoryDimension);
    if (!all_finite(actor_input_)) {
      throw NonFiniteError("Actor observation contains NaN or Inf.");
    }
    const char* input_names[] = {config_->actor_model.input.name.c_str()};
    const char* output_names[] = {config_->actor_model.output.name.c_str()};
    actor_session_->Run(Ort::RunOptions{nullptr}, input_names,
                        actor_input_tensor_.get(), 1, output_names,
                        actor_output_tensor_.get(), 1);
    if (!all_finite(actor_output_)) {
      throw NonFiniteError("Actor output contains NaN or Inf.");
    }
  }

  void set_fault(ErrorCode error_code, std::string message) noexcept {
    state_ = State::kFault;
    error_code_ = error_code;
    error_message_ = std::move(message);
    last_action_.fill(0.0F);
  }

  StepResult zero_result() const noexcept {
    return StepResult{state_, Action{}, error_code_};
  }

  void copy_error(std::string* destination) const noexcept {
    if (destination != nullptr) {
      try {
        *destination = error_message_;
      } catch (...) {
      }
    }
  }

  void clear_run_state() noexcept {
    valid_steps_ = 0;
    inference_steps_ = 0;
    tcn_history_.clear();
    actor_history_.clear();
    tcn_input_.fill(0.0F);
    tcn_output_.fill(0.0F);
    delta16_.fill(0.0F);
    actor_input_.fill(0.0F);
    actor_output_.fill(0.0F);
    last_action_.fill(0.0F);
  }

  void release_resources() noexcept {
    initialized_ = false;
    clear_run_state();
    actor_output_tensor_.reset();
    actor_input_tensor_.reset();
    tcn_output_tensor_.reset();
    tcn_input_tensor_.reset();
    memory_info_.reset();
    actor_session_.reset();
    tcn_session_.reset();
    env_.reset();
    config_.reset();
  }

  State state_{State::kFault};
  ErrorCode error_code_{ErrorCode::kNotInitialized};
  std::string error_message_{"Deploy is not initialized."};
  bool initialized_{false};
  bool initialization_attempted_{false};
  bool closed_{false};
  std::size_t valid_steps_{0};
  std::size_t inference_steps_{0};
  std::optional<Config> config_;

  FrameRing<kSensorDimension, kTcnHistoryLength> tcn_history_;
  FrameRing<kActorFrameDimension, kActorHistoryLength> actor_history_;

  std::array<float, kSensorDimension * kTcnHistoryLength> tcn_input_{};
  std::array<float, kTcnOutputDimension> tcn_output_{};
  std::array<float, kTcnFeatureDimension> delta16_{};
  std::array<float, kActorObservationDimension> actor_input_{};
  std::array<float, kActionDimension> actor_output_{};
  Action last_action_{};

  std::unique_ptr<Ort::Env> env_;
  std::unique_ptr<Ort::Session> tcn_session_;
  std::unique_ptr<Ort::Session> actor_session_;
  std::unique_ptr<Ort::MemoryInfo> memory_info_;
  std::unique_ptr<Ort::Value> tcn_input_tensor_;
  std::unique_ptr<Ort::Value> tcn_output_tensor_;
  std::unique_ptr<Ort::Value> actor_input_tensor_;
  std::unique_ptr<Ort::Value> actor_output_tensor_;
};

Runtime::Runtime() : impl_(std::make_unique<Impl>()) {}

Runtime::~Runtime() { impl_->close(); }

bool Runtime::initialize(const std::filesystem::path& model_directory,
                         std::string* error_message) noexcept {
  return impl_->initialize(model_directory, error_message);
}

StepResult Runtime::step(const SensorFrame& sensor,
                         const Action& previous_applied_action) noexcept {
  return impl_->step(sensor, previous_applied_action);
}

bool Runtime::reset() noexcept { return impl_->reset(); }

void Runtime::close() noexcept { impl_->close(); }

State Runtime::get_state() const noexcept { return impl_->state(); }

ErrorCode Runtime::get_error_code() const noexcept {
  return impl_->error_code();
}

std::string Runtime::get_error_message() const {
  return impl_->error_message();
}

std::size_t Runtime::valid_steps() const noexcept {
  return impl_->valid_steps();
}

std::size_t Runtime::inference_steps() const noexcept {
  return impl_->inference_steps();
}

const char* to_string(State state) noexcept {
  switch (state) {
    case State::kWarmup:
      return "WARMUP";
    case State::kReady:
      return "READY";
    case State::kFault:
      return "FAULT";
  }
  return "UNKNOWN";
}

const char* to_string(ErrorCode error_code) noexcept {
  switch (error_code) {
    case ErrorCode::kNone:
      return "NONE";
    case ErrorCode::kNotInitialized:
      return "NOT_INITIALIZED";
    case ErrorCode::kConfiguration:
      return "CONFIGURATION";
    case ErrorCode::kModelIntegrity:
      return "MODEL_INTEGRITY";
    case ErrorCode::kModelInterface:
      return "MODEL_INTERFACE";
    case ErrorCode::kInvalidInput:
      return "INVALID_INPUT";
    case ErrorCode::kInference:
      return "INFERENCE";
    case ErrorCode::kNonFinite:
      return "NON_FINITE";
    case ErrorCode::kHistory:
      return "HISTORY";
  }
  return "UNKNOWN";
}

}  // namespace gexo::deploy
