#include "gexo_tcn_pd_deploy.hpp"
#include "sha256.hpp"

#include <json/json.h>

#include <algorithm>
#include <array>
#include <charconv>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <numeric>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using gexo::deploy_tcn_pd::ErrorCode;
using gexo::deploy_tcn_pd::JointVector;
using gexo::deploy_tcn_pd::Runtime;
using gexo::deploy_tcn_pd::SensorFrame;
using gexo::deploy_tcn_pd::State;
using gexo::deploy_tcn_pd::StepResult;

constexpr std::size_t kDefaultMeasurementSteps = 500;
constexpr std::size_t kMaximumMeasurementSteps = 100'000;
constexpr std::size_t kRepeatedInputPrimingSteps = 50;
constexpr double kControlPeriodMicroseconds = 20'000.0;
constexpr float kMaximumReplayTolerance = 1.0e-5F;

void require(bool condition, const std::string& message) {
  if (!condition) {
    throw std::runtime_error(message);
  }
}

Json::Value load_json(const std::filesystem::path& path) {
  std::ifstream stream(path);
  require(static_cast<bool>(stream), "Cannot open replay: " + path.string());

  Json::CharReaderBuilder builder;
  builder["collectComments"] = false;
  Json::Value root;
  JSONCPP_STRING errors;
  require(Json::parseFromStream(builder, stream, &root, &errors),
          "Cannot parse replay: " + errors);
  require(root.isObject(), "Replay root must be an object.");
  return root;
}

template <std::size_t Size>
std::array<float, Size> json_array(const Json::Value& value,
                                   const std::string& label) {
  require(value.isArray() && value.size() == Size,
          label + " has the wrong shape.");
  std::array<float, Size> result{};
  for (std::size_t index = 0; index < Size; ++index) {
    const auto json_index = static_cast<Json::ArrayIndex>(index);
    require(value[json_index].isNumeric(), label + " contains a non-number.");
    result[index] = value[json_index].asFloat();
    require(std::isfinite(result[index]), label + " contains NaN or Inf.");
  }
  return result;
}

float absolute_error(float actual, float expected, const std::string& label) {
  require(std::isfinite(actual), label + " is NaN or Inf.");
  return std::fabs(actual - expected);
}

template <std::size_t Size>
float maximum_absolute_error(const std::array<float, Size>& actual,
                             const std::array<float, Size>& expected,
                             const std::string& label) {
  float maximum = 0.0F;
  for (std::size_t index = 0; index < Size; ++index) {
    maximum = std::max(maximum,
                       absolute_error(actual[index], expected[index],
                                      label + "[" + std::to_string(index) + "]"));
  }
  return maximum;
}

bool is_zero(const JointVector& values) {
  return std::all_of(values.begin(), values.end(),
                     [](float value) { return value == 0.0F; });
}

void require_finite(const StepResult& result, const std::string& label) {
  for (std::size_t index = 0; index < result.action.size(); ++index) {
    require(std::isfinite(result.action[index]),
            label + ".action[" + std::to_string(index) + "] is not finite.");
    require(std::isfinite(result.target_torque_nm[index]),
            label + ".target_torque_nm[" + std::to_string(index) +
                "] is not finite.");
  }
  require(std::isfinite(result.confidence), label + ".confidence is not finite.");
  require(std::isfinite(result.feature_ood_ratio),
          label + ".feature_ood_ratio is not finite.");
  require(std::isfinite(result.sensor_ood_ratio),
          label + ".sensor_ood_ratio is not finite.");
}

float require_close(float actual, const Json::Value& expected, float tolerance,
                    const std::string& label) {
  require(expected.isNumeric(), label + " reference is not numeric.");
  const float error = absolute_error(actual, expected.asFloat(), label);
  require(error <= tolerance,
          label + " differs by " + std::to_string(error) +
              " (tolerance " + std::to_string(tolerance) + ").");
  return error;
}

void require_flag(bool actual, const Json::Value& expected,
                  const std::string& label) {
  require(expected.isBool(), label + " reference is not boolean.");
  require(actual == expected.asBool(), label + " differs.");
}

struct ErrorSummary {
  float action{0.0F};
  float torque{0.0F};
  float diagnostic{0.0F};
};

