#include "gexo_deploy.hpp"
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

using gexo::deploy::Action;
using gexo::deploy::ErrorCode;
using gexo::deploy::Runtime;
using gexo::deploy::SensorFrame;
using gexo::deploy::State;

void require(bool condition, const std::string& message) {
  if (!condition) {
    throw std::runtime_error(message);
  }
}

class TemporaryDirectory final {
 public:
  TemporaryDirectory() {
    const auto token = std::chrono::steady_clock::now()
                           .time_since_epoch()
                           .count();
    for (int attempt = 0; attempt < 100; ++attempt) {
      path_ = std::filesystem::temp_directory_path() /
              ("gexo-deploy-test-" + std::to_string(token) + "-" +
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

bool is_zero(const Action& action) {
  return std::all_of(action.begin(), action.end(),
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
    require(std::isfinite(result[index]),
            label + " contains NaN or Inf.");
  }
  return result;
}

Json::Value load_json(const std::string& path) {
  std::ifstream stream(path);
  require(static_cast<bool>(stream), "Cannot open replay fixture: " + path);
  Json::CharReaderBuilder builder;
  builder["collectComments"] = false;
  Json::Value root;
  JSONCPP_STRING errors;
  require(Json::parseFromStream(builder, stream, &root, &errors),
          "Cannot parse replay fixture: " + errors);
  return root;
}

void feed_warmup(Runtime& runtime) {
  SensorFrame sensor{};
  const Action ignored_during_warmup{0.8F, -0.7F, 0.6F, -0.5F};
  for (std::size_t step = 1; step <= 150; ++step) {
    sensor[0] = 0.001F * static_cast<float>(step);
    const auto result = runtime.step(sensor, ignored_during_warmup);
    require(is_zero(result.action), "Warmup action must be exactly zero.");
    require(result.state == State::kWarmup,
            "Deploy must remain WARMUP through frame 150.");
  }
  require(runtime.valid_steps() == 150, "Warmup counter must equal 150.");
  require(runtime.inference_steps() == 0,
          "Warmup must not execute ONNX inference.");
}

Action first_ready_action(Runtime& runtime) {
  SensorFrame sensor{};
  sensor[0] = 0.151F;
  const Action previous_applied{0.1F, -0.2F, 0.3F, -0.4F};
  const auto result = runtime.step(sensor, previous_applied);
  require(result.state == State::kReady,
          "Frame 151 must produce the first READY action.");
  require(runtime.inference_steps() == 1,
          "Frame 151 must execute one inference cycle.");
  for (float value : result.action) {
    require(std::isfinite(value), "READY action must be finite.");
    require(value >= -1.0F && value <= 1.0F,
            "READY action must be clipped to [-1, 1].");
  }
  return result.action;
}

void test_lifecycle_and_determinism(const std::string& model_directory) {
  Runtime first;
  std::string error;
  const bool first_initialized = first.initialize(model_directory, &error);
  require(first_initialized, "First initialization failed: " + error);
  require(first.get_state() == State::kWarmup,
          "Successful initialization must enter WARMUP.");
  feed_warmup(first);
  const Action expected = first_ready_action(first);

  require(first.reset(), "READY reset must succeed.");
  require(first.get_state() == State::kWarmup,
          "Reset must return Deploy to WARMUP.");
  require(first.valid_steps() == 0, "Reset must clear the valid-step counter.");
  require(first.inference_steps() == 0,
          "Reset must clear the inference counter.");

  SensorFrame partial_sensor{};
  for (std::size_t step = 0; step < 10; ++step) {
    partial_sensor[0] = 0.002F * static_cast<float>(step);
    const auto result = first.step(partial_sensor, Action{});
    require(result.state == State::kWarmup && is_zero(result.action),
            "A partial second warmup must remain zero-assist.");
  }
  require(first.reset(), "Partial WARMUP reset must succeed.");
  require(first.reset(), "Repeated reset must be idempotent.");
  require(first.valid_steps() == 0,
          "Repeated reset must leave the counter at zero.");
  require(first.inference_steps() == 0,
          "Repeated reset must leave inference count at zero.");

  feed_warmup(first);
  const Action reset_actual = first_ready_action(first);
  for (std::size_t index = 0; index < reset_actual.size(); ++index) {
    require(std::fabs(reset_actual[index] - expected[index]) <= 1.0e-6F,
            "Reset replay must preserve deterministic Session output.");
  }

  first.close();
  require(first.get_state() == State::kFault,
          "A closed Runtime must reject further use.");
  require(first.get_error_code() == ErrorCode::kNotInitialized,
          "A normally closed Runtime must report NOT_INITIALIZED.");
  require(first.valid_steps() == 0, "Close must clear counters.");
  const auto closed_result = first.step(SensorFrame{}, Action{});
  require(closed_result.state == State::kFault &&
              is_zero(closed_result.action),
          "A closed Runtime must return FAULT and zero action.");
  require(!first.reset(), "A closed Runtime must reject reset.");
  first.close();
  require(first.get_error_code() == ErrorCode::kNotInitialized,
          "Close must be idempotent.");
  error.clear();
  require(!first.initialize(model_directory, &error) && !error.empty(),
          "A closed Runtime must reject reinitialization with diagnostics.");

  Runtime second;
  const bool second_initialized = second.initialize(model_directory, &error);
  require(second_initialized, "Second initialization failed: " + error);
  feed_warmup(second);
  const Action actual = first_ready_action(second);
  for (std::size_t index = 0; index < actual.size(); ++index) {
    require(std::fabs(actual[index] - expected[index]) <= 1.0e-6F,
            "A fresh process-equivalent runtime must be deterministic.");
  }
}

void test_fault_latching(const std::string& model_directory) {
  Runtime runtime;
  std::string error;
  const bool initialized = runtime.initialize(model_directory, &error);
  require(initialized, "Fault test initialization failed: " + error);
  SensorFrame invalid{};
  invalid[7] = std::numeric_limits<float>::quiet_NaN();
  auto result = runtime.step(invalid, Action{});
  require(result.state == State::kFault, "NaN input must enter FAULT.");
  require(result.error_code == ErrorCode::kInvalidInput,
          "NaN input must report INVALID_INPUT.");
  require(is_zero(result.action), "FAULT must return zero action.");
  result = runtime.step(SensorFrame{}, Action{});
  require(result.state == State::kFault, "FAULT must remain latched.");
  require(is_zero(result.action), "Latched FAULT must return zero action.");
  const std::string original_error = runtime.get_error_message();
  require(!runtime.reset(), "FAULT must reject reset.");
  require(runtime.get_error_code() == ErrorCode::kInvalidInput &&
              runtime.get_error_message() == original_error,
          "Rejected reset must preserve the latched fault.");
}

void test_finite_overflow_fault(const std::string& model_directory) {
  Runtime runtime;
  std::string error;
  const bool initialized = runtime.initialize(model_directory, &error);
  require(initialized, "Overflow test initialization failed: " + error);
  SensorFrame sensor{};
  sensor[0] = std::numeric_limits<float>::max();
  const auto result = runtime.step(sensor, Action{});
  require(result.state == State::kFault,
          "Finite preprocessing overflow must enter FAULT.");
  require(result.error_code == ErrorCode::kNonFinite,
          "Finite preprocessing overflow must report NON_FINITE.");
  require(is_zero(result.action), "Overflow FAULT must return zero action.");
}

void copy_model_package(const std::filesystem::path& source,
                        const std::filesystem::path& destination) {
  for (const char* filename : {"model_config.json", "tcn.onnx", "actor.onnx"}) {
    std::filesystem::copy_file(source / filename, destination / filename,
                               std::filesystem::copy_options::none);
  }
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
      gexo::deploy::detail::sha256_file(empty_path) ==
          "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "SHA-256 empty-file test vector failed.");
  require(
      gexo::deploy::detail::sha256_file(abc_path) ==
          "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
      "SHA-256 abc test vector failed.");
}

void test_model_hash_rejection(const std::string& model_directory) {
  TemporaryDirectory temporary;
  copy_model_package(model_directory, temporary.path());
  {
    std::ofstream actor(temporary.path() / "actor.onnx",
                        std::ios::binary | std::ios::app);
    require(static_cast<bool>(actor), "Cannot mutate temporary Actor model.");
    actor.put('\0');
  }
  Runtime runtime;
  std::string error;
  require(!runtime.initialize(temporary.path(), &error),
          "A modified model must fail SHA-256 validation.");
  require(runtime.get_state() == State::kFault,
          "Model hash mismatch must enter FAULT.");
  require(runtime.get_error_code() == ErrorCode::kModelIntegrity,
          "Model hash mismatch must report MODEL_INTEGRITY.");
  const std::string original_error = runtime.get_error_message();
  runtime.close();
  runtime.close();
  require(runtime.get_state() == State::kFault &&
              runtime.get_error_code() == ErrorCode::kModelIntegrity &&
              runtime.get_error_message() == original_error,
          "Closing a failed initialization must preserve its root cause.");
  error.clear();
  require(!runtime.initialize(model_directory, &error) &&
              error == original_error &&
              runtime.get_error_code() == ErrorCode::kModelIntegrity,
          "A closed failed Runtime must preserve its original diagnostics.");
}

void test_warmup_contract_rejection(const std::string& model_directory) {
  TemporaryDirectory temporary;
  const auto source =
      std::filesystem::path(model_directory) / "model_config.json";
  const auto destination = temporary.path() / "model_config.json";
  Json::Value config = load_json(source.string());
  config["warmup_steps"] = 50;
  Json::StreamWriterBuilder builder;
  builder["indentation"] = "  ";
  std::ofstream stream(destination);
  require(static_cast<bool>(stream), "Cannot write temporary model config.");
  stream << Json::writeString(builder, config);
  stream.close();

  Runtime runtime;
  std::string error;
  require(!runtime.initialize(temporary.path(), &error),
          "preroll150 protocol must reject warmup_steps=50.");
  require(runtime.get_error_code() == ErrorCode::kConfiguration,
          "Invalid warmup must report CONFIGURATION.");
}

void test_python_reference_replay(const std::string& model_directory,
                                  const std::string& replay_path) {
  const Json::Value fixture = load_json(replay_path);
  require(fixture["schema"].asString() ==
              "gexo_deploy_reference_replay_v1",
          "Replay fixture schema is incompatible.");
  require(fixture["warmup_steps"].asInt() == 150 &&
              fixture["frame_count"].asInt() == 151,
          "Replay fixture must contain 150 warmup frames and one READY frame.");
  require(fixture["warmup_action_history_mode"].asString() ==
              "force_zero_ignore_input",
          "Replay fixture has the wrong warmup action semantics.");
  const Json::Value& frames = fixture["frames"];
  require(frames.isArray() && frames.size() == 151,
          "Replay fixture frame count is invalid.");
  const Action expected_action =
      json_array<4>(fixture["expected_action"], "expected_action");
  const float tolerance = fixture["absolute_tolerance"].asFloat();
  require(std::isfinite(tolerance) && tolerance > 0.0F,
          "Replay tolerance must be positive and finite.");

  Runtime runtime;
  std::string error;
  const bool initialized = runtime.initialize(model_directory, &error);
  require(initialized, "Replay initialization failed: " + error);
  for (std::size_t index = 0; index < frames.size(); ++index) {
    const Json::Value& frame = frames[static_cast<Json::ArrayIndex>(index)];
    const SensorFrame sensor =
        json_array<32>(frame["sensor32"], "sensor32");
    const Action previous = json_array<4>(
        frame["previous_applied_action"], "previous_applied_action");
    const auto result = runtime.step(sensor, previous);
    if (index < 150) {
      require(is_zero(result.action),
              "Reference warmup action must be exactly zero.");
      require(result.state == State::kWarmup,
              "All 150 reference warmup frames must remain WARMUP.");
    } else {
      require(result.state == State::kReady,
              "Reference frame 151 must be READY.");
      for (std::size_t action_index = 0;
           action_index < expected_action.size(); ++action_index) {
        require(std::fabs(result.action[action_index] -
                          expected_action[action_index]) <= tolerance,
                "C++ output differs from the Python reference replay.");
      }
    }
  }
}

void test_initialization_failure() {
  Runtime runtime;
  std::string error;
  require(!runtime.initialize("/definitely/not/a/gexo/model/package", &error),
          "Missing model directory must fail initialization.");
  require(runtime.get_state() == State::kFault,
          "Initialization failure must enter FAULT.");
  require(!error.empty(), "Initialization failure must provide diagnostics.");
  require(!runtime.reset(), "Initialization FAULT must reject reset.");
  require(is_zero(runtime.step(SensorFrame{}, Action{}).action),
          "Uninitialized FAULT must return zero action.");
}

}  // namespace

int main() {
  try {
    const std::string model_directory = GEXO_TEST_MODEL_DIRECTORY;
    test_sha256_vectors();
    test_initialization_failure();
    test_lifecycle_and_determinism(model_directory);
    test_fault_latching(model_directory);
    test_finite_overflow_fault(model_directory);
    test_model_hash_rejection(model_directory);
    test_warmup_contract_rejection(model_directory);
    test_python_reference_replay(model_directory, GEXO_TEST_REPLAY_PATH);
    std::cout << "All Deploy runtime tests passed.\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "Deploy runtime test failed: " << error.what() << '\n';
    return 1;
  }
}
