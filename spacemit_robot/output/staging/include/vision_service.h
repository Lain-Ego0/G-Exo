/*
 * Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
 * SPDX-License-Identifier: Apache-2.0
 *
 * Public API / stable ABI: this header and the vision library are the customer-facing
 * contract. Internal refactors do not change this API.
 *
 * Result data structures are defined ONCE here (namespace vision) and reused
 * internally; there is no separate "service result" struct or conversion layer.
 */

#ifndef VISION_SERVICE_H
#define VISION_SERVICE_H

#include <cstdint>
#include <memory>
#include <string>
#include <type_traits>
#include <variant>
#include <vector>

#include <opencv2/core.hpp>

namespace vision {

// ============================================================================
// Result data types (plain data / POD-like; helper logic lives in src/).
// ============================================================================

struct BoundingBox {
    float x1 = 0.0f;
    float y1 = 0.0f;
    float x2 = 0.0f;
    float y2 = 0.0f;
};

struct KeyPoint {
    float x = 0.0f;
    float y = 0.0f;
    float visibility = 0.0f;  // 0.0-1.0 confidence
};

// Object detection (YOLOv5/8/11/12, face, gesture, fire...).
struct Detection {
    BoundingBox bbox;
    float score = 0.0f;
    int label = -1;
};

// Image classification (ResNet, MobileNet, Emotion...).
struct Classification {
    int label = -1;
    float score = 0.0f;
    std::vector<float> class_scores;  // all class probabilities (may be empty)
};

// Pose estimation (YOLOv8-pose).
struct Pose {
    BoundingBox bbox;
    float score = 0.0f;
    int label = -1;
    std::vector<KeyPoint> keypoints;
};

// Instance/semantic segmentation (YOLOv8-seg, PP-LiteSeg).
struct Segmentation {
    BoundingBox bbox;
    float score = 0.0f;
    int label = -1;
    std::shared_ptr<cv::Mat> mask;  // binary mask, may be null
};

// Face/object embedding (ArcFace).
struct Embedding {
    std::vector<float> embedding;
    float score = 1.0f;
};

// Object tracking (ByteTrack, OC-SORT).
struct Tracking {
    BoundingBox bbox;
    float score = 0.0f;
    int label = -1;
    int track_id = -1;

    enum class State : uint8_t { Tentative = 0, Confirmed = 1, Lost = 2 };
    State state = State::Confirmed;
};

// Sequence action recognition (STGCN, Emotion-LSTM).
struct Action {
    int label = -1;
    float score = 0.0f;
    std::vector<float> class_scores;
};

// Text detection + recognition (OCR, e.g. PP-OCR). Each result is one text
// instance: a 4-point polygon (usually clockwise from top-left, in pixel
// coordinates), the recognized string, and a confidence score.
struct Text {
    std::vector<KeyPoint> polygon;  // quadrilateral corners (x, y); visibility unused
    std::string text;               // recognized characters (UTF-8)
    float score = 0.0f;             // recognition confidence
    int label = -1;                 // unused for OCR (kept for accessor symmetry)
};

// ============================================================================
// Unified result variant
// ============================================================================

using Result = std::variant<
    Detection,
    Classification,
    Pose,
    Segmentation,
    Embedding,
    Tracking,
    Action,
    Text>;

using ResultList = std::vector<Result>;

// ============================================================================
// Result accessors (convenience helpers over the Result variant)
//
// For concrete-type access use std::get_if / std::holds_alternative directly,
// e.g. std::get_if<vision::Detection>(&r). The helpers below cover the common
// case of reading shared fields (bbox/score/label/track_id) without first
// knowing the task type.
// ============================================================================

// Score is present on every result type.
inline float get_score(const Result& r) {
    return std::visit([](const auto& v) -> float { return v.score; }, r);
}

// Bounding box for box-bearing results; empty box otherwise.
inline BoundingBox get_bbox(const Result& r) {
    return std::visit([](const auto& v) -> BoundingBox {
        using T = std::decay_t<decltype(v)>;
        if constexpr (std::is_same_v<T, Detection> || std::is_same_v<T, Pose> ||
            std::is_same_v<T, Segmentation> || std::is_same_v<T, Tracking>) {
            return v.bbox;
        } else {
            return BoundingBox{};
        }
    }, r);
}

// Class label for label-bearing results; -1 otherwise (e.g. Embedding).
inline int get_label(const Result& r) {
    return std::visit([](const auto& v) -> int {
        using T = std::decay_t<decltype(v)>;
        if constexpr (std::is_same_v<T, Embedding>) {
            return -1;
        } else {
            return v.label;
        }
    }, r);
}

// Track id for Tracking results; -1 otherwise.
inline int get_track_id(const Result& r) {
    if (const Tracking* t = std::get_if<Tracking>(&r)) {
        return t->track_id;
    }
    return -1;
}

}  // namespace vision

