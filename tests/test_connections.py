import asyncio
from itertools import pairwise
from unittest.mock import AsyncMock

import httpx2
import pytest
from pydantic import ValidationError

from app.core import connections
from app.core.config import Settings, settings
from app.main import app, lifespan


def test_shared_client_paces_concurrent_vlr_requests_across_fresh_event_loops(monkeypatch):
    interval = 0.015
    monkeypatch.setattr(settings, "VLR_REQUEST_INTERVAL_SECONDS", interval)
    for feature in ("ENABLE_DATABASE", "ENABLE_CACHE", "ENABLE_LIVE_PUSH", "LLM_RATE_LIMIT_ENABLED"):
        monkeypatch.setattr(settings, feature, False)
    monkeypatch.setattr(connections, "http_client", None)
    lifecycles = []

    async def run_requests():
        started = []
        clients = []

        def respond(request):
            started.append(asyncio.get_running_loop().time())
            return httpx2.Response(200, text="ok", request=request)

        monkeypatch.setattr(connections, "build_transport", lambda: httpx2.MockTransport(respond))

        async def fetch(url):
            async with connections.get_http_client() as client:
                clients.append(client)
                return await client.get(url)

        async with lifespan(app):
            shared = connections.http_client
            responses = await asyncio.gather(
                fetch("https://www.vlr.gg/matches"),
                fetch("https://vlr.gg/events"),
                fetch("https://www.vlr.gg/team/624"),
            )
            assert all(client is shared for client in clients)
            assert [response.text for response in responses] == ["ok", "ok", "ok"]

        assert shared.is_closed
        assert connections.http_client is None
        assert len(started) == 3
        assert all(later - earlier >= interval * 0.9 for earlier, later in pairwise(started))
        lifecycles.append(shared)

    asyncio.run(run_requests())
    asyncio.run(run_requests())
    assert lifecycles[0] is not lifecycles[1]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("interval", "url"),
    [(0, "https://www.vlr.gg/matches"), (1, "https://media.example.test/image.png")],
    ids=["disabled", "other-host"],
)
async def test_temporary_client_skips_waits_when_pacing_does_not_apply(monkeypatch, interval, url):
    monkeypatch.setattr(connections, "http_client", None)
    monkeypatch.setattr(settings, "VLR_REQUEST_INTERVAL_SECONDS", interval)
    monkeypatch.setattr(
        connections,
        "build_transport",
        lambda: httpx2.MockTransport(lambda request: httpx2.Response(200, text="ok", request=request)),
    )
    sleep = AsyncMock()
    monkeypatch.setattr(connections.asyncio, "sleep", sleep)

    async with connections.get_http_client() as client:
        responses = await asyncio.gather(client.get(url), client.get(url))

    assert [response.status_code for response in responses] == [200, 200]
    assert client.is_closed
    sleep.assert_not_awaited()


def test_request_interval_configuration_accepts_zero_and_rejects_negative(monkeypatch):
    for name in Settings.model_fields:
        monkeypatch.delenv(name, raising=False)
    assert Settings(_env_file=None, VLR_REQUEST_INTERVAL_SECONDS=0).VLR_REQUEST_INTERVAL_SECONDS == 0
    with pytest.raises(ValidationError, match="VLR_REQUEST_INTERVAL_SECONDS"):
        Settings(_env_file=None, VLR_REQUEST_INTERVAL_SECONDS=-1)
