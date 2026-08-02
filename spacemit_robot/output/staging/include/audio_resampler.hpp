/*
 * Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
 * SPDX-License-Identifier: Apache-2.0
 */
#ifndef AUDIO_RESAMPLER_HPP
#define AUDIO_RESAMPLER_HPP

#ifdef __cplusplus

#include <vector>
#include <cstdint>
#include <memory>

// Forward declaration for libsamplerate (always present for ABI stability)
struct SRC_STATE_tag;
typedef struct SRC_STATE_tag SRC_STATE;

/**
 * Resampling method enumeration
 */
enum class ResampleMethod {
    // Linear interpolation methods (always available, no external library)
    LINEAR_UPSAMPLE,      // Linear interpolation upsampling
    LINEAR_DOWNSAMPLE,    // Linear interpolation downsampling

    // libsamplerate methods (only available if USE_LIBSAMPLERATE is defined)
    SRC_SINC_BEST_QUALITY,   // Band limited sinc interpolation, best quality
    SRC_SINC_MEDIUM_QUALITY,  // Band limited sinc interpolation, medium quality
    SRC_SINC_FASTEST,        // Band limited sinc interpolation, fastest
    SRC_ZERO_ORDER_HOLD,     // Zero order hold interpolator
    SRC_LINEAR               // Linear interpolator (libsamplerate version)
};

/**
 * Check if libsamplerate support is compiled in
 * @return true if libsamplerate is available
 */
inline bool isLibsamplerateAvailable() {
#ifdef USE_LIBSAMPLERATE
    return true;
#else
    return false;
#endif
}

/**
 * Resampler class for audio sample rate conversion
 * Supports linear interpolation (always available) and libsamplerate methods (optional)
 */
class Resampler {
public:
    struct Config {
        int input_sample_rate = 16000;
        int output_sample_rate = 48000;
        int channels = 1;
        // Default to linear interpolation (always available)
        ResampleMethod method = ResampleMethod::LINEAR_UPSAMPLE;
    };

    explicit Resampler(const Config& config);
    ~Resampler();

    // Disable copy
    Resampler(const Resampler&) = delete;
    Resampler& operator=(const Resampler&) = delete;

    // Enable move
    Resampler(Resampler&& other) noexcept;
    Resampler& operator=(Resampler&& other) noexcept;

    /**
     * Initialize the resampler
     * @return true on success, false on failure
     */
    bool initialize();

    /**
     * Reset the resampler state (for streaming use)
     */
    void reset();

    /**
     * Resample audio data (single-shot, non-streaming)
     * @param input Input audio samples (interleaved if multi-channel)
     * @return Resampled audio samples
     */
    std::vector<float> process(const std::vector<float>& input);
    std::vector<float> process(const float* input, size_t num_samples);

    /**
     * Resample audio data (streaming mode)
     * @param input Input audio samples
     * @param end_of_input Set to true when this is the last block
     * @return Resampled audio samples
     */
    std::vector<float> processStreaming(const std::vector<float>& input, bool end_of_input = false);

    /**
     * Get the resampling ratio (output_rate / input_rate)
     */
    double getRatio() const { return ratio_; }

    /**
     * Check if upsampling or downsampling
     */
    bool isUpsampling() const { return ratio_ > 1.0; }
    bool isDownsampling() const { return ratio_ < 1.0; }

    /**
     * Get configuration
     */
    const Config& getConfig() const { return config_; }

    /**
     * Static helper: estimate output size for given input size
     */
    static size_t estimateOutputSize(size_t input_size, int input_rate, int output_rate);

    /**
     * Check if the current method requires libsamplerate
     */
    static bool methodRequiresLibsamplerate(ResampleMethod method);

private:
    Config config_;
    double ratio_;
    bool initialized_;

    // libsamplerate state (always present for ABI stability, nullptr when unused)
    SRC_STATE* src_state_ = nullptr;

