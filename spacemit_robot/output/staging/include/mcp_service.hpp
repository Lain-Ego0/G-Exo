/*
 * Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
 * SPDX-License-Identifier: Apache-2.0
 */

#ifndef MCP_SERVICE_HPP
#define MCP_SERVICE_HPP

#include <string>
#include <vector>
#include <memory>
#include <functional>
#include <chrono>
#include <map>
#include <stdexcept>
#include <nlohmann/json.hpp>

namespace mcp {

using json = nlohmann::json;

// ============================================================================
// 版本信息
// ============================================================================

constexpr const char* SDK_VERSION = "1.0.0";
constexpr const char* PROTOCOL_VERSION = "2024-11-05";

// ============================================================================
// 错误码
// ============================================================================

enum class ErrorCode {
    None = 0,

    // 传输层错误 (1xx)
    TransportError = 100,
    ConnectionFailed = 101,
    ConnectionClosed = 102,
    SendFailed = 103,
    ReceiveFailed = 104,
    Timeout = 105,

    // 协议层错误 (2xx)
    ProtocolError = 200,
    InvalidResponse = 201,
    InitializeFailed = 202,

    // 服务器错误 (3xx)
    ServerError = 300,
    ToolNotFound = 301,
    ServerNotFound = 302,
    ToolCallFailed = 303,
};

class MCPException : public std::runtime_error {
public:
    MCPException(ErrorCode code, const std::string& msg)
        : std::runtime_error(msg), code_(code) {}

    ErrorCode code() const { return code_; }

private:
    ErrorCode code_;
};

// ============================================================================
// Transport 抽象接口
// ============================================================================

class Transport {
public:
    virtual ~Transport() = default;

    virtual bool connect() = 0;
    virtual void disconnect() = 0;
    virtual bool isConnected() const = 0;
    virtual bool send(const std::string& data) = 0;
    virtual std::string receive(std::chrono::milliseconds timeout = std::chrono::milliseconds(5000)) = 0;
    virtual std::string typeName() const = 0;
};

// ============================================================================
// Transport 配置
// ============================================================================

struct StdioConfig {
    std::string command;                    // 要执行的命令
    std::vector<std::string> args;          // 命令参数
    std::string workingDir;                 // 工作目录（可选）
    std::map<std::string, std::string> env;  // 额外环境变量（可选）
    std::chrono::milliseconds startupTimeout{30000};  // 启动阶段 initialize/tools/list 超时
    std::chrono::milliseconds requestTimeout{30000};  // 稳态请求超时
};

struct UnixSocketConfig {
    std::string socketPath;  // Socket 文件路径
};

struct HttpConfig {
    std::string url;                            // MCP 端点 URL (如 http://host:port/mcp)
    std::map<std::string, std::string> headers;  // 额外 HTTP 头（可选）
    std::chrono::milliseconds timeout{30000};   // 请求超时
    bool enableSSE = true;                      // 是否启用 SSE 响应
};

// ============================================================================
// Transport 工厂函数
// ============================================================================

std::unique_ptr<Transport> createStdioTransport(const StdioConfig& config);
std::unique_ptr<Transport> createUnixSocketTransport(const UnixSocketConfig& config);
std::unique_ptr<Transport> createHttpTransport(const HttpConfig& config);

// ============================================================================
// 工具相关类型
// ============================================================================

struct Tool {
    std::string name;        // 工具名称
    std::string description;  // 工具描述
    json inputSchema;        // 输入参数 JSON Schema

    static Tool fromJson(const json& j) {
        Tool tool;
        tool.name = j.value("name", "");
        tool.description = j.value("description", "");
        if (j.contains("inputSchema")) {
            tool.inputSchema = j["inputSchema"];
        }
        return tool;
    }

