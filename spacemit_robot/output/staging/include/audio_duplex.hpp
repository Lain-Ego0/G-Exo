/*
 * Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
 * SPDX-License-Identifier: Apache-2.0
 */

/**
 * SpacemitAudio Full-Duplex API
 *
 * High-level interface for full-duplex audio I/O, designed for AEC applications.
 *
 * Usage:
 *   SpacemitAudio::AudioDuplex duplex;
 *   duplex.SetCallback([](const float* input, float* output, size_t frames, int channels) {
 *       // Process synchronized input/output
 *   });
 *   duplex.Start(48000, 1);  // 48kHz mono
 */

#ifndef AUDIO_DUPLEX_HPP
#define AUDIO_DUPLEX_HPP

#include <functional>
#include <memory>
#include <vector>
#include <string>

namespace SpacemitAudio {

// ============================================================================
// AudioDuplex Class
// ============================================================================

/**
 * Full-duplex audio I/O
 *
 * Provides synchronized microphone input and speaker output in a single callback.
 * This is essential for acoustic echo cancellation (AEC) where the output signal
 * serves as the reference for echo removal.
 */
class AudioDuplex {
public:
    /**
     * Full-duplex callback
     *
     * @param input   Microphone input samples (float, [-1.0, 1.0])
     * @param output  Speaker output buffer to fill (float, [-1.0, 1.0])
     * @param frames  Number of frames
     * @param channels Number of channels
     *
     * Note: Both input and output have (frames * channels) samples.
     */
    using Callback = std::function<void(
        const float* input,
        float* output,
        size_t frames,
        int channels)>;

    using CallbackEx = std::function<void(
        const float* input,
        float* output,
        size_t frames,
        int input_channels,
        int output_channels)>;

    /**
     * Constructor
     *
     * @param input_device  Input device index (-1 for default)
     * @param output_device Output device index (-1 for default)
     */
    explicit AudioDuplex(int input_device = -1, int output_device = -1);

    ~AudioDuplex();

    // Non-copyable
    AudioDuplex(const AudioDuplex&) = delete;
    AudioDuplex& operator=(const AudioDuplex&) = delete;

    // -------------------------------------------------------------------------
    // Configuration
    // -------------------------------------------------------------------------

    /**
     * Set the audio callback
     * Must be called before Start()
     */
    void SetCallback(Callback cb);

    /**
     * Set an extended callback for streams with different input/output
     * channel counts.
     */
    void SetCallbackEx(CallbackEx cb);

    // -------------------------------------------------------------------------
    // Lifecycle
    // -------------------------------------------------------------------------

    /**
     * Start full-duplex audio processing
     *
     * @param sample_rate Sample rate (48000 recommended for AEC)
     * @param channels    Number of channels (1=mono, 2=stereo)
     * @param frames_per_buffer Frames per callback (480 = 10ms @ 48kHz)
     * @return true on success
     */
    bool Start(int sample_rate = 48000, int channels = 1, int frames_per_buffer = 480);

    /**
     * Start full-duplex audio processing with independent input/output
     * channel counts.
     */
    bool Start(int sample_rate, int input_channels, int output_channels,
        int frames_per_buffer);

    /**
     * Stop audio processing
     */
    void Stop();

    /**
     * Close and release resources
     */
    void Close();

    // -------------------------------------------------------------------------
    // Status
    // -------------------------------------------------------------------------

    bool IsRunning() const;

    int GetSampleRate() const;
    int GetChannels() const;
    int GetInputChannels() const;
    int GetOutputChannels() const;
    int GetInputDevice() const;
    int GetOutputDevice() const;

    // -------------------------------------------------------------------------
    // Static Utilities
    // -------------------------------------------------------------------------

    /**
     * List available input devices
     * @return Vector of (device_index, device_name) pairs
     */
    static std::vector<std::pair<int, std::string>> ListInputDevices();

    /**
     * List available output devices
     * @return Vector of (device_index, device_name) pairs
     */
    static std::vector<std::pair<int, std::string>> ListOutputDevices();

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace SpacemitAudio

#endif  // AUDIO_DUPLEX_HPP
