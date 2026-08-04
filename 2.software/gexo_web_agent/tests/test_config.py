from __future__ import annotations

from gexo_web_agent.config import load_settings


def test_environment_overrides_yaml(monkeypatch, tmp_path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(
        "bridge:\n  topic: /yaml/topic\nllm:\n  model: yaml-model\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("GEXO_BRIDGE__TOPIC", "/env/topic")
    monkeypatch.setenv("GEXO_LLM__MODEL", "env-model")

    settings = load_settings(str(config))

    assert settings.bridge.topic == "/env/topic"
    assert settings.llm.model == "env-model"


def test_yaml_is_used_without_environment_override(tmp_path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("bridge:\n  topic: /yaml/topic\n", encoding="utf-8")

    settings = load_settings(str(config))

    assert settings.bridge.topic == "/yaml/topic"