// ============================================================================
// Inference request / response
// ============================================================================

// Inference-time parameters. A field <= 0 (or <0 for ints) means "use the
// model default from config".
struct VisionServiceInferParams {
    float conf_threshold = -1.0f;
    float iou_threshold = -1.0f;
    int top_k = -1;
    float kp_threshold = -1.0f;
    float mask_threshold = -1.0f;
    int max_det = -1;
};

enum class VisionPixelFormat : std::uint8_t {
    BGR8 = 0,
    NV12 = 1,
};

// Unified inference input. Image models fill `image`; sequence models
// (e.g. STGCN) fill the skeleton point buffer + frame size.
struct VisionServiceRequest {
    // Host memory must remain readable and unmodified until Infer() returns.
    // With image_dma_fd >= 0, image describes the mapped DMA-BUF layout.
    cv::Mat image;                        // image-based models
    VisionPixelFormat image_format = VisionPixelFormat::BGR8;
    int image_dma_fd = -1;                // >= 0 imports DMA-BUF; otherwise host memory

    const float* sequence_pts = nullptr;  // sequence models: skeleton points
    int sequence_count = 0;               // length of sequence_pts; if > 0 it is
                                          // validated against the model's expected
                                          // size to prevent out-of-bounds reads
    int sequence_width = 0;               // source frame width
    int sequence_height = 0;              // source frame height

    // Open-vocabulary text prompts (e.g. YOLO-World). Empty means "use the
    // model's configured default vocabulary". Models that don't consume text
    // ignore this field, so existing image/sequence callers are unaffected.
    std::vector<std::string> prompts;

    VisionServiceInferParams params;
};

// Unified inference response.
struct VisionServiceResponse {
    vision::ResultList results;
    bool ok = true;
    std::string error_message;
};

struct VisionServiceProfileEntry {
    // Naming contract: repeated calls to the same logical model instance use
    // the same name; different roles or model instances use distinct names.
    std::string name;
    double total_ms = 0.0;
    uint64_t calls = 0;
};

struct VisionServiceProfile {
    std::vector<VisionServiceProfileEntry> components;
};

struct VisionServiceTiming {
    // Generic image pipeline stages (most models)
    double preprocess_ms = 0.0;
    double model_infer_ms = 0.0;
    double postprocess_ms = 0.0;

    // Tracking pipeline stages (tracking models)
    double detect_ms = 0.0;
    double track_ms = 0.0;

    // Aggregated totals
    double infer_ms = 0.0;
    double draw_ms = 0.0;

    // Other task types
    double embedding_ms = 0.0;
    double sequence_ms = 0.0;
};

struct VisionServiceTimingOptions {
    bool enabled = false;
    bool print_to_stdout = false;
};

enum VisionServiceStatus {
    VISION_SERVICE_OK = 0,
    VISION_SERVICE_INVALID_ARGUMENT = 1,
    VISION_SERVICE_CREATE_FAILED = 2,
    VISION_SERVICE_INFER_FAILED = 3,
    VISION_SERVICE_IO_FAILED = 4
};

/**
 * @brief Vision inference service
 *
 * @thread_safety IMPORTANT: VisionService instances are NOT thread-safe.
 *
 * Thread Safety Rules:
 * - Create() is thread-safe (can be called from multiple threads)
 * - All other methods are NOT thread-safe for the same instance
 * - Do NOT call Infer/Draw concurrently on the same instance
 *
 * Correct Multi-threading Usage:
 * - Option 1: Create separate VisionService instances for each thread (RECOMMENDED)
 * - Option 2: Use a thread pool with one VisionService per worker thread
 * - Option 3: Protect with mutex (NOT recommended, serializes inference)
 */
