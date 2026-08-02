/*
 * Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
 * SPDX-License-Identifier: Apache-2.0
 *
 * SpacemiT 说话人识别 C++ 接口
 */

#ifndef VP_SERVICE_H
#define VP_SERVICE_H

#include <string>
#include <vector>
#include <memory>
#include <cstdint>

namespace SpacemiT {

// =============================================================================
// VpBackendType
// =============================================================================

enum class VpBackendType {
    CAMPPLUS,
    ERES2NET,
    ECAPA_TDNN,
    HTTP,
    CUSTOM,
};

// =============================================================================
// VpConfig
// =============================================================================

struct VpConfig {
    VpBackendType backend = VpBackendType::CAMPPLUS;
    std::string model_dir;
    int num_threads = 1;
    std::string provider = "cpu";
    float threshold = 0.6f;
    int sample_rate = 16000;
    std::string db_path;

    // Presets (implemented in vp_presets.cpp)
    static VpConfig Preset(const std::string& name);
    static std::vector<std::string> AvailablePresets();

    // Builder
    VpConfig withThreshold(float t) const {
        auto c = *this; c.threshold = t; return c;
    }
    VpConfig withNumThreads(int n) const {
        auto c = *this; c.num_threads = n; return c;
    }
    VpConfig withProvider(const std::string& p) const {
        auto c = *this; c.provider = p; return c;
    }
    VpConfig withDbPath(const std::string& path) const {
        auto c = *this; c.db_path = path; return c;
    }
    VpConfig withSampleRate(int rate) const {
        auto c = *this; c.sample_rate = rate; return c;
    }
};

// =============================================================================
// SpeakerMatch
// =============================================================================

struct SpeakerMatch {
    std::string name;
    float score = 0.0f;
};

// =============================================================================
// VpResult
// =============================================================================

class VpResult {
public:
    VpResult();
    ~VpResult();
    VpResult(VpResult&&) noexcept;
    VpResult& operator=(VpResult&&) noexcept;

    VpResult(const VpResult&) = delete;
    VpResult& operator=(const VpResult&) = delete;

    std::string GetName() const;
    float GetScore() const;
    bool IsIdentified() const;
    std::vector<SpeakerMatch> GetMatches() const;
    bool IsVerified() const;
    std::vector<float> GetEmbedding() const;
    float GetRTF() const;
    int GetProcessingTimeMs() const;
    bool IsSuccess() const;
    std::string GetErrorMessage() const;

private:
    friend class VpEngine;
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

// =============================================================================
// VpEngine
// =============================================================================

class VpEngine {
public:
    explicit VpEngine(const VpConfig& config = VpConfig());
    explicit VpEngine(VpBackendType backend,
        const std::string& model_dir = "");
    ~VpEngine();

    VpEngine(const VpEngine&) = delete;
    VpEngine& operator=(const VpEngine&) = delete;

    // Registration
    bool Register(const std::string& name, const std::string& audio_path);
    bool Register(const std::string& name,
        const std::vector<std::string>& audio_paths);
    bool Register(const std::string& name,
        const std::vector<float>& audio,
        int sample_rate = 16000);
    bool RegisterWithEmbedding(const std::string& name,
        const std::vector<float>& embedding);

    // Identification (1:N)
    std::shared_ptr<VpResult> Identify(const std::string& audio_path);
    std::shared_ptr<VpResult> Identify(const std::vector<float>& audio,
        int sample_rate = 16000);

    // Verification (1:1)
    std::shared_ptr<VpResult> Verify(const std::string& name,
        const std::string& audio_path);
    std::shared_ptr<VpResult> Verify(const std::string& name,
        const std::vector<float>& audio,
        int sample_rate = 16000);

    // Embedding extraction
    std::shared_ptr<VpResult> ExtractEmbedding(const std::string& audio_path);
    std::shared_ptr<VpResult> ExtractEmbedding(const std::vector<float>& audio,
        int sample_rate = 16000);

    // Speaker management
    bool RemoveSpeaker(const std::string& name);
    bool ContainsSpeaker(const std::string& name) const;
    int GetSpeakerCount() const;
    std::vector<std::string> GetAllSpeakers() const;

    // Database persistence
    bool SaveDatabase(const std::string& path = "");
    bool LoadDatabase(const std::string& path = "");

    // Dynamic configuration
    void SetThreshold(float threshold);
    float GetThreshold() const;

    // Status
    bool IsInitialized() const;
    int GetEmbeddingDimension() const;
    std::string GetEngineName() const;
    VpBackendType GetBackendType() const;
    VpConfig GetConfig() const;

private:
    void init(const VpConfig& config);
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace SpacemiT

#endif  // VP_SERVICE_H
