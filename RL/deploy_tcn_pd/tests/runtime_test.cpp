#include "gexo_tcn_pd_deploy.hpp"
#include "sha256.hpp"

#include <json/json.h>

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>

namespace {

using gexo::deploy_tcn_pd::ErrorCode;
using gexo::deploy_tcn_pd::JointVector;
using gexo::deploy_tcn_pd::Runtime;
using gexo::deploy_tcn_pd::SensorFrame;
using gexo::deploy_tcn_pd::State;
using gexo::deploy_tcn_pd::StepResult;

void require(bool condition, const std::string& message) {
  if (!condition) {
    throw std::runtime_error(message);
  }
}

class TemporaryDirectory final {
 public:
  TemporaryDirectory() {
    const auto token =
        std::chrono::steady_clock::now().time_since_epoch().count();
    for (int attempt = 0; attempt < 100; ++attempt) {
      path_ = std::filesystem::temp_directory_path() /
              ("gexo-tcn-pd-deploy-test-" + std::to_string(token) + "-" +
               std::to_string(attempt));
      std::error_code error;
      if (std::filesystem::create_directory(path_, error)) {
        return;
      }
    }
    throw std::runtime_error("Cannot create a temporary test directory.");
  }

  ~TemporaryDirectory() {
    std::error_code error;
    std::filesystem::remove_all(path_, error);
  }

  TemporaryDirectory(const TemporaryDirectory&) = delete;
  TemporaryDirectory& operator=(const TemporaryDirectory&) = delete;

  const std::filesystem::path& path() const noexcept { return path_; }