class VisionService {
public:
    /**
     * @brief Create a VisionService instance
     * @thread_safety Thread-safe. Can be called from multiple threads.
     */
    static std::unique_ptr<VisionService> Create(const std::string& config_path,
                                                const std::string& model_path_override = "",
                                                bool lazy_load = false);

    /**
     * @brief Get last creation error
     * @thread_safety Thread-safe (uses thread_local storage)
     */
    static const std::string& LastCreateError();

    /**
     * @brief Run inference. The single entry point for all model types.
     *
     * The model's task type is inferred from its config; results are returned
     * as task-specific variants in `response->results`. For image models set
     * `request.image`; for sequence models set `request.sequence_pts` etc.
     *
     * @thread_safety NOT thread-safe. Do not call concurrently on the same instance.
     */
    VisionServiceStatus Infer(
        const VisionServiceRequest& request,
        VisionServiceResponse* response);

    /**
     * @brief Convenience overload: load an image file then run inference.
     * @thread_safety NOT thread-safe.
     */
    VisionServiceStatus Infer(
        const std::string& image_path,
        VisionServiceResponse* response,
        const VisionServiceInferParams& params = {});

    /**
     * @brief Convenience overload: run inference on a cv::Mat image.
     * @thread_safety NOT thread-safe.
     */
    VisionServiceStatus Infer(
        const cv::Mat& image,
        VisionServiceResponse* response,
        const VisionServiceInferParams& params = {});

    /**
     * @brief Encode a text string into an embedding vector (multimodal models).
     * @thread_safety NOT thread-safe.
     */
    VisionServiceStatus EncodeText(const std::string& text,
                                    std::vector<float>* out_embedding);

    /**
     * @brief Compute cosine similarity between two embeddings
     * @thread_safety Thread-safe (pure function)
     */
    static float EmbeddingSimilarity(const std::vector<float>& embedding_a,
                                    const std::vector<float>& embedding_b);

    /**
     * @brief Draw inference results on an image.
     *
     * Stateless: the results to draw are passed explicitly, so this is
     * re-entrant and not coupled to the last Infer() call.
     *
     * @thread_safety NOT thread-safe. Do not call concurrently on the same instance.
     */
    VisionServiceStatus Draw(
        const cv::Mat& image,
        const VisionServiceResponse& response,
        cv::Mat* out_image);

    /**
     * @brief Check if current model supports drawing
     * @thread_safety Thread-safe after model is loaded
     */
    bool SupportsDraw() const;

    /**
     * @brief Release model resources
     * @thread_safety NOT thread-safe. Do not call while inference is running.
     */
    void Release();

    /**
     * @brief Set timing options
     * @thread_safety NOT thread-safe.
     */
    void SetTimingOptions(const VisionServiceTimingOptions& options);

    /**
     * @brief Get timing data from last inference
     * @thread_safety NOT thread-safe. Only call from the same thread that ran inference.
     */
    VisionServiceTiming GetLastTiming() const;

    /**
     * @brief Get named component timings from the last inference
     * Returns an empty component list when timing is disabled or when the
     * model only reports the legacy scalar timing fields.
     * @thread_safety NOT thread-safe. Only call from the same thread that ran inference.
     */
    VisionServiceProfile GetLastProfile() const;

    /**
     * @brief Get default image path from config
     * @thread_safety Thread-safe after construction
     */
    std::string GetDefaultImage();

    /**
     * @brief Get config value by key (also used to read model-specific values,
     *        e.g. a sequence model's fall-down class index, from its yaml).
     * @thread_safety Thread-safe after construction
     */
    std::string GetConfigPathValue(const std::string& config_key);

    /**
     * @brief Get the class-name table loaded from the model's config
     *        (label_file_path). Empty if the config declares no labels.
     *        Index into it with a result's `label` to get a human-readable name.
     * @thread_safety Thread-safe after construction.
     */
    std::vector<std::string> GetClassNames() const;

    /**
     * @brief Get last error message
     * @thread_safety Thread-safe (uses instance-local storage)
     */
    const std::string& LastError() const;

    ~VisionService();

private:
    VisionService() = default;

    VisionServiceStatus SetError(VisionServiceStatus code, const std::string& message);

    struct Impl;
    std::unique_ptr<Impl> impl_;
    std::string last_error_;

    static thread_local std::string g_last_error_;
};

#endif  // VISION_SERVICE_H
