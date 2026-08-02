"""Configuration: config/default.yaml + GEXO_* env var overrides.

Env override examples:
    GEXO_BRIDGE__TRANSPORT=ros2
    GEXO_LLM__BASE_URL=http://127.0.0.1:9193/v1
    GEXO_STATE__STALE_TIMEOUT_S=2.0
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

PACKAGE_ROOT = Path(__file__).resolve().parent.parent  # .../2.software/gexo_web_agent


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000


class BridgeConfig(BaseModel):
    transport: Literal["mock", "ros2"] = "mock"
    topic: str = "/g_exo/bridge"
    message_mode: Literal["json_string"] = "json_string"
    source_id: str = "gexo_web_agent"


class StateConfig(BaseModel):
    stale_timeout_s: float = 1.0
    ws_min_interval_ms: int = 200


class CommandConfig(BaseModel):
    result_timeout_s: float = 3.0
    confirm_ttl_s: float = 30.0
    history_size: int = 200


class SafetyConfig(BaseModel):
    assist_min: float = 0.3
    assist_max: float = 1.0
    assist_step: float = 0.1


class LlmConfig(BaseModel):
    base_url: str = "http://127.0.0.1:9193/v1"
    model: str = "Qwen3.5-0.8B-Q4_0.gguf"
    api_key: str = "none"
    temperature: float = 0.1
    timeout_s: float = 30.0
    max_tokens: int = 1024
    enable_thinking: bool = False
    force_json_fallback: bool = True


class RagConfig(BaseModel):
    corpus_dirs: list[str] = Field(default_factory=lambda: ["data/docs"])
    db_path: str = "data/rag_index.db"
    chunk_size: int = 700
    chunk_overlap: int = 100
    top_k: int = 3


class MockConfig(BaseModel):
    state_hz: float = 5.0
    result_latency_ms: int = 150
    scenario: str = "normal"


class DebugConfig(BaseModel):
    enabled: bool = True


class LoggingConfig(BaseModel):
    level: str = "INFO"
    file: Optional[str] = None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GEXO_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    server: ServerConfig = ServerConfig()
    bridge: BridgeConfig = BridgeConfig()
    state: StateConfig = StateConfig()
    command: CommandConfig = CommandConfig()
    safety: SafetyConfig = SafetyConfig()
    llm: LlmConfig = LlmConfig()
    rag: RagConfig = RagConfig()
    mock: MockConfig = MockConfig()
    debug: DebugConfig = DebugConfig()
    logging: LoggingConfig = LoggingConfig()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # YAML is passed as init data; deployment env vars must override it.
        return env_settings, init_settings, dotenv_settings, file_secret_settings

    def resolve_path(self, p: str) -> Path:
        """Resolve a config-relative path against the package root."""
        path = Path(p)
        return path if path.is_absolute() else (PACKAGE_ROOT / path).resolve()


def load_settings(config_path: Optional[str] = None) -> Settings:
    """Load YAML config, then let GEXO_* env vars override.

    Search order for the YAML file:
    1. explicit `config_path` argument
    2. GEXO_CONFIG env var
    3. <package>/config/default.yaml
    """
    path = config_path or os.environ.get("GEXO_CONFIG") or str(PACKAGE_ROOT / "config" / "default.yaml")
    data: dict = {}
    p = Path(path)
    if p.is_file():
        with open(p, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    return Settings(**data)
