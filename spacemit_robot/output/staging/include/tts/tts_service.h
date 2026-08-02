/*
 * Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
 * SPDX-License-Identifier: Apache-2.0
 *
 * SpacemiT TTS 引擎 C++ 接口。提供文本合成（阻塞）与流式合成。
 */

#ifndef TTS_SERVICE_H
#define TTS_SERVICE_H

#include <cstdint>

#include <functional>
#include <memory>
#include <string>
#include <vector>

// Forward declaration of internal types
namespace tts {
    class ITtsBackend;
    struct AudioChunk;
    struct ErrorInfo;
}  // namespace tts

namespace SpacemiT {

// -----------------------------------------------------------------------------
// AudioFormat
// -----------------------------------------------------------------------------

enum class AudioFormat {
    PCM,  // 原始 PCM 数据
    WAV,  // WAV 文件格式
    MP3,  // MP3 格式（预留）
    OGG,  // OGG 格式（预留）
};

// -----------------------------------------------------------------------------
// BackendType
// -----------------------------------------------------------------------------

enum class BackendType {
    MATCHA_ZH,      // 中文 22050Hz
    MATCHA_EN,      // 英文 22050Hz
    MATCHA_ZH_EN,   // 中英混合 16000Hz
    COSYVOICE,
    VITS,
    PIPER,
    KOKORO,          // 兼容旧名, 等价于 KOKORO_EN
    KOKORO_EN,       // 英文 kokoro-v1.0-en 24000Hz
    KOKORO_ZH,       // 中文 kokoro-v1.1-zh 24000Hz
    CUSTOM,
};

// -----------------------------------------------------------------------------
// PronunciationEntry
// -----------------------------------------------------------------------------

struct PronunciationEntry {
    std::string word;
    std::string phoneme;
    std::string locale = "zh";
};

// -----------------------------------------------------------------------------
// TtsConfig
// -----------------------------------------------------------------------------

// 引擎配置，可用 Preset("matcha_zh_en") 等创建。
struct TtsConfig {
    BackendType backend = BackendType::MATCHA_ZH_EN;
    std::string model;
    std::string model_dir;
    std::string voice = "default";
    int speaker_id = 0;

    AudioFormat format = AudioFormat::WAV;
    int sample_rate = 16000;
    int volume = 50;

    float speech_rate = 1.0f;
    float pitch = 1.0f;

    float target_rms = 0.15f;
    float compression_ratio = 2.0f;
    bool use_rms_norm = true;
    bool remove_clicks = true;

    int num_threads = 2;
    bool enable_warmup = true;
    std::string provider = "auto";           // auto, cpu, spacemit

    std::vector<PronunciationEntry> lexicon;

    static TtsConfig Preset(const std::string& name);
    static std::vector<std::string> AvailablePresets();

    // 链式配置
    TtsConfig withSpeed(float speed) const {
        auto c = *this;
        c.speech_rate = speed;
        return c;
    }

    TtsConfig withSpeaker(int id) const {
        auto c = *this;
        c.speaker_id = id;
        return c;
    }

    TtsConfig withVolume(int vol) const {
        auto c = *this;
        c.volume = vol;
        return c;
    }

    TtsConfig withProvider(const std::string& value) const {
        auto c = *this;
        c.provider = value;
        return c;
    }
};

// -----------------------------------------------------------------------------
// TtsEngineResult
// -----------------------------------------------------------------------------

// 合成结果。流式下 IsSentenceEnd() 区分中间结果与句末最终结果。
class TtsEngineResult {
public:
    TtsEngineResult();
    ~TtsEngineResult();

    TtsEngineResult(const TtsEngineResult&) = delete;
    TtsEngineResult& operator=(const TtsEngineResult&) = delete;
    TtsEngineResult(TtsEngineResult&&) noexcept;
    TtsEngineResult& operator=(TtsEngineResult&&) noexcept;

    std::vector<uint8_t> GetAudioData() const;
    std::vector<float> GetAudioFloat() const;
    std::vector<int16_t> GetAudioInt16() const;

    std::string GetTimestamp() const;
    std::string GetResponse() const;
    std::string GetRequestId() const;

    bool IsSuccess() const;
    std::string GetCode() const;
    std::string GetMessage() const;
    bool IsEmpty() const;
    bool IsSentenceEnd() const;

    int GetSampleRate() const;
    int GetDurationMs() const;
    int GetProcessingTimeMs() const;
    float GetRTF() const;

    bool SaveToFile(const std::string& file_path) const;

private:
    friend class TtsEngine;
    friend class CallbackAdapter;

    struct Impl;
    std::unique_ptr<Impl> impl_;
};

// -----------------------------------------------------------------------------
// TtsResultCallback
// -----------------------------------------------------------------------------

// 流式回调，顺序 OnOpen → OnEvent → OnComplete → OnClose，出错时 OnError → OnClose。
class TtsResultCallback {
public:
    virtual ~TtsResultCallback() = default;

    virtual void OnOpen() {}
    virtual void OnEvent(std::shared_ptr<TtsEngineResult> result) {}
    virtual void OnComplete() {}
    virtual void OnError(const std::string& message) {}
    virtual void OnClose() {}
};

// -----------------------------------------------------------------------------
// TtsEngine
// -----------------------------------------------------------------------------

// TTS 引擎，支持阻塞合成与流式合成。
class TtsEngine {
public:
    // 双向流，边输入文本边合成。
    class DuplexStream {
    public:
        virtual ~DuplexStream() = default;
        virtual void SendText(const std::string& text) = 0;
        virtual void Complete() = 0;
        virtual bool IsActive() const = 0;
    };

    explicit TtsEngine(
            BackendType backend = BackendType::MATCHA_ZH_EN,
            const std::string& model_dir = "");
    explicit TtsEngine(const TtsConfig& config);
    virtual ~TtsEngine();

    // 显式释放 native backend / ONNX Runtime 资源。析构会自动调用。
    void Shutdown();

    TtsEngine(const TtsEngine&) = delete;
    TtsEngine& operator=(const TtsEngine&) = delete;

    // 合成文本，失败返回 nullptr。
    std::shared_ptr<TtsEngineResult> Call(
        const std::string& text,
        const TtsConfig& config = TtsConfig());
    bool CallToFile(const std::string& text, const std::string& file_path);

    void StreamingCall(
            const std::string& text,
            std::shared_ptr<TtsResultCallback> callback,
            const TtsConfig& config = TtsConfig());
    std::shared_ptr<DuplexStream> StartDuplexStream(
        std::shared_ptr<TtsResultCallback> callback,
        const TtsConfig& config = TtsConfig());

    void SetSpeed(float speed);
    void SetSpeaker(int speaker_id);
    void SetVolume(int volume);
    void UpdateLexicon(const std::vector<PronunciationEntry>& entries);
    TtsConfig GetConfig() const;

    bool IsInitialized() const;
    std::string GetEngineName() const;
    BackendType GetBackendType() const;
    int GetNumSpeakers() const;
    int GetSampleRate() const;
    std::string GetLastRequestId() const;

private:
    friend class CallbackAdapter;

    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace SpacemiT

#endif  // TTS_SERVICE_H
