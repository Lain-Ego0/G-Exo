/*
 * Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
 * SPDX-License-Identifier: Apache-2.0
 */
#ifndef AUDIO_BASE_HPP
#define AUDIO_BASE_HPP

#include <cstdint>
#include <cstddef>
#include <functional>
#include <vector>
#include <string>
#include <memory>

namespace SpacemitAudio {

// ============================================================================
// Global Configuration
// ============================================================================

/**
 * Global audio configuration
 */
struct AudioConfig {
    int sample_rate = 16000;      // Sample rate in Hz
    int channels = 1;             // Number of channels
    int chunk_size = 3200;        // Bytes per callback (capture only)
    int capture_device = -1;      // Capture device index (-1 = default)
    int player_device = -1;       // Player device index (-1 = default)
};

/**
 * Initialize global audio configuration
 * @param config Configuration to set
 */
void Init(const AudioConfig& config);

/**
 * Initialize global audio configuration with individual parameters
 * All parameters are optional (-1 means keep current value)
 */
void Init(int sample_rate = -1,
            int channels = -1,
            int chunk_size = -1,
            int capture_device = -1,
            int player_device = -1);

/**
 * Get current global configuration
 * @return Current configuration
 */
AudioConfig GetConfig();

// ============================================================================
// AudioCapture
// ============================================================================

/**
 * Audio capture from microphone
 *
 * Usage:
 *   AudioCapture capture(0);  // device 0, or -1 for default
 *   capture.SetCallback([](const uint8_t* data, size_t size) {
 *       // PCM16 data in bytes
 *   });
 *   capture.Start(16000, 1, 3200);  // 16kHz, mono, 3200 bytes per callback
 *   // ...
 *   capture.Stop();
 *   capture.Close();
 */
class AudioCapture {
public:
    using Callback = std::function<void(const uint8_t* data, size_t size)>;

    explicit AudioCapture(int device_index = -1);
    ~AudioCapture();

    // Disable copy
    AudioCapture(const AudioCapture&) = delete;
    AudioCapture& operator=(const AudioCapture&) = delete;

    /**
     * Set callback for receiving audio data
     * @param cb Callback receives PCM16 little-endian bytes
     */
    void SetCallback(Callback cb);

    /**
     * Start audio capture
     * @param sample_rate Sample rate in Hz (-1 = use global config)
     * @param channels Number of channels (-1 = use global config)
     * @param chunk_size Bytes per callback (-1 = use global config)
     * @return true on success
     */
    bool Start(int sample_rate = -1, int channels = -1, int chunk_size = -1);

    /**
     * Stop audio capture
     */
    void Stop();

    /**
     * Close device and release resources
     */
    void Close();

    /**
     * Check if capturing
     */
    bool IsRunning() const;

    /**
     * List available input devices
     * @return Vector of (index, name) pairs
     */
    static std::vector<std::pair<int, std::string>> ListDevices();

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

/**
 * Audio playback to speaker
 *
 * Usage:
 *   AudioPlayer player(0);  // device 0, or -1 for default
 *   player.Start(16000, 1);
 *   player.Write(pcm_data);  // PCM16 bytes
 *   // or
 *   player.PlayFile("audio.wav");  // blocking
 *   player.Stop();
 *   player.Close();
 */
class AudioPlayer {
public:
    explicit AudioPlayer(int device_index = -1);
    ~AudioPlayer();

    // Disable copy
    AudioPlayer(const AudioPlayer&) = delete;
    AudioPlayer& operator=(const AudioPlayer&) = delete;

    /**
     * Start playback stream
     * @param sample_rate Sample rate in Hz (-1 = use global config)
     * @param channels Number of channels (-1 = use global config)
     * @return true on success
     */
    bool Start(int sample_rate = -1, int channels = -1);

    /**
     * Start playback stream with explicit output buffer size
     * @param sample_rate Sample rate in Hz (-1 = use global config)
     * @param channels Number of channels (-1 = use global config)
     * @param frames_per_buffer Frames per PortAudio write buffer
     * @return true on success
     */
    bool Start(int sample_rate, int channels, int frames_per_buffer);

    /**
     * Write PCM16 data for playback
     * @param data PCM16 little-endian bytes
     * @return true on success
     */
    bool Write(const std::vector<uint8_t>& data);

    /**
     * Write PCM16 data for playback (pointer version)
     * @param data PCM16 little-endian bytes
     * @param size Number of bytes
     * @return true on success
     */
    bool Write(const uint8_t* data, size_t size);

    /**
     * Play a WAV file (blocking until complete)
     * @param file_path Path to WAV file
     * @return true on success
     */
    bool PlayFile(const std::string& file_path);

    /**
     * Stop playback
     */
    void Stop();

    /**
     * Close device and release resources
     */
    void Close();

    /**
     * Check if playing
     */
    bool IsRunning() const;

    /**
     * List available output devices
     * @return Vector of (index, name) pairs
     */
    static std::vector<std::pair<int, std::string>> ListDevices();

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace SpacemitAudio

#endif  // AUDIO_BASE_HPP