    // Internal processing methods
    std::vector<float> linearUpsample(const float* input, size_t num_samples);
    std::vector<float> linearDownsample(const float* input, size_t num_samples);

#ifdef USE_RVV_OPTIMIZATION
    // RVV-optimized versions (RISC-V Vector Extension)
    std::vector<float> linearUpsample_RVV(const float* input, size_t num_samples);
    std::vector<float> linearDownsample_RVV(const float* input, size_t num_samples);
    static bool isRVVAvailable();  // Runtime RVV detection
#endif

#ifdef USE_LIBSAMPLERATE
    std::vector<float> srcResample(const float* input, size_t num_samples, bool end_of_input);
    int methodToSrcType(ResampleMethod method) const;
#endif
};

#endif  // __cplusplus

// ============== C API for use in C files ==============
#ifdef __cplusplus
extern "C" {
#endif

/**
 * C API Resampling method enumeration
 */
typedef enum {
    RESAMPLE_METHOD_LINEAR = 0,           // Linear interpolation (always available)
    RESAMPLE_METHOD_SRC_BEST_QUALITY,     // libsamplerate best quality (requires libsamplerate)
    RESAMPLE_METHOD_SRC_MEDIUM_QUALITY,   // libsamplerate medium quality (requires libsamplerate)
    RESAMPLE_METHOD_SRC_FASTEST,          // libsamplerate fastest (requires libsamplerate)
    RESAMPLE_METHOD_SRC_ZERO_ORDER_HOLD,  // Zero order hold (requires libsamplerate)
    RESAMPLE_METHOD_SRC_LINEAR            // libsamplerate linear (requires libsamplerate)
} ResampleMethodC;

/**
 * Opaque handle for C API resampler
 */
typedef struct ResamplerHandle ResamplerHandle;

/**
 * Check if libsamplerate support is available
 * @return 1 if available, 0 if not
 */
int resampler_has_libsamplerate(void);

/**
 * Create a resampler instance
 * @param input_rate Input sample rate
 * @param output_rate Output sample rate
 * @param channels Number of channels
 * @param method Resampling method (falls back to linear if libsamplerate not available)
 * @return Handle to resampler, or NULL on failure
 */
ResamplerHandle* resampler_create(int input_rate, int output_rate, int channels, ResampleMethodC method);

/**
 * Destroy a resampler instance
 * @param handle Resampler handle
 */
void resampler_destroy(ResamplerHandle* handle);

/**
 * Reset resampler state
 * @param handle Resampler handle
 */
void resampler_reset(ResamplerHandle* handle);

/**
 * Process audio data
 * @param handle Resampler handle
 * @param input Input samples
 * @param input_samples Number of input samples (total, not frames)
 * @param output Output buffer (must be pre-allocated)
 * @param output_capacity Capacity of output buffer
 * @return Number of output samples generated, or -1 on error
 */
int resampler_process(ResamplerHandle* handle,
        const float* input, int input_samples,
        float* output, int output_capacity);

/**
 * Estimate output buffer size needed
 * @param input_samples Number of input samples
 * @param input_rate Input sample rate
 * @param output_rate Output sample rate
 * @return Estimated number of output samples
 */
int resampler_estimate_output_size(int input_samples, int input_rate, int output_rate);

/**
 * Simple one-shot resample function (creates/destroys resampler internally)
 * For frequent use, prefer creating a persistent resampler handle
 * @param input Input samples
 * @param input_samples Number of input samples
 * @param input_rate Input sample rate
 * @param output_rate Output sample rate
 * @param channels Number of channels
 * @param method Resampling method (falls back to linear if libsamplerate not available)
 * @param output Output buffer (must be pre-allocated)
 * @param output_capacity Capacity of output buffer
 * @return Number of output samples generated, or -1 on error
 */
int resample_simple(const float* input, int input_samples,
                    int input_rate, int output_rate,
                    int channels, ResampleMethodC method,
                    float* output, int output_capacity);

#ifdef __cplusplus
}
#endif

#endif  // AUDIO_RESAMPLER_HPP
