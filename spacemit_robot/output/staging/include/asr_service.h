/*
 * Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
 * SPDX-License-Identifier: Apache-2.0
 *
 * SpacemiT ASR 引擎 C++ 接口。提供文件/内存阻塞识别与流式识别。
 */

#ifndef ASR_SERVICE_H
#define ASR_SERVICE_H

#include <string>
#include <vector>
#include <memory>
#include <functional>
#include <cstdint>

namespace asr {
    class ASREngine;
    struct RecognitionResult;
    struct ErrorInfo;
}

namespace SpacemiT {

// -----------------------------------------------------------------------------
// AsrConfig
// -----------------------------------------------------------------------------

// 引擎配置，可用 Preset("sensevoice") 创建。
struct AsrConfig {
    std::string engine = "sensevoice";
    std::string model_dir;
    std::string language = "auto";
    bool punctuation = true;
    bool enable_emotion = false;
    int sample_rate = 16000;
    std::string provider = "spacemit";  // "cpu" or "spacemit"

    // Hotword configuration
    std::vector<std::string> hotwords;
    float hotword_boost = 1.0f;
    std::string hotword_file;

    // Qwen3-ASR llama-server settings (used when engine == "qwen3-asr")
    std::string endpoint = "http://127.0.0.1:8063/v1/chat/completions";
    std::string model = "qwen3-asr";
    int timeout = 60;

    static AsrConfig Preset(const std::string& name);
    static std::vector<std::string> AvailablePresets();
};

// -----------------------------------------------------------------------------
// Sentence
// -----------------------------------------------------------------------------

// 单句结果，时间 ms，置信度 [0,1]。emotion 仅在后端支持时返回。
struct Sentence {
    std::string text;
    int begin_time = 0;
    int end_time = 0;
    float confidence = 0.0f;
    std::string emotion;
};

// -----------------------------------------------------------------------------
// RecognitionResult
// -----------------------------------------------------------------------------

// 识别结果。流式下 IsSentenceEnd() 区分中间结果与句末最终结果。
class RecognitionResult {
public:
    RecognitionResult();
    ~RecognitionResult();

    RecognitionResult(const RecognitionResult&) = delete;
    RecognitionResult& operator=(const RecognitionResult&) = delete;
    RecognitionResult(RecognitionResult&&) noexcept;
    RecognitionResult& operator=(RecognitionResult&&) noexcept;

    Sentence GetSentence() const;
    std::vector<Sentence> GetSentences() const;
    bool IsSentenceEnd() const;
    std::string GetRequestId() const;
    std::string GetText() const;
    std::string GetEmotion() const;
    bool IsEmpty() const;
    int GetAudioDuration() const;
    int GetProcessingTime() const;
    float GetRTF() const;

private:
    friend class AsrEngine;
    friend class CallbackAdapter;
    void setFromInternal(const asr::RecognitionResult& internal);
    void setFinal(bool is_final);

    struct Impl;
    std::unique_ptr<Impl> impl_;
};

// -----------------------------------------------------------------------------
// AsrEngineCallback
// -----------------------------------------------------------------------------

// 流式回调，顺序 OnOpen → OnEvent → OnComplete → OnClose，出错时 OnError → OnClose。
class AsrEngineCallback {
public:
    virtual ~AsrEngineCallback() = default;

    virtual void OnOpen() {}
    virtual void OnEvent(std::shared_ptr<RecognitionResult> result) {}
    virtual void OnComplete() {}
    virtual void OnError(std::shared_ptr<RecognitionResult> result) {}
    virtual void OnClose() {}
};

// -----------------------------------------------------------------------------
// AsrEngine
// -----------------------------------------------------------------------------

// ASR 引擎，支持阻塞识别与流式识别。
class AsrEngine {
public:
    explicit AsrEngine(
        const std::string& engine = "sensevoice",
        const std::string& model_dir = "");
    explicit AsrEngine(const AsrConfig& config);
    virtual ~AsrEngine();

    AsrEngine(const AsrEngine&) = delete;
    AsrEngine& operator=(const AsrEngine&) = delete;

    // 识别文件，失败返回 nullptr。
    std::shared_ptr<RecognitionResult> Call(const std::string& file_path,
                                            const std::string& phrase_id = "");
    // 识别 PCM，默认 16kHz。
    std::shared_ptr<RecognitionResult> Recognize(const std::vector<int16_t>& audio,
                                                int sample_rate = 16000);
    std::shared_ptr<RecognitionResult> Recognize(const std::vector<float>& audio,
                                                int sample_rate = 16000);

    void SetCallback(std::shared_ptr<AsrEngineCallback> callback);
    void Start(const std::string& phrase_id = "");
    // 送入一帧，PCM 16kHz 16bit mono。
    void SendAudioFrame(const std::vector<uint8_t>& data);
    // 立即识别当前缓冲，会话不结束。
    void Flush();
    void Stop();

    void SetLanguage(const std::string& language);
    void SetPunctuation(bool enabled);
    void SetHotwords(const std::vector<std::string>& hotwords, float boost = 1.0f);
    void LoadHotwordFile(const std::string& file_path, float default_boost = 1.0f);
    AsrConfig GetConfig() const;

    std::string GetLastRequestId();
    int GetFirstPackageDelay();
    int GetLastPackageDelay();
    std::string GetResponse();
    bool IsInitialized() const;
    std::string GetEngineName() const;

private:
    friend class CallbackAdapter;
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace SpacemiT

#endif  // ASR_SERVICE_H
