/*
 * Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
 * SPDX-License-Identifier: Apache-2.0
 *
 * Sound Source Localization (SSL) API.
 *
 * This is the single public header for the doa component.
 *   - SoundLocator      : 2-channel GCC-PHAT (DOA in [0, 180])
 *   - MultiSoundLocator : 3+ channel planar MPCC-LSQ (azimuth in [0, 360))
 *
 * 2-channel and multi-channel classes are independent; the 2-channel
 * SoundLocator is preserved bit-stable across releases.
 *
 * ===========================================================================
 * Coordinate / convention spec (read this once before integrating)
 * ===========================================================================
 *
 * 1. ANGLE FRAME (MultiSoundLocator)
 *    - azimuth_deg ∈ [0°, 360°)
 *    - 0°    = +x axis of the array coordinate frame
 *    - 90°   = +y axis (counter-clockwise from +x; mathematical convention)
 *    - Rotation: CCW positive
 *    - To map array frame → robot frame, set
 *      `MultiSoundLocatorConfig.azimuth_offset_deg` so that the robot's
 *      forward direction reads as 0° in the output. Example: if mic0 is on
 *      the robot's left side (array +x = robot +y), set
 *      `azimuth_offset_deg = -90.0f`.
 *
 *    SoundLocator (2-channel) is a separate convention:
 *    - DOA ∈ [0°, 180°]
 *    - 90°   = broadside (perpendicular to the mic line)
 *    - 0°    = endfire toward ch1
 *    - 180°  = endfire toward ch0
 *    - There is no front/back disambiguation; use the 3-channel class for
 *      full 360° awareness.
 *
 * 2. MICROPHONE INDEX → POSITION MAPPING
 *    - For MultiSoundLocator, `microphones[i]` is the (x, y, z) position of
 *      the mic that produces channel i in the interleaved/separated input
 *      streams of Process(). i.e. channel index == mic index, no permutation.
 *    - `CreateEquilateralTriangleConfig(side)` lays out:
 *        mic0 = ( +side/√3, 0)        (along +x axis, "front" by default)
 *        mic1 = ( -side/(2√3), +side/2)
 *        mic2 = ( -side/(2√3), -side/2)
 *      centroid at origin.
 *    - If your hardware delivers channels in a different physical order,
 *      override `config.microphones` to match — do NOT renumber channels
 *      in your capture code.
 *
 * 3. TDOA SIGN CONVENTION
 *    - For any pair (i, j) with i < j (lexicographic), `GetTDOA(i, j)`
 *      returns τ_ij = arrival_i − arrival_j (seconds).
 *    - GetTDOA(j, i) returns the negation, i.e. -τ_ij.
 *    - Pair indices used internally for N=3 are stored lexicographically:
 *        pair 0 = (0,1) → τ_01
 *        pair 1 = (0,2) → τ_02
 *        pair 2 = (1,2) → τ_12
 *
 * 4. CLOSURE INVARIANT (N=3 only)
 *    - For a self-consistent 3-mic batch:
 *        τ_01 + τ_12 + τ_20 = 0     ⇔     τ_01 + τ_12 − τ_02 = 0
 *      (τ_20 = −τ_02 by definition)
 *    - `result.closure_residual_sec` reports |τ_01 + τ_12 − τ_02| in seconds.
 *    - `config.closure_threshold_samples` gates `result.valid` on this
 *      residual (only when N=3; ignored otherwise).
 *
 * 5. CONFIDENCE SEMANTICS  (changed in v1.1; see README A4 migration)
 *    - `result.confidence` (post-v1.1) = geometric mean of pair GCC peaks
 *      × `result.quality` (clamped consistency in [0, 1]).
 *    - `result.peak_score` retains the pre-v1.1 arithmetic-mean value;
 *      read this if you tuned thresholds against the old semantics.
 *
 * 6. LIFECYCLE
 *    - Construct → call `Initialize()` ONCE (returns bool) → call
 *      `Process(...)` repeatedly → read `GetResult()` after each batch.
 *    - Calling Process() before Initialize() returns false silently
 *      (does not throw).
 *    - Calling Process() with the wrong channel count throws
 *      std::invalid_argument (matches the cpp idiom; Python receives a
 *      RuntimeError via pybind11).
 *    - `Reset()` clears multi-frame accumulators and result; keeps FFT plans.
 *
 * 7. STREAMING / LONG-RUNNING USE
 *    - `max_avg_seconds = 0` (default) keeps the GetAverageAzimuth window
 *      UNBOUNDED since the last Reset() — fine for one-shot batches, but
 *      causes unbounded memory growth in live capture / long sessions.
 *    - Live mic / streaming integrations MUST set `max_avg_seconds` to the
 *      time window they actually want (e.g. 5–30 s), or call Reset()
 *      periodically.
 * ===========================================================================
 */