void require_ready_result(const StepResult& result, const Json::Value& expected,
                          float tolerance, const std::string& label,
                          ErrorSummary* errors) {
  require(result.state == State::kReady, label + " must be READY.");
  require(result.error_code == ErrorCode::kNone,
          label + " returned error " +
              std::string(gexo::deploy_tcn_pd::to_string(result.error_code)) +
              ".");
  require_finite(result, label);

  const float action_error = maximum_absolute_error(
      result.action, json_array<4>(expected["action"], label + ".action"),
      label + ".action");
  const float torque_error = maximum_absolute_error(
      result.target_torque_nm,
      json_array<4>(expected["target_torque_nm"],
                    label + ".target_torque_nm"),
      label + ".target_torque_nm");
  require(action_error <= tolerance,
          label + ".action exceeds the replay tolerance.");
  require(torque_error <= tolerance,
          label + ".target_torque_nm exceeds the replay tolerance.");
  errors->action = std::max(errors->action, action_error);
  errors->torque = std::max(errors->torque, torque_error);

  errors->diagnostic = std::max(
      errors->diagnostic,
      require_close(result.confidence, expected["confidence"], tolerance,
                    label + ".confidence"));
  errors->diagnostic = std::max(
      errors->diagnostic,
      require_close(result.feature_ood_ratio, expected["feature_ood_ratio"],
                    tolerance, label + ".feature_ood_ratio"));
  errors->diagnostic = std::max(
      errors->diagnostic,
      require_close(result.sensor_ood_ratio, expected["sensor_ood_ratio"],
                    tolerance, label + ".sensor_ood_ratio"));
  require_flag(result.feature_saturated, expected["feature_saturated"],
               label + ".feature_saturated");
  require_flag(result.sensor_saturated, expected["sensor_saturated"],
               label + ".sensor_saturated");
  require_flag(result.error_limited, expected["error_limited"],
               label + ".error_limited");
  require_flag(result.action_saturated, expected["action_saturated"],
               label + ".action_saturated");
}

std::size_t parse_measurement_steps(const char* text) {
  const std::string value(text);
  require(!value.empty() &&
              std::all_of(value.begin(), value.end(), [](char character) {
                return character >= '0' && character <= '9';
              }),
          "MEASUREMENT_STEPS must contain decimal digits only.");
  unsigned long long parsed = 0;
  const auto conversion =
      std::from_chars(value.data(), value.data() + value.size(), parsed, 10);
  require(conversion.ec == std::errc{} && conversion.ptr == value.data() + value.size() &&
              parsed > 0 && parsed <= kMaximumMeasurementSteps,
          "MEASUREMENT_STEPS must be between 1 and " +
              std::to_string(kMaximumMeasurementSteps) + ".");
  return static_cast<std::size_t>(parsed);
}

double percentile(const std::vector<double>& sorted, double fraction) {
  require(!sorted.empty(), "Cannot calculate an empty latency percentile.");
  const double scaled = fraction * static_cast<double>(sorted.size() - 1U);
  const auto lower = static_cast<std::size_t>(std::floor(scaled));
  const auto upper = static_cast<std::size_t>(std::ceil(scaled));
  const double weight = scaled - static_cast<double>(lower);
  return sorted[lower] * (1.0 - weight) + sorted[upper] * weight;
}

void verify_model_package(const std::filesystem::path& model_directory,
                          const Json::Value& fixture) {
  const Json::Value& package = fixture["model_package"];
  require(package.isObject(), "Replay does not describe its model package.");
  require(package["schema"].asString() == "gexo_tcn_pd_deploy_model_v1",
          "Replay model-package schema is unsupported.");

  const std::string expected_model_hash = package["tcn_onnx_sha256"].asString();
  const std::string expected_config_hash =
      package["model_config_sha256"].asString();
  require(expected_model_hash.size() == 64 && expected_config_hash.size() == 64,
          "Replay model-package hashes are malformed.");
  require(gexo::deploy_tcn_pd::detail::sha256_file(model_directory / "tcn.onnx") ==
              expected_model_hash,
          "tcn.onnx does not match the reference replay.");
  require(gexo::deploy_tcn_pd::detail::sha256_file(model_directory /
                                                   "model_config.json") ==
              expected_config_hash,
          "model_config.json does not match the reference replay.");
}

struct SmokeArguments {
  std::filesystem::path model_directory;
  std::filesystem::path replay_path;
  std::size_t measurement_steps{kDefaultMeasurementSteps};
};

