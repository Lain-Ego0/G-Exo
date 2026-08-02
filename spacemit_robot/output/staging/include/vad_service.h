/*
 * Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
 * SPDX-License-Identifier: Apache-2.0
 *
 * SpacemiT VAD 引擎 C++ 接口。提供单帧检测与流式检测。
 */

#ifndef VAD_SERVICE_H
#define VAD_SERVICE_H

#include <cstdint>

#include <functional>
#include <memory>
#include <string>
#include <vector>

// Forward declaration of internal types
namespace vad {
    class IVadBackend;
    struct DetectionResult;
    struct ErrorInfo;
}

namespace SpacemiT {

// -----------------------------------------------------------------------------
// VadState
// -----------------------------------------------------------------------------

enum class VadState {
    SILENCE,
    SPEECH_START,
    SPEECH,
    SPEECH_END,
};

// -----------------------------------------------------------------------------
// VadBackendType
// -----------------------------------------------------------------------------

enum class VadBackendType {
    SILERO,
    ENERGY,
    WEBRTC,
    FSMN,
    CUSTOM,
};

// -----------------------------------------------------------------------------
// VadConfig
// -----------------------------------------------------------------------------

// 引擎配置，可用 Preset("silero") 创建。
struct VadConfig {
    VadBackendType backend = VadBackendType::SILERO;
    std::string model_dir;

    int sample_rate = 16000;
    int window_size = 512;

    float trigger_threshold = 0.5f;
    float stop_threshold = 0.35f;
    int min_speech_duration_ms = 250;
    int min_silence_duration_ms = 100;

    int smoothing_window = 10;
    bool use_smoothing = true;
    int num_threads = 1;

    static VadConfig Preset(const std::string& name);
    static std::vector<std::string> AvailablePresets();

    VadConfig withTriggerThreshold(float threshold) const {
        auto c = *this;
        c.trigger_threshold = threshold;
        return c;
    }

    VadConfig withStopThreshold(float threshold) const {
        auto c = *this;
        c.stop_threshold = threshold;
        return c;
    }
    VadConfig withSmoothingWindow(int window) const {
        auto c = *this;
        c.smoothing_window = window;
        return c;
    }
    VadConfig withMinSpeechDuration(int ms) const {
        auto c = *this;
        c.min_speech_duration_ms = ms;
        return c;
    }
    VadConfig withMinSilenceDuration(int ms) const {
        auto c = *this;
        c.min_silence_duration_ms = ms;
        return c;
    }
    VadConfig withWindowSize(int size) const {
        auto c = *this;
        c.window_size = size;
        return c;
    }
    VadConfig withSampleRate(int rate) const {
        auto c = *this;
        c.sample_rate = rate;
        return c;
    }
    VadConfig withSmoothing(bool enable) const {
        auto c = *this;
        c.use_smoothing = enable;
        return c;
    }
    VadConfig withNumThreads(int threads) const {
        auto c = *this;
        c.num_threads = threads;
        return c;
    }
};

// -----------------------------------------------------------------------------
// VadResult
// -----------------------------------------------------------------------------

class VadResult {
public:
    VadResult();
    ~VadResult();

    VadResult(const VadResult&) = delete;
    VadResult& operator=(const VadResult&) = delete;
    VadResult(VadResult&&) noexcept;
    VadResult& operator=(VadResult&&) noexcept;

    float GetProbability() const;
    float GetSmoothedProbability() const;

    bool IsSpeech() const;
    VadState GetState() const;
    bool IsSpeechStart() const;
    bool IsSpeechEnd() const;

    int64_t GetTimestampMs() const;
    int64_t GetSpeechStartMs() const;
    int64_t GetSpeechEndMs() const;
    int GetSpeechDurationMs() const;

    int GetProcessingTimeMs() const;

    bool IsSuccess() const;
    std::string GetCode() const;
    std::string GetMessage() const;

private:
    friend class VadEngine;
    friend class CallbackAdapter;

    struct Impl;
    std::unique_ptr<Impl> impl_;
};

// -----------------------------------------------------------------------------
// VadEngineCallback
// -----------------------------------------------------------------------------

// 流式回调：OnOpen → OnEvent（含 OnSpeechStart/OnSpeechEnd）→ OnComplete → OnClose，出错时 OnError → OnClose。
class VadEngineCallback {
public:
    virtual ~VadEngineCallback() = default;

    virtual void OnOpen() {}
    virtual void OnEvent(std::shared_ptr<VadResult> result) {}
    virtual void OnSpeechStart(int64_t timestamp_ms) {}
    virtual void OnSpeechEnd(int64_t timestamp_ms, int duration_ms) {}
    virtual void OnComplete() {}
    virtual void OnError(const std::string& message) {}
    virtual void OnClose() {}
};

// -----------------------------------------------------------------------------
// VadEngine
// -----------------------------------------------------------------------------

// VAD 引擎，支持单帧检测与流式检测。
class VadEngine {
public:
    explicit VadEngine(VadBackendType backend = VadBackendType::SILERO,
                        const std::string& model_dir = "");
    explicit VadEngine(const VadConfig& config);
    virtual ~VadEngine();

    VadEngine(const VadEngine&) = delete;
    VadEngine& operator=(const VadEngine&) = delete;

    // 检测单帧，失败返回 nullptr。
    std::shared_ptr<VadResult> Detect(const std::vector<float>& audio,
                                        int sample_rate = 16000);
    std::shared_ptr<VadResult> Detect(const float* data, size_t num_samples,
                                        int sample_rate = 16000);

    void SetCallback(std::shared_ptr<VadEngineCallback> callback);
    bool Start();
    void SendAudioFrame(const std::vector<float>& data);
    void SendAudioFrame(const float* data, size_t num_samples);
    void Stop();

    void Reset();
    VadState GetCurrentState() const;
    bool IsInSpeech() const;
    bool IsInitialized() const;
    bool IsStreaming() const;

    void SetTriggerThreshold(float threshold);
    void SetStopThreshold(float threshold);
    VadConfig GetConfig() const;

    std::string GetEngineName() const;
    VadBackendType GetBackendType() const;
    float GetLastProbability() const;

private:
    friend class CallbackAdapter;

    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace SpacemiT

#endif  // VAD_SERVICE_H