#ifndef DOA_SERVICE_H
#define DOA_SERVICE_H

#include <cstddef>
#include <cstdint>
#include <memory>
#include <vector>

namespace SpacemitAudio {

// ===========================================================================
// 2-channel SoundLocator
// ===========================================================================

/// Configuration for SoundLocator.
/// All fields have sensible defaults; users MUST set `mic_distance`
/// to match their hardware.
struct SoundLocatorConfig {
    int sample_rate = 16000;            ///< Sampling rate (Hz)
    float mic_distance = 0.058f;        ///< Microphone spacing (meters)
    float sound_speed = 343.0f;         ///< Speed of sound (m/s)
    int fft_size = 0;                   ///< FFT length; 0 = auto (2 * frame_size)
    int frame_size = 512;               ///< Samples per frame (512 @ 16 kHz ≈ 32 ms)
    int avg_frames = 4;                 ///< Number of frames to average before output
    float confidence_threshold = 0.1f;  ///< Minimum confidence to consider result valid
    int upsample_factor = 0;            ///< GCC upsample factor; 0 = auto (~4μs resolution)
    bool use_fftw_measure = false;      ///< Use FFTW_MEASURE for faster FFTs (slower init)
};

/// Dual-channel sound source locator using GCC-PHAT.
///
/// Usage:
/// @code
///   SoundLocatorConfig cfg;
///   cfg.mic_distance = 0.10f;          // set to your mic spacing
///   SoundLocator loc(cfg);
///   loc.Initialize();
///
///   // feed stereo PCM16 frames (from AudioCapture callback)
///   loc.Process(pcm16_interleaved, num_frames);
///
///   if (loc.IsValid()) {
///       float angle = loc.GetDOA();    // degrees, [0, 180]
///   }
/// @endcode
class SoundLocator {
public:
    explicit SoundLocator(const SoundLocatorConfig& config = {});
    ~SoundLocator();

    SoundLocator(const SoundLocator&) = delete;
    SoundLocator& operator=(const SoundLocator&) = delete;
    SoundLocator(SoundLocator&& other) noexcept;
    SoundLocator& operator=(SoundLocator&& other) noexcept;

    /// Allocate FFT plans and internal buffers.  Must be called once
    /// before the first Process().
    /// @return true on success.
    bool Initialize();

    /// Clear the multi-frame accumulator and cached results.
    void Reset();

    // ----- Process methods ------------------------------------------------

    /// Process interleaved stereo float data [L, R, L, R, ...].
    /// @param interleaved  pointer to interleaved samples
    /// @param num_frames   number of sample frames (each frame = 2 floats)
    /// @return true if a DOA result is ready (enough frames accumulated).
    bool Process(const float* interleaved, size_t num_frames);

    /// Process two separate float channels.
    bool Process(const float* ch0, const float* ch1, size_t num_frames);

    /// Process interleaved stereo PCM16 data (compatible with AudioCapture).
    bool Process(const int16_t* interleaved, size_t num_frames);

    // ----- Result accessors -----------------------------------------------

    /// Estimated time-difference-of-arrival (seconds).
    float GetTDOA() const;

    /// Estimated direction-of-arrival (degrees), range [0, 180].
    /// 90° = broadside (perpendicular), 0° = endfire (ch1 side), 180° = endfire (ch0 side).
    float GetDOA() const;

    /// Peak value of the normalised GCC function, range [0, 1].
    /// 2-channel SoundLocator is full-band (active_bins = padded/2+1) so the
    /// raw peak is already ≈ 1.0 for a clean source — bit-stable, unchanged
    /// across releases. Multi-channel MultiSoundLocator may band-limit
    /// internally; its per-pair peak is active-bin normalized (P1.1) so the
    /// same `confidence_threshold = 0.1` carries the same significance
    /// across mic geometries.
    float GetConfidence() const;

    /// True when GetConfidence() >= confidence_threshold.
    bool IsValid() const;

    /// Dominant confidence-weighted DOA across all processed batches since
    /// last Reset(). Aggregation is done in TDOA space so near-endfire
    /// results are not pulled toward 90° by a few opposite-sign outliers.
    /// Returns 90.0f (broadside) if no valid results yet.
    float GetAverageDOA() const;

    /// Number of valid result batches accumulated since last Reset().
    int GetResultCount() const;

    // ----- Configuration query --------------------------------------------

    const SoundLocatorConfig& GetConfig() const;

