import httpx
import pytest

from kontra_ki import lm_studio_client as client
from kontra_ki.lm_studio_client import LMStudioError, ask


class FakeAsyncClient:
    """Stand-in for httpx.AsyncClient exposing only what ask()/_resolve_model use."""

    def __init__(
        self, get_response=None, post_response=None, get_exc=None, post_exc=None
    ):
        self._get_response = get_response
        self._post_response = post_response
        self._get_exc = get_exc
        self._post_exc = post_exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, url, headers=None, timeout=None):
        self.get_headers = headers
        if self._get_exc:
            raise self._get_exc
        return self._get_response

    async def post(self, url, headers=None, json=None, timeout=None):
        self.post_headers = headers
        self.post_timeout = timeout
        if self._post_exc:
            raise self._post_exc
        return self._post_response


def make_response(json_data, status_code=200):
    request = httpx.Request("POST", "http://localhost:1234/v1/chat/completions")
    return httpx.Response(status_code, json=json_data, request=request)


def make_invalid_json_response():
    request = httpx.Request("POST", "http://localhost:1234/v1/chat/completions")
    return httpx.Response(200, content=b"not-json", request=request)


def use_fake_client(monkeypatch, **kwargs):
    fake = FakeAsyncClient(**kwargs)
    monkeypatch.setattr(client.httpx, "AsyncClient", lambda: fake)
    return fake


class TestAsk:
    async def test_returns_content_on_success(self, monkeypatch):
        monkeypatch.setattr(client, "CONFIGURED_MODEL", "test-model")
        use_fake_client(
            monkeypatch,
            post_response=make_response(
                {"choices": [{"message": {"content": "the critique"}}]}
            ),
        )

        result = await ask("system", "user")
        assert result == "the critique"

    async def test_sends_api_key_as_bearer_header(self, monkeypatch):
        monkeypatch.setattr(client, "CONFIGURED_MODEL", "test-model")
        monkeypatch.setattr(client, "API_KEY", "secret")
        fake = use_fake_client(
            monkeypatch,
            post_response=make_response(
                {"choices": [{"message": {"content": "the critique"}}]}
            ),
        )

        await ask("system", "user")

        assert fake.post_headers == {"Authorization": "Bearer secret"}

    async def test_uses_configured_request_timeout(self, monkeypatch):
        monkeypatch.setattr(client, "CONFIGURED_MODEL", "test-model")
        monkeypatch.setattr(client, "TIMEOUT_SECONDS", 7.0)
        fake = use_fake_client(
            monkeypatch,
            post_response=make_response(
                {"choices": [{"message": {"content": "the critique"}}]}
            ),
        )

        await ask("system", "user")

        assert fake.post_timeout == 7.0

    async def test_rejects_remote_http_endpoint(self, monkeypatch):
        monkeypatch.setattr(client, "LM_STUDIO_BASE", "http://remote-host:1234")
        monkeypatch.setattr(client, "LM_STUDIO_CHAT_URL", "http://remote-host:1234/v1/chat/completions")
        monkeypatch.setattr(client, "LM_STUDIO_MODELS_URL", "http://remote-host:1234/api/v0/models")
        monkeypatch.setattr(client, "API_KEY", "secret")

        with pytest.raises(LMStudioError, match="must use HTTPS"):
            await ask("system", "user")

    async def test_rejects_remote_https_without_api_key(self, monkeypatch):
        monkeypatch.setattr(client, "LM_STUDIO_BASE", "https://remote-host:1234")
        monkeypatch.setattr(client, "LM_STUDIO_CHAT_URL", "https://remote-host:1234/v1/chat/completions")
        monkeypatch.setattr(client, "LM_STUDIO_MODELS_URL", "https://remote-host:1234/api/v0/models")
        monkeypatch.setattr(client, "API_KEY", None)

        with pytest.raises(LMStudioError, match="require KONTRA_KI_LM_STUDIO_API_KEY"):
            await ask("system", "user")

    async def test_raises_on_empty_choices(self, monkeypatch):
        monkeypatch.setattr(client, "CONFIGURED_MODEL", "test-model")
        use_fake_client(monkeypatch, post_response=make_response({"choices": []}))

        with pytest.raises(LMStudioError, match="unexpected response shape"):
            await ask("system", "user")

    async def test_raises_on_message_without_content(self, monkeypatch):
        monkeypatch.setattr(client, "CONFIGURED_MODEL", "test-model")
        use_fake_client(
            monkeypatch, post_response=make_response({"choices": [{"message": {}}]})
        )

        with pytest.raises(LMStudioError, match="unexpected response shape"):
            await ask("system", "user")

    async def test_raises_on_invalid_json_response(self, monkeypatch):
        monkeypatch.setattr(client, "CONFIGURED_MODEL", "test-model")
        use_fake_client(monkeypatch, post_response=make_invalid_json_response())

        with pytest.raises(LMStudioError, match="invalid JSON"):
            await ask("system", "user")

    async def test_raises_on_non_list_choices(self, monkeypatch):
        monkeypatch.setattr(client, "CONFIGURED_MODEL", "test-model")
        use_fake_client(monkeypatch, post_response=make_response({"choices": {}}))

        with pytest.raises(LMStudioError, match="unexpected response shape"):
            await ask("system", "user")

    async def test_raises_on_connect_error(self, monkeypatch):
        monkeypatch.setattr(client, "CONFIGURED_MODEL", "test-model")
        request = httpx.Request("POST", "http://localhost:1234/v1/chat/completions")
        use_fake_client(monkeypatch, post_exc=httpx.ConnectError("refused", request=request))

        with pytest.raises(LMStudioError, match="Could not reach"):
            await ask("system", "user")

    async def test_raises_on_timeout(self, monkeypatch):
        monkeypatch.setattr(client, "CONFIGURED_MODEL", "test-model")
        request = httpx.Request("POST", "http://localhost:1234/v1/chat/completions")
        use_fake_client(monkeypatch, post_exc=httpx.TimeoutException("slow", request=request))

        with pytest.raises(LMStudioError, match="timed out"):
            await ask("system", "user")

    async def test_raises_on_other_request_error(self, monkeypatch):
        monkeypatch.setattr(client, "CONFIGURED_MODEL", "test-model")
        request = httpx.Request("POST", "http://localhost:1234/v1/chat/completions")
        use_fake_client(monkeypatch, post_exc=httpx.ReadError("connection lost", request=request))

        with pytest.raises(LMStudioError, match="communicate with LM Studio"):
            await ask("system", "user")

    async def test_raises_on_http_status_error(self, monkeypatch):
        monkeypatch.setattr(client, "CONFIGURED_MODEL", "test-model")
        use_fake_client(monkeypatch, post_response=make_response({"error": "boom"}, status_code=500))

        with pytest.raises(LMStudioError, match="HTTP 500"):
            await ask("system", "user")


