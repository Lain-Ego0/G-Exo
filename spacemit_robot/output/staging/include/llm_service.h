/*
 * Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
 * SPDX-License-Identifier: Apache-2.0
 */

#ifndef LLM_SERVICE_H
#define LLM_SERVICE_H

#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <vector>

namespace spacemit_llm {

// Forward declarations
struct LLMServiceImpl;

/**
 * LLM Service - C++ interface (PIMPL)
 * Supports multiple backends:
 * 1. OpenAI-compatible HTTP API
 * 2. Custom backends (e.g., local inference engines)
 */
class LLMService {
public:
    // -------------------------------------------------------------------------
    // Chat types (multi-turn / tool calling)
    // -------------------------------------------------------------------------
    struct ChatMessage {
        enum class Role { SYSTEM, USER, ASSISTANT, TOOL };
        Role role;
        std::string content;
        std::string tool_calls_json;  // assistant's tool calls (JSON array)
        std::string tool_call_id;     // tool reply's corresponding call id
        std::string reasoning_content;  // assistant reasoning content for APIs that require replay

        static ChatMessage System(const std::string& content) {
            return {Role::SYSTEM, content, "", "", ""};
        }
        static ChatMessage User(const std::string& content) {
            return {Role::USER, content, "", "", ""};
        }
        static ChatMessage Assistant(const std::string& content,
            const std::string& tool_calls = "",
            const std::string& reasoning_content = "") {
            return {Role::ASSISTANT, content, tool_calls, "", reasoning_content};
        }
        static ChatMessage Tool(const std::string& content, const std::string& tool_call_id) {
            return {Role::TOOL, content, "", tool_call_id, ""};
        }
    };

    struct ChatResult {
        std::string content;
        std::string tool_calls_json;
        bool cancelled = false;
        std::string error;
        std::string reasoning_content;

        bool HasToolCalls() const {
            return !tool_calls_json.empty() && tool_calls_json != "[]";
        }
    };

    enum class BackendType {
        OPENAI_API,  // HTTP API (Ollama, vLLM, etc.)
        CUSTOM       // Custom backend
    };

    /**
     * Constructor for OpenAI-compatible API mode
     */
    LLMService(
        const std::string& model,
        const std::string& api_base = "http://localhost:8000/v1",
        const std::string& api_key = "EMPTY",
        const std::string& prompt = "You are a helpful assistant.",
        int max_tokens = 512);

    /**
     * Constructor for custom/local backend mode
     */
    LLMService(
        const std::string& config_dir,
        const std::string& prompt = "You are a helpful assistant.",
        int max_tokens = 512);

    ~LLMService();

    // Non-copyable
    LLMService(const LLMService&) = delete;
    LLMService& operator=(const LLMService&) = delete;

    // =========================================================================
    // Single-turn completion (Completions-style)
    // =========================================================================

    std::string complete(
        const std::string& user_text,
        const std::string& prompt = "");

    void complete_async(
        const std::string& user_text,
        std::function<void(const std::string& result, const std::string& error)> callback,
        const std::string& prompt = "");

    /**
     * Streaming completion (single-turn).
     * Callback returns bool: false = cancel the stream.
     */
    void complete_stream(
        const std::string& user_text,
        std::function<bool(const std::string& chunk, bool is_finished, const std::string& error)> callback,
        const std::string& prompt = "");

    // =========================================================================
    // Multi-turn chat
    // =========================================================================

    /**
     * Multi-turn chat (sync)
     */
    std::string chat(const std::vector<ChatMessage>& messages);

    /**
     * Multi-turn chat (streaming, blocking).
     * Supports cancellation via callback returning false.
     * Supports tool calling via tools_json (OpenAI function calling format).
     */
    ChatResult chat_stream(
        const std::vector<ChatMessage>& messages,
        std::function<bool(const std::string& chunk, bool is_done, const std::string& error)> callback,
        const std::string& tools_json = "");

    // =========================================================================
    // Configuration
    // =========================================================================

    void update_prompt(const std::string& new_prompt, int max_tokens = -1);
    void update_model(const std::string& new_model);
    void update_api_settings(const std::string& api_base, const std::string& api_key);
    void update_reasoning_budget(int reasoning_budget);

    // =========================================================================
    // Metrics (LLM-oriented performance indicators)
    // =========================================================================

    struct Metrics {
        // ---- Request counts & state ----
        int total_requests = 0;       ///< Total number of completed requests
        bool is_processing = false;   ///< True if a request is in progress

        // ---- Latency (ms) ----
        double last_latency_ms = 0.0;  ///< End-to-end latency of last request
        double avg_latency_ms = 0.0;   ///< Average end-to-end latency over all requests
        double last_ttft_ms = 0.0;     ///< Time To First Token (streaming); 0 if N/A

        // ---- Token / throughput ----
        int64_t last_output_tokens = -1;  ///< Output tokens; when server has no usage, estimated as stream chunk count
        double last_tokens_per_second = 0.0;  ///< Output tokens/s (generation phase)
    };
    Metrics get_metrics() const;

    BackendType get_backend_type() const;

private:
    std::unique_ptr<LLMServiceImpl> pimpl_;
};

// Namespace-level aliases for API stability (use spacemit_llm::ChatMessage, spacemit_llm::ChatResult)
using ChatMessage = LLMService::ChatMessage;
using ChatResult = LLMService::ChatResult;

}  // namespace spacemit_llm

#endif  // LLM_SERVICE_H