    /// Maximum delay in samples that is physically possible given
    /// mic_distance and sound_speed.
    int GetMaxDelaySamples() const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

// ===========================================================================
// 3+ channel MultiSoundLocator (planar MPCC-LSQ)
// ===========================================================================

/// Microphone position in meters, centered in the array coordinate frame.
/// v1 uses x/y only for planar azimuth; z is reserved for future elevation.
struct MicrophonePosition {
    float x = 0.0f;
    float y = 0.0f;
    float z = 0.0f;
};

/// Configuration for MultiSoundLocator.
struct MultiSoundLocatorConfig {
    /// Sampling rate (Hz).
    int sample_rate = 16000;

    /// Samples per frame.
    int frame_size = 512;

    /// Frames averaged before one result. One batch is roughly
    /// frame_size * avg_frames / sample_rate seconds (128 ms at defaults).
    int avg_frames = 4;

    /// GetAverageAzimuth sliding-window length (seconds).
    /// 0  = unbounded since the last Reset() (default, backward compat).
    ///      WARNING: live / streaming integrations MUST set this > 0 or call
    ///      Reset() periodically, otherwise history memory grows for the full
    ///      session.
    /// >0 = keep only the most recent ceil(max_avg_seconds / batch_seconds)
    ///      batches in the running mean (useful for streaming / moving sources
    ///      to bound memory).
    float max_avg_seconds = 0.0f;

    /// FFT length; 0 = auto (2 * frame_size).
    int fft_size = 0;

    /// GCC upsample factor; 0 = auto (~4 us resolution).
    int upsample_factor = 0;

    /// Minimum (geo-mean x quality) confidence for valid result.
    float confidence_threshold = 0.1f;

    /// Minimum ||k_hat_unnorm|| (geometry consistency).
    /// Silence / multi-source frames typically have margin < 0.5.
    float margin_threshold = 0.6f;

    /// Minimum per-frame RMS before GCC-PHAT processing. 0 disables this gate.
    /// This is an activity gate, not a DOA confidence gate: GCC-PHAT
    /// normalizes spectra, so very quiet noise can otherwise produce a stable
    /// looking correlation peak and a misleading azimuth.
    float min_signal_rms = 0.0f;

    /// [A5] Minimum `quality` (clamped 1 - |1 - ||n_hat|||) for valid result.
    /// 0 disables this gate; 0.5 is the AI-variant default if you opt in.
    float quality_threshold = 0.0f;

    /// [A2/P1.1] Closure-residual gate (N = 3 only). Effective threshold
    /// in samples = max(closure_threshold_samples,
    ///                   closure_threshold_fraction * max_physical_TDOA_samples),
    /// where max_physical_TDOA_samples = max_pair_distance / sound_speed
    /// * sample_rate. Both <= 0 disables the gate.
    ///
    /// Defaults (P1.1 evolve 2026-05-16): samples = 0.0 (disabled standalone),
    /// fraction = 0.3 (~= 30% of max physical TDOA). Array-scale invariant:
    /// e.g. 0.063m@16kHz physical_max ≈ 2.94 samples → effective ≈ 0.88
    /// samples; 0.21m@16kHz physical_max ≈ 9.79 samples → effective ≈ 2.94
    /// samples. Pre-P1.1 default 2.0 samples was scale-sensitive (= 68%
    /// of physical for 0.063m array, effectively no rejection).
    float closure_threshold_samples = 0.0f;
    float closure_threshold_fraction = 0.3f;

    /// Speed of sound (m/s).
    float sound_speed = 343.0f;

    /// Use FFTW_MEASURE for faster FFTs (slower init).
    bool use_fftw_measure = false;

    /// Microphone positions. N >= 2; N = 3 validated in v1; closure gate
    /// is only active for N = 3.
    std::vector<MicrophonePosition> microphones;

    /// Array-frame to robot-frame offset (degrees).
    float azimuth_offset_deg = 0.0f;

    /// GCC-PHAT band-limit. 0 = auto alias-safe c / (2 * d_max).
    float max_frequency_hz = 0.0f;

    /// Reserved for SRP-PHAT variants.
    float search_step_deg = 1.0f;
};

/// Atomic snapshot of the latest multi-channel DOA result.
///
/// Semantics of `confidence` (geometric mean x quality, post-A4) and
/// `peak_score` (arithmetic mean, backward-compat) are intentionally
/// different - see field comments.
struct MultiSoundLocatorResult {
    /// Robot-frame azimuth in [0, 360).
    float azimuth_deg = 0.0f;

    /// [A4/P1.1] geometric-mean of pair GCC peaks x quality. Pair peaks are
    /// active-bin normalized (P1.1) so they ≈ 1.0 for a clean source
    /// regardless of fft_size / max_frequency_hz / mic-array. Penalises a
    /// single dead pair instead of letting two strong pairs mask it (the
    /// failure mode of the old arithmetic mean). Used by `valid`. Same
    /// `confidence_threshold` (default 0.1) now means the same significance
    /// level across 2-ch and multi-ch paths.
    float confidence = 0.0f;