SmokeArguments parse_arguments(int argc, char** argv) {
  require(argc >= 1 && argc <= 4,
          std::string("Usage: ") + argv[0] +
              " [MODEL_DIRECTORY [REFERENCE_REPLAY [MEASUREMENT_STEPS]]]");
  SmokeArguments arguments{GEXO_SMOKE_MODEL_DIRECTORY, GEXO_SMOKE_REPLAY_PATH,
                           kDefaultMeasurementSteps};
  if (argc >= 2) {
    arguments.model_directory = argv[1];
  }
  if (argc >= 3) {
    arguments.replay_path = argv[2];
  }
  if (argc == 4) {
    arguments.measurement_steps = parse_measurement_steps(argv[3]);
  }
  return arguments;
}

int run_smoke(const SmokeArguments& arguments) {
  const Json::Value fixture = load_json(arguments.replay_path);
  require(fixture["schema"].asString() ==
              "gexo_tcn_pd_reference_replay_v1",
          "Replay schema is unsupported.");
  require(fixture["schema_version"].asUInt() == 1,
          "Replay schema version is unsupported.");
  require(fixture["first_action_step"].asUInt64() == 150,
          "Replay first action must be step 150.");
  require(fixture["expected_zero_action_through_step"].asUInt64() == 149,
          "Replay warmup output must end at step 149.");

  const Json::Value& frames = fixture["frames"];
  require(frames.isArray() && frames.size() == 151,
          "Replay must contain exactly 151 frames.");
  require(fixture["frame_count"].asUInt64() == frames.size(),
          "Replay frame_count does not match frames.");
  require(fixture["absolute_tolerance"].isNumeric(),
          "Replay tolerance is missing.");
  const float tolerance = fixture["absolute_tolerance"].asFloat();
  require(std::isfinite(tolerance) && tolerance > 0.0F &&
              tolerance <= kMaximumReplayTolerance,
          "Replay tolerance must be in (0, 1e-5].");
  verify_model_package(arguments.model_directory, fixture);

  Runtime runtime;
  std::string initialization_error;
  const auto initialization_start = std::chrono::steady_clock::now();
  const bool initialized =
      runtime.initialize(arguments.model_directory, &initialization_error);
  require(initialized,
          "Runtime initialization failed: " + initialization_error);
  const auto initialization_end = std::chrono::steady_clock::now();

  ErrorSummary errors;
  SensorFrame last_sensor{};
  std::vector<double> replay_latencies;
  replay_latencies.reserve(static_cast<std::size_t>(frames.size()));
  for (Json::ArrayIndex index = 0; index < frames.size(); ++index) {
    const std::size_t step = static_cast<std::size_t>(index) + 1U;
    const std::string label = "step " + std::to_string(step);
    const Json::Value& frame = frames[index];
    last_sensor = json_array<gexo::deploy_tcn_pd::kSensorDimension>(
        frame["sensor32"], label + ".sensor32");

    const auto start = std::chrono::steady_clock::now();
    const StepResult result = runtime.step(last_sensor);
    const auto end = std::chrono::steady_clock::now();
    replay_latencies.push_back(
        std::chrono::duration<double, std::micro>(end - start).count());

    require_finite(result, label);
    const std::string expected_state = frame["expected_state"].asString();
    require(expected_state == gexo::deploy_tcn_pd::to_string(result.state),
            label + " state differs: got " +
                gexo::deploy_tcn_pd::to_string(result.state) + ", expected " +
                expected_state + ".");
    const float action_error = maximum_absolute_error(
        result.action,
        json_array<4>(frame["expected_action"], label + ".expected_action"),
        label + ".action");
    require(action_error <= tolerance,
            label + " action exceeds the replay tolerance.");
    errors.action = std::max(errors.action, action_error);

    if (step <= 149U) {
      require(result.state == State::kWarmup &&
                  result.error_code == ErrorCode::kNone,
              label + " violates the WARMUP contract.");
      require(is_zero(result.action) && is_zero(result.target_torque_nm),
              label + " WARMUP output is not exactly zero.");
    } else if (step == 150U) {
      require_ready_result(result, fixture["expected_step150"], tolerance,
                           label, &errors);
    } else {
      require_ready_result(result, fixture["expected_step151"], tolerance,
                           label, &errors);
    }
  }
  require(runtime.valid_steps() == static_cast<std::size_t>(frames.size()),
          "Runtime frame counter differs after replay.");

  StepResult repeated_input_reference;
  for (std::size_t step = 0; step < kRepeatedInputPrimingSteps; ++step) {
    repeated_input_reference = runtime.step(last_sensor);
    require(repeated_input_reference.state == State::kReady &&
                repeated_input_reference.error_code == ErrorCode::kNone,
            "Repeated-input priming did not remain READY.");
    require_finite(repeated_input_reference, "repeated-input priming");
  }

  std::vector<double> measurement_latencies;
  measurement_latencies.reserve(arguments.measurement_steps);
  std::size_t calls_over_control_period = 0;
  for (std::size_t step = 0; step < arguments.measurement_steps; ++step) {
    const auto start = std::chrono::steady_clock::now();
    const StepResult result = runtime.step(last_sensor);
    const auto end = std::chrono::steady_clock::now();
    const double latency =
        std::chrono::duration<double, std::micro>(end - start).count();
    measurement_latencies.push_back(latency);
    if (latency > kControlPeriodMicroseconds) {
      ++calls_over_control_period;
    }
    require(result.state == State::kReady &&
                result.error_code == ErrorCode::kNone,
            "Measurement step " + std::to_string(step + 1U) +
                " did not remain READY.");
    const std::string label = "measurement step " + std::to_string(step + 1U);
    require_finite(result, label);
    require(maximum_absolute_error(result.action,
                                   repeated_input_reference.action,
                                   label + ".action") <= tolerance,
            label + " action is not stable for identical input history.");
    require(maximum_absolute_error(result.target_torque_nm,
                                   repeated_input_reference.target_torque_nm,
                                   label + ".target_torque_nm") <= tolerance,
            label + " torque is not stable for identical input history.");
    require(absolute_error(result.confidence,
                           repeated_input_reference.confidence,
                           label + ".confidence") <= tolerance,
            label + " confidence is not stable for identical input history.");
    require(std::all_of(result.action.begin(), result.action.end(),
                        [tolerance](float action) {
                          return action >= -1.0F - tolerance &&
                                 action <= 1.0F + tolerance;
                        }),
            label + " action is outside [-1, 1].");
  }

  runtime.request_shutdown("Local smoke test complete.");
  require(runtime.valid_steps() == 0,
          "Runtime cleanup did not clear the frame counter.");
  const StepResult stopped = runtime.step(last_sensor);
  require(stopped.state != State::kWarmup && stopped.state != State::kReady &&
              is_zero(stopped.action) && is_zero(stopped.target_torque_nm),
          "Runtime cleanup did not leave zero control output.");
  runtime.request_shutdown("Repeated local smoke cleanup.");
  require(runtime.valid_steps() == 0,
          "Repeated runtime cleanup was not idempotent.");

  std::sort(measurement_latencies.begin(), measurement_latencies.end());
  const double sum = std::accumulate(measurement_latencies.begin(),
                                     measurement_latencies.end(), 0.0);
  const double initialization_ms =
      std::chrono::duration<double, std::milli>(initialization_end -
                                               initialization_start)
          .count();
  const double first_ready_us = replay_latencies[149];

  std::cout << std::fixed << std::setprecision(3)
            << "TCN+PD local smoke: PASS\n"
            << "  model: " << (arguments.model_directory / "tcn.onnx") << '\n'
            << "  replay: " << arguments.replay_path << '\n'
            << "  frames: 151 (WARMUP 1..149, first READY/action 150)\n"
            << std::scientific << "  max_abs_error: action=" << errors.action
            << " torque_nm=" << errors.torque
            << " diagnostic=" << errors.diagnostic << '\n' << std::fixed
            << "  initialization_ms: " << initialization_ms << '\n'
            << "  first_ready_step_us: " << first_ready_us << '\n'
            << "  repeated_input_step_us: mean="
            << sum / static_cast<double>(measurement_latencies.size())
            << " p50=" << percentile(measurement_latencies, 0.50)
            << " p95=" << percentile(measurement_latencies, 0.95)
            << " p99=" << percentile(measurement_latencies, 0.99)
            << " max=" << measurement_latencies.back() << '\n'
            << "  step_calls_over_20ms: " << calls_over_control_period << '/'
            << arguments.measurement_steps << '\n';
  return 0;
}

}  // namespace

int main(int argc, char** argv) {
  try {
    return run_smoke(parse_arguments(argc, argv));
  } catch (const std::exception& error) {
    std::cerr << "TCN+PD local smoke: FAIL: " << error.what() << '\n';
    return 1;
  }
}