class TestResolveModel:
    async def test_uses_configured_model_without_network_call(self, monkeypatch):
        monkeypatch.setattr(client, "CONFIGURED_MODEL", "pinned-model")
        fake = use_fake_client(monkeypatch, get_response=make_response({"data": []}))

        async with client.httpx.AsyncClient() as c:
            model = await client._resolve_model(c)
        assert model == "pinned-model"

    async def test_auto_detects_single_loaded_chat_model(self, monkeypatch):
        monkeypatch.setattr(client, "CONFIGURED_MODEL", None)
        data = {
            "data": [
                {"id": "chat-model", "state": "loaded", "type": "llm"},
                {"id": "embed-model", "state": "loaded", "type": "embeddings"},
                {"id": "unloaded-model", "state": "not-loaded", "type": "llm"},
            ]
        }
        async with FakeAsyncClient(get_response=make_response(data)) as c:
            model = await client._resolve_model(c)
        assert model == "chat-model"

    async def test_raises_when_no_chat_model_loaded(self, monkeypatch):
        monkeypatch.setattr(client, "CONFIGURED_MODEL", None)
        data = {"data": [{"id": "embed-model", "state": "loaded", "type": "embeddings"}]}
        async with FakeAsyncClient(get_response=make_response(data)) as c:
            with pytest.raises(LMStudioError, match="no chat-capable model"):
                await client._resolve_model(c)

    async def test_raises_when_multiple_chat_models_loaded(self, monkeypatch):
        monkeypatch.setattr(client, "CONFIGURED_MODEL", None)
        data = {
            "data": [
                {"id": "model-a", "state": "loaded", "type": "llm"},
                {"id": "model-b", "state": "loaded", "type": "llm"},
            ]
        }
        async with FakeAsyncClient(get_response=make_response(data)) as c:
            with pytest.raises(LMStudioError, match="multiple loaded"):
                await client._resolve_model(c)

    async def test_raises_on_invalid_model_json(self, monkeypatch):
        monkeypatch.setattr(client, "CONFIGURED_MODEL", None)

        async with FakeAsyncClient(get_response=make_invalid_json_response()) as c:
            with pytest.raises(LMStudioError, match="invalid JSON"):
                await client._resolve_model(c)

    async def test_raises_on_malformed_model_data(self, monkeypatch):
        monkeypatch.setattr(client, "CONFIGURED_MODEL", None)
        data = {"data": [{"state": "loaded", "type": "llm"}]}

        async with FakeAsyncClient(get_response=make_response(data)) as c:
            with pytest.raises(LMStudioError, match="unexpected model response shape"):
                await client._resolve_model(c)