    json toJson() const {
        return {
            {"name", name},
            {"description", description},
            {"inputSchema", inputSchema}
        };
    }
};

struct ToolResult {
    bool success = true;               // 是否成功
    std::vector<std::string> contents;  // 文本内容列表
    std::string error;                 // 错误信息（如果失败）
    json rawResult;                    // 原始 JSON 结果
};

struct ServerInfo {
    std::string name;       // 服务器名称
    std::string version;    // 服务器版本
    json capabilities;      // 服务器能力
};

// ============================================================================
// MCPClient - 单服务器客户端
// ============================================================================

struct ClientConfig {
    std::string name = "mcp-cpp-client";    // 客户端名称
    std::string version = "1.0.0";          // 客户端版本
    std::chrono::milliseconds requestTimeout{5000};  // 默认请求超时
};

class MCPClient {
public:
    using ToolsChangedHandler = std::function<void()>;

    explicit MCPClient(std::unique_ptr<Transport> transport, const ClientConfig& config = {});

    ~MCPClient();

    // 禁止拷贝
    MCPClient(const MCPClient&) = delete;
    MCPClient& operator=(const MCPClient&) = delete;

    // 允许移动
    MCPClient(MCPClient&&) noexcept;
    MCPClient& operator=(MCPClient&&) noexcept;

    bool connect();
    bool initialize(std::chrono::milliseconds timeout = std::chrono::milliseconds::zero());
    std::vector<Tool> listTools(std::chrono::milliseconds timeout = std::chrono::milliseconds::zero());
    ToolResult callTool(
        const std::string& name,
        const json& args,
        std::chrono::milliseconds timeout = std::chrono::milliseconds::zero());
    void onToolsChanged(ToolsChangedHandler handler);
    void shutdown();

    // 状态查询
    bool isConnected() const;
    bool isInitialized() const;
    const ServerInfo& serverInfo() const;
    const std::string& name() const;

private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};

// ============================================================================
// MCPManager - 多服务器管理
// ============================================================================

enum class ServerState {
    Disconnected,   // 未连接
    Connecting,     // 连接中
    Initializing,   // 初始化中
    Ready,          // 就绪
    Reconnecting,   // 重连中
    Error           // 错误
};

struct ServerStatus {
    std::string name;           // 服务器名称
    ServerState state;          // 当前状态
    std::vector<Tool> tools;    // 可用工具
    std::string lastError;      // 最后错误信息
};

class MCPManager {
public:
    MCPManager();
    ~MCPManager();

    // 禁止拷贝
    MCPManager(const MCPManager&) = delete;
    MCPManager& operator=(const MCPManager&) = delete;

    // ========== 服务器管理 ==========

    void addStdioServer(const std::string& name, const StdioConfig& config);
    void addUnixSocketServer(const std::string& name, const UnixSocketConfig& config);
    void addHttpServer(const std::string& name, const HttpConfig& config);
    bool removeServer(const std::string& name);
    bool startServer(const std::string& name);
    void stopServer(const std::string& name);
    void startAll();
    void stopAll();

    // ========== 等待服务器 ==========

    bool waitForAnyServer(std::chrono::milliseconds timeout = std::chrono::milliseconds(30000));
    bool waitForAllServers(std::chrono::milliseconds timeout = std::chrono::milliseconds(60000));

    // ========== 工具操作 ==========

    std::vector<Tool> getAllTools() const;
    json getAllToolsJson() const;
    ToolResult callTool(const std::string& toolName, const json& args);
    std::string findServerForTool(const std::string& toolName) const;

    // ========== 状态查询 ==========

    std::vector<ServerStatus> getStatuses() const;
    ServerStatus getStatus(const std::string& name) const;
    size_t readyServerCount() const;
    bool hasAvailableServers() const;

    // ========== 事件回调 ==========

    using ServerEventHandler = std::function<void(const std::string& serverName, ServerState state)>;
    using ToolChangeHandler = std::function<void(const std::vector<Tool>& tools)>;

    void onServerEvent(ServerEventHandler handler);
    void onToolChange(ToolChangeHandler handler);

private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};

// ============================================================================
// SDK 初始化
// ============================================================================

void init();
void cleanup();

struct SDKInit {
    SDKInit() { init(); }
    ~SDKInit() { cleanup(); }

    // 禁止拷贝
    SDKInit(const SDKInit&) = delete;
    SDKInit& operator=(const SDKInit&) = delete;
};

}  // namespace mcp

#endif  // MCP_SERVICE_HPP
