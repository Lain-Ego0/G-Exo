from __future__ import annotations

import pytest

from gexo_web_agent.config import LlmConfig
from gexo_web_agent.llm_client import LlmClient


class _Response:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}


class _AsyncClient:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.payload: dict | None = None

    async def post(self, path: str, *, json: dict) -> _Response:
        assert path == "/chat/completions"
        self.payload = json
        return _Response()

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_chat_uses_deployed_model_and_disables_thinking(monkeypatch) -> None:
    fake = _AsyncClient()

    def build_fake(**kwargs):
        fake.kwargs = kwargs
        return fake

    monkeypatch.setattr(
        "gexo_web_agent.llm_client.httpx.AsyncClient", build_fake
    )
    client = LlmClient(LlmConfig())

    message = await client.chat([{"role": "user", "content": "status"}])

    assert message["content"] == "ok"
    assert fake.kwargs["base_url"] == "http://127.0.0.1:9193/v1"
    assert fake.payload is not None
    assert fake.payload["model"] == "Qwen3.5-0.8B-Q4_0.gguf"
    assert fake.payload["chat_template_kwargs"] == {"enable_thinking": False}
    await client.close()