    /// Backward-compat: arithmetic mean of pair GCC peaks (the pre-A4
    /// semantics). Read this if you tuned thresholds against the old
    /// `confidence`.
    float peak_score = 0.0f;

    /// Raw norm of the unnormalized wavefront vector ||k_hat|| (legacy).
    /// `quality` is the clamped, symmetric version.
    float score_margin = 0.0f;

    /// [A5] clamp(1 - |1 - ||k_hat|||, 0, 1).
    /// 1 = perfect plane wave; 0 = inconsistent.
    /// Symmetric penalty on both ||k_hat||<1 and ||k_hat||>1.
    float quality = 0.0f;

    /// [A1] |tau_01 + tau_12 - tau_02| in seconds (N = 3 only; 0 otherwise).
    /// TDOA loop closure - a physical invariant for 3-mic arrays.
    float closure_residual_sec = 0.0f;

    /// Number of pair peaks above confidence_threshold.
    /// Informational: LSQ still uses all pairs.
    int valid_pairs = 0;

    /// `confidence >= confidence_threshold` AND
    /// `score_margin >= margin_threshold` AND
    /// frame RMS >= `min_signal_rms` AND
    /// `quality >= quality_threshold` AND
    /// (N != 3 OR `closure_samples <= closure_threshold_samples`).
    bool valid = false;
};

/// Multi-channel planar sound source locator.
///
/// v1 ships MPCC-LSQ: pairwise GCC-PHAT TDOAs are solved into a 2D wavefront
/// vector using a geometry-agnostic least-squares pseudo-inverse.
class MultiSoundLocator {
public:
    explicit MultiSoundLocator(const MultiSoundLocatorConfig& config);
    ~MultiSoundLocator();

    MultiSoundLocator(const MultiSoundLocator&) = delete;
    MultiSoundLocator& operator=(const MultiSoundLocator&) = delete;
    MultiSoundLocator(MultiSoundLocator&& other) noexcept;
    MultiSoundLocator& operator=(MultiSoundLocator&& other) noexcept;

    /// Allocate FFT plans and internal buffers. Must be called before Process().
    bool Initialize();

    /// Clear multi-frame accumulators and cached results.
    void Reset();

    /// Process interleaved float data [ch0, ch1, ..., chN-1, ch0, ...].
    /// Throws std::invalid_argument if n_channels does not match config.
    bool Process(const float* interleaved, size_t n_frames, int n_channels);

    /// Process separate float channel arrays.
    /// Throws std::invalid_argument if n_channels does not match config.
    bool Process(const float* const* channel_ptrs, size_t n_frames, int n_channels);

    /// Process interleaved PCM16 data.
    /// Throws std::invalid_argument if n_channels does not match config.
    bool Process(const int16_t* interleaved, size_t n_frames, int n_channels);

    MultiSoundLocatorResult GetResult() const;

    float GetAzimuth() const;
    float GetConfidence() const;
    bool IsValid() const;
    float GetAverageAzimuth() const;
    int GetResultCount() const;
    float GetTDOA(int i, int j) const;
    int GetMaxDelaySamplesPair(int i, int j) const;
    const MultiSoundLocatorConfig& GetConfig() const;

    // ----- New accessors (A1 / A3 / A5 / A6) -----

    /// [A1] |τ_01 + τ_12 − τ_02| of the latest batch (seconds).
    /// Only meaningful for N=3; returns 0 for other N.
    /// In a perfectly synchronized 3-mic array this is ~0; large values
    /// flag hardware-level channel desync or a dropped/duplicated sample.
    float GetClosureResidual() const;

    /// [A1] Same as GetClosureResidual() but in original samples.
    float GetClosureSamples() const;

    /// [A3] Copy the latest pair-by-pair GCC peak confidences into `out`.
    /// `n` must equal the number of pairs (N*(N-1)/2; e.g. 3 for N=3).
    /// Throws std::out_of_range if `n` does not match.
    void GetPairConfidences(float* out, int n) const;

    /// [A3] Number of microphone pairs (= N*(N-1)/2).
    int GetPairCount() const;

    /// [A5] Same as result.quality, the clamped consistency metric.
    float GetQuality() const;

    /// [A6] Mardia mean resultant length R ∈ [0, 1] of the azimuth running mean.
    /// 1 = stable direction (consistent across batches);
    /// 0 = scattered / multi-source / noise.
    /// Computed over the same window as GetAverageAzimuth (full history when
    /// `max_avg_seconds == 0`, sliding window when > 0). Returns 0 if no
    /// valid results yet.
    float GetAverageResultantLength() const;

    static MultiSoundLocatorConfig CreateEquilateralTriangleConfig(
        float side_length_m = 0.063f);

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace SpacemitAudio

#endif  // DOA_SERVICE_H
