"""The suite never reaches a real model: conftest pins the stub provider and blocks real HTTP.

backend/.env may hold a live LLM key (`LLM_PROVIDER=openai_compatible`); a test that reads settings
without pinning the provider must still get the stub, and a real request must fail the test.
"""

import httpx
import pytest

from app.core.config import get_settings
from app.llm.client import get_llm_client
from app.providers.openai_compatible import OpenAICompatibleProvider
from app.providers.stub import StubProvider


def test_settings_read_in_a_test_give_the_stub_provider():
    get_settings.cache_clear()
    settings = get_settings()
    assert (settings.llm_provider, settings.llm_api_key) == ("stub", "")
    assert isinstance(get_llm_client(settings).provider, StubProvider)


async def test_a_real_http_request_fails_the_test():
    provider = OpenAICompatibleProvider(api_key="k", base_url="http://127.0.0.1:9/v1", default_model="m")
    with pytest.raises(pytest.fail.Exception, match="network"):
        await provider.generate([])


def test_a_mock_transport_still_works():
    client = httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(200, text="ok")))
    assert client.get("http://example.test/").text == "ok"