 private:
  std::filesystem::path path_;
};

bool is_zero(const JointVector& values) {
  return std::all_of(values.begin(), values.end(),
                     [](float value) { return value == 0.0F; });
}

template <std::size_t Size>
std::array<float, Size> json_array(const Json::Value& value,
                                   const std::string& label) {
  require(value.isArray() && value.size() == Size,
          label + " has the wrong shape.");
  std::array<float, Size> result{};
  for (std::size_t index = 0; index < Size; ++index) {
    const Json::Value& element = value[static_cast<Json::ArrayIndex>(index)];
    require(element.isNumeric(), label + " contains a non-number.");
    result[index] = element.asFloat();
    require(std::isfinite(result[index]), label + " contains NaN or Inf.");
  }
  return result;
}

Json::Value load_json(const std::filesystem::path& path) {
  std::ifstream stream(path);
  require(static_cast<bool>(stream), "Cannot open JSON: " + path.string());
  Json::CharReaderBuilder builder;
  builder["collectComments"] = false;
  Json::Value root;
  JSONCPP_STRING errors;
  require(Json::parseFromStream(builder, stream, &root, &errors),
          "Cannot parse JSON: " + errors);
  return root;
}

void write_json(const std::filesystem::path& path, const Json::Value& value) {
  Json::StreamWriterBuilder builder;
  builder["indentation"] = "  ";
  std::ofstream stream(path);
  require(static_cast<bool>(stream), "Cannot write JSON: " + path.string());
  stream << Json::writeString(builder, value) << '\n';
  require(static_cast<bool>(stream), "Cannot finish JSON: " + path.string());
}

void require_close(float actual, float expected, float tolerance,
                   const std::string& label) {
  require(std::isfinite(actual), label + " is not finite.");
  require(std::fabs(actual - expected) <= tolerance,
          label + " differs: actual=" + std::to_string(actual) +
              " expected=" + std::to_string(expected));
}

template <std::size_t Size>
void require_close(const std::array<float, Size>& actual,
                   const std::array<float, Size>& expected, float tolerance,
                   const std::string& label) {
  for (std::size_t index = 0; index < Size; ++index) {
    require_close(actual[index], expected[index], tolerance,
                  label + "[" + std::to_string(index) + "]");
  }
}

void require_result(const StepResult& result, const Json::Value& expected,
                    float tolerance, const std::string& label) {
  require(result.state == State::kReady, label + " must be READY.");
  require(result.error_code == ErrorCode::kNone,
          label + " must not report an error.");
  require_close(result.action,
                json_array<4>(expected["action"], label + ".action"),
                tolerance, label + ".action");
  require_close(
      result.target_torque_nm,
      json_array<4>(expected["target_torque_nm"],
                    label + ".target_torque_nm"),
      tolerance, label + ".target_torque_nm");
  require_close(result.confidence, expected["confidence"].asFloat(), tolerance,
                label + ".confidence");
  require_close(result.feature_ood_ratio,
                expected["feature_ood_ratio"].asFloat(), tolerance,
                label + ".feature_ood_ratio");
  require_close(result.sensor_ood_ratio,
                expected["sensor_ood_ratio"].asFloat(), tolerance,
                label + ".sensor_ood_ratio");
  require(result.feature_saturated == expected["feature_saturated"].asBool(),
          label + ".feature_saturated differs.");
  require(result.sensor_saturated == expected["sensor_saturated"].asBool(),
          label + ".sensor_saturated differs.");
  require(result.error_limited == expected["error_limited"].asBool(),
          label + ".error_limited differs.");
  require(result.action_saturated == expected["action_saturated"].asBool(),
          label + ".action_saturated differs.");
}

void copy_model_package(const std::filesystem::path& source,
                        const std::filesystem::path& destination) {
  for (const char* filename : {"model_config.json", "tcn.onnx"}) {
    std::filesystem::copy_file(source / filename, destination / filename,
                               std::filesystem::copy_options::none);
  }
}

StepResult run_zero_warmup(Runtime& runtime, const SensorFrame& final_sensor) {
  for (std::size_t step = 1; step < 150; ++step) {
    const auto result = runtime.step(SensorFrame{});
    require(result.state == State::kWarmup,
            "Steps 1..149 must remain WARMUP.");
    require(is_zero(result.action) && is_zero(result.target_torque_nm),
            "WARMUP output must be exactly zero.");
  }
  return runtime.step(final_sensor);
}

void test_reference_replay(const std::string& model_directory,
                           const std::string& replay_path) {
  const Json::Value fixture = load_json(replay_path);
  require(fixture["schema"].asString() ==
              "gexo_tcn_pd_reference_replay_v1",
          "Unexpected replay schema.");
  require(fixture["first_action_step"].asUInt64() == 150,
          "TCN+PD first action must occur at step 150.");
  require(fixture["expected_zero_action_through_step"].asUInt64() == 149,
          "Only steps 1..149 may be forced to zero.");
  const Json::Value& frames = fixture["frames"];
  require(frames.isArray() && frames.size() == 151,
          "Replay must contain 151 frames.");
  const float tolerance = fixture["absolute_tolerance"].asFloat();

  Runtime runtime;
  std::string error;
  require(runtime.initialize(model_directory, &error),
          "Reference initialization failed: " + error);
  StepResult step150;
  StepResult step151;
  for (Json::ArrayIndex index = 0; index < frames.size(); ++index) {
    const Json::Value& frame = frames[index];
    const auto sensor = json_array<32>(frame["sensor32"], "sensor32");
    const auto result = runtime.step(sensor);
    const std::size_t step = static_cast<std::size_t>(index) + 1;
    const std::string expected_state = frame["expected_state"].asString();
    require(std::string(gexo::deploy_tcn_pd::to_string(result.state)) ==
                expected_state,
            "Replay state differs at step " + std::to_string(step));
    require_close(result.action,
                  json_array<4>(frame["expected_action"], "expected_action"),
                  tolerance,
                  "replay action step " + std::to_string(step));
    if (step < 150) {
      require(is_zero(result.target_torque_nm),
              "WARMUP target torque must be zero.");
    } else if (step == 150) {
      step150 = result;
    } else if (step == 151) {
      step151 = result;
    }
  }
  require_result(step150, fixture["expected_step150"], tolerance, "step150");
  require_result(step151, fixture["expected_step151"], tolerance, "step151");
  require(runtime.valid_steps() == 151,
          "Replay valid-step counter must equal 151.");

  runtime.request_shutdown("reference complete");
  require(runtime.get_state() == State::kShuttingDown,
          "Shutdown must enter SHUTTING_DOWN.");
  require(runtime.valid_steps() == 0, "Shutdown must clear counters.");
  const auto stopped = runtime.step(SensorFrame{});
  require(stopped.state == State::kShuttingDown && is_zero(stopped.action) &&
              is_zero(stopped.target_torque_nm),
          "SHUTTING_DOWN must return zero output.");
  runtime.request_shutdown("idempotent second request");
  require(runtime.get_state() == State::kShuttingDown,
          "Shutdown must be idempotent.");
}

void test_determinism(const std::string& model_directory,
                      const std::string& replay_path) {
  const Json::Value fixture = load_json(replay_path);
  const Json::Value& frames = fixture["frames"];
  std::array<StepResult, 2> final_results{};
  for (std::size_t run = 0; run < final_results.size(); ++run) {
    Runtime runtime;
    std::string error;
    require(runtime.initialize(model_directory, &error),
            "Determinism initialization failed: " + error);
    for (Json::ArrayIndex index = 0; index < frames.size(); ++index) {
      final_results[run] = runtime.step(
          json_array<32>(frames[index]["sensor32"], "sensor32"));
    }
  }
  require_close(final_results[0].action, final_results[1].action, 0.0F,
                "deterministic action");
  require_close(final_results[0].target_torque_nm,
                final_results[1].target_torque_nm, 0.0F,
                "deterministic torque");
}

void test_fault_latching(const std::string& model_directory) {
  Runtime runtime;
  std::string error;
  require(runtime.initialize(model_directory, &error),
          "Fault-test initialization failed: " + error);
  SensorFrame invalid{};
  invalid[7] = std::numeric_limits<float>::quiet_NaN();
  auto result = runtime.step(invalid);
  require(result.state == State::kFault,
          "NaN sensor input must enter FAULT.");
  require(result.error_code == ErrorCode::kInvalidInput,
          "NaN sensor input must report INVALID_INPUT.");
  require(is_zero(result.action) && is_zero(result.target_torque_nm),
          "FAULT must return zero output.");
  result = runtime.step(SensorFrame{});
  require(result.state == State::kFault && is_zero(result.action),
          "FAULT must remain latched.");
  runtime.request_shutdown("fault cleanup");
  runtime.request_shutdown("fault cleanup again");
  require(runtime.get_state() == State::kShuttingDown,
          "FAULT must use common idempotent cleanup.");
}

void test_finite_overflow_fault(const std::string& model_directory) {
  Runtime runtime;
  std::string error;
  require(runtime.initialize(model_directory, &error),
          "Overflow-test initialization failed: " + error);
  SensorFrame sensor{};
  sensor[0] = -std::numeric_limits<float>::max();
  const auto result = runtime.step(sensor);
  require(result.state == State::kFault,
          "Finite preprocessing overflow must enter FAULT.");
  require(result.error_code == ErrorCode::kNonFinite,
          "Finite preprocessing overflow must report NON_FINITE.");
}

void test_sha256_vectors() {
  TemporaryDirectory temporary;
  const auto empty_path = temporary.path() / "empty";
  const auto abc_path = temporary.path() / "abc";
  std::ofstream(empty_path, std::ios::binary).close();
  {
    std::ofstream stream(abc_path, std::ios::binary);
    stream << "abc";
  }
  require(
      gexo::deploy_tcn_pd::detail::sha256_file(empty_path) ==
          "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "SHA-256 empty-file vector failed.");
  require(
      gexo::deploy_tcn_pd::detail::sha256_file(abc_path) ==
          "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
      "SHA-256 abc vector failed.");
}

void test_model_hash_rejection(const std::string& model_directory) {
  TemporaryDirectory temporary;
  copy_model_package(model_directory, temporary.path());
  {
    std::ofstream model(temporary.path() / "tcn.onnx",
                        std::ios::binary | std::ios::app);
    require(static_cast<bool>(model), "Cannot mutate temporary TCN model.");
    model.put('\0');
  }
  Runtime runtime;
  std::string error;
  require(!runtime.initialize(temporary.path(), &error),
          "Modified TCN model must fail initialization.");
  require(runtime.get_state() == State::kFault &&
              runtime.get_error_code() == ErrorCode::kModelIntegrity,
          "Modified TCN model must report MODEL_INTEGRITY.");
  runtime.request_shutdown("partial initialization cleanup");
  runtime.request_shutdown("partial initialization cleanup again");
}

void test_configuration_rejection(const std::string& model_directory) {
  TemporaryDirectory temporary;
  copy_model_package(model_directory, temporary.path());
  Json::Value config =
      load_json(temporary.path() / "model_config.json");
  config["warmup_steps"] = 50;
  write_json(temporary.path() / "model_config.json", config);
  Runtime runtime;
  std::string error;
  require(!runtime.initialize(temporary.path(), &error),
          "warmup_steps=50 must be rejected.");
  require(runtime.get_error_code() == ErrorCode::kConfiguration,
          "Invalid warmup must report CONFIGURATION.");
}

void test_model_interface_rejection(const std::string& model_directory) {
  TemporaryDirectory temporary;
  copy_model_package(model_directory, temporary.path());
  Json::Value config =
      load_json(temporary.path() / "model_config.json");
  config["models"]["tcn"]["input"]["name"] = "wrong_input";
  write_json(temporary.path() / "model_config.json", config);
  Runtime runtime;
  std::string error;
  require(!runtime.initialize(temporary.path(), &error),
          "Wrong tensor name must be rejected.");
  require(runtime.get_error_code() == ErrorCode::kModelInterface,
          "Wrong tensor name must report MODEL_INTERFACE.");
}

void test_controller_events(const std::string& model_directory) {
  {
    Runtime runtime;
    std::string error;
    require(runtime.initialize(model_directory, &error),
            "Sensor-gate initialization failed: " + error);
    SensorFrame saturated{};
    saturated[0] = 5.0F * 3.1415927410125732F;
    const auto result = run_zero_warmup(runtime, saturated);
    require(result.state == State::kReady && result.sensor_saturated,
            "Sensor clip boundary must be a normal READY event.");
    require(result.confidence == 0.0F && is_zero(result.action) &&
                is_zero(result.target_torque_nm),
            "Sensor saturation must disable assistance.");
  }
  {
    TemporaryDirectory temporary;
    copy_model_package(model_directory, temporary.path());
    Json::Value config =
        load_json(temporary.path() / "model_config.json");
    for (Json::ArrayIndex index = 0; index < 8; ++index) {
      config["tcn_preprocessing"]["feature_clip"][index] = 1.0e-6;
    }
    write_json(temporary.path() / "model_config.json", config);
    Runtime runtime;
    std::string error;
    require(runtime.initialize(temporary.path(), &error),
            "Feature-gate initialization failed: " + error);
    const auto result = run_zero_warmup(runtime, SensorFrame{});
    require(result.state == State::kReady && result.feature_saturated,
            "Selected feature saturation must remain READY.");
    require(result.confidence == 0.0F && is_zero(result.action),
            "Selected feature saturation must disable assistance.");
  }
  {
    TemporaryDirectory temporary;
    copy_model_package(model_directory, temporary.path());
    Json::Value config =
        load_json(temporary.path() / "model_config.json");
    for (Json::ArrayIndex index = 0; index < 4; ++index) {
      config["controller"]["action_scale_nm"][index] = 1.0e-8;
      config["controller"]["position_delta_limit_rad"][index] = 1.0e-6;
      config["controller"]["velocity_delta_limit_rad_s"][index] = 1.0e-6;
    }
    write_json(temporary.path() / "model_config.json", config);
    Runtime runtime;
    std::string error;
    require(runtime.initialize(temporary.path(), &error),
            "Controller-event initialization failed: " + error);
    const auto result = run_zero_warmup(runtime, SensorFrame{});
    require(result.state == State::kReady && result.error_limited &&
                result.action_saturated,
            "Delta and action limits must be reported without FAULT.");
  }
}

void test_warmup_shutdown(const std::string& model_directory) {
  Runtime runtime;
  std::string error;
  require(runtime.initialize(model_directory, &error),
          "Shutdown-test initialization failed: " + error);
  require(runtime.step(SensorFrame{}).state == State::kWarmup,
          "First frame must be WARMUP.");
  runtime.request_shutdown("warmup shutdown");
  require(runtime.get_state() == State::kShuttingDown &&
              runtime.valid_steps() == 0,
          "WARMUP shutdown must clear runtime state.");
}

}  // namespace

int main() {
  try {
    const std::string model_directory = GEXO_TEST_MODEL_DIRECTORY;
    const std::string replay_path = GEXO_TEST_REPLAY_PATH;
    test_sha256_vectors();
    test_reference_replay(model_directory, replay_path);
    test_determinism(model_directory, replay_path);
    test_fault_latching(model_directory);
    test_finite_overflow_fault(model_directory);
    test_model_hash_rejection(model_directory);
    test_configuration_rejection(model_directory);
    test_model_interface_rejection(model_directory);
    test_controller_events(model_directory);
    test_warmup_shutdown(model_directory);
    std::cout << "All TCN+PD Deploy tests passed.\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "TCN+PD Deploy test failed: " << error.what() << '\n';
    return 1;
  }
}
