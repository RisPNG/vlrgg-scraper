import asyncio
from collections import Counter
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from unittest.mock import AsyncMock

import httpx2
import pytest
from bs4 import BeautifulSoup
from pydantic import ValidationError

from app import constants
from app.core import connections
from app.core.config import Settings, settings
from app.exceptions import ScrapingError
from app.main import app, lifespan
from app.services import matches, player, team

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.mark.asyncio
async def test_shared_source_timezone_calibrates_once_and_resets_with_the_client(monkeypatch):
    for feature in ("ENABLE_DATABASE", "ENABLE_CACHE", "ENABLE_LIVE_PUSH", "LLM_RATE_LIMIT_ENABLED"):
        monkeypatch.setattr(settings, feature, False)
    monkeypatch.setattr(settings, "DETECT_SOURCE_TIMEZONE", True)
    monkeypatch.setattr(settings, "VLR_REQUEST_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(connections, "http_client", None)
    soup = BeautifulSoup((FIXTURE_DIR / "team_624_completed_page1.html").read_bytes(), "lxml")
    cards = soup.select("a.m-item")
    cards[0].select_one(".m-item-date").string = "2026/10/09 TBD"
    cards[1]["href"] = "/754739/t1-vs-paper-rex-valorant-champions-2026-lr1"
    cards[1].select_one(".m-item-date").string = "2026/10/09 5:00 pm"
    pages = {
        team.completed_matches_url("624", 1): str(soup).encode(),
        constants.UPCOMING_MATCHES_URL: (FIXTURE_DIR / "matches.html").read_bytes(),
        player.player_matches_url("45", 1): (FIXTURE_DIR / "player_matches_45_page1.html").read_bytes(),
        "https://www.vlr.gg/754739/t1-vs-paper-rex-valorant-champions-2026-lr1": (
            FIXTURE_DIR / "match_timezone_singapore.html"
        ).read_bytes(),
    }
    requests = Counter()

    async def respond(request):
        url = str(request.url)
        requests[url] += 1
        if "/754739/" in url:
            await asyncio.sleep(0)
        return httpx2.Response(200, content=pages[url], request=request)

    monkeypatch.setattr(connections, "build_transport", lambda: httpx2.MockTransport(respond))
    for _ in range(2):
        requests.clear()
        async with lifespan(app):
            completed, upcoming, played = await asyncio.gather(
                team.get_team_matches_page("624"),
                matches.get_upcoming_matches(None),
                player.get_player_matches_page("45"),
            )
        assert completed[0].date is None
        assert completed[1].date == datetime(2026, 10, 9, 9, tzinfo=UTC)
        assert upcoming[0].time == datetime(2026, 6, 7, 11, 30, tzinfo=UTC)
        assert played[0].date.utcoffset().total_seconds() == 0
        assert sum(count for url, count in requests.items() if "/754739/" in url) == 1
        assert sum(requests.values()) == 4


@pytest.mark.asyncio
async def test_unobserved_source_timezone_does_not_publish_a_guessed_time(monkeypatch):
    monkeypatch.setattr(settings, "DETECT_SOURCE_TIMEZONE", True)
    monkeypatch.setattr(settings, "VLR_REQUEST_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(connections, "http_client", None)
    listing = (FIXTURE_DIR / "team_624_completed_page1.html").read_bytes()

    def respond(request):
        content = listing if "/team/" in request.url.path else b"<html><body>No announced clock</body></html>"
        return httpx2.Response(200, content=content, request=request)

    monkeypatch.setattr(connections, "build_transport", lambda: httpx2.MockTransport(respond))
    with pytest.raises(ScrapingError, match="rendered timezone"):
        await team.get_team_matches_page("624")


@pytest.mark.asyncio
async def test_missing_listing_metadata_cannot_fall_back_to_a_guessed_zone(monkeypatch, http_response):
    from unittest.mock import patch

    monkeypatch.setattr(settings, "DETECT_SOURCE_TIMEZONE", True)
    url = team.completed_matches_url("624", 1)
    response = http_response(url, (FIXTURE_DIR / "team_624_completed_page1.html").read_bytes())
    with (
        patch("httpx2.AsyncClient.get", return_value=response),
        pytest.raises(ScrapingError, match="rendered timezone"),
    ):
        await team.get_team_matches_page("624")


@pytest.mark.asyncio
async def test_an_existing_detail_seeds_a_named_zone_with_daylight_saving_rules(monkeypatch):
    for feature in ("ENABLE_DATABASE", "ENABLE_CACHE", "ENABLE_LIVE_PUSH", "LLM_RATE_LIMIT_ENABLED"):
        monkeypatch.setattr(settings, feature, False)
    monkeypatch.setattr(settings, "DETECT_SOURCE_TIMEZONE", True)
    monkeypatch.setattr(settings, "VLR_REQUEST_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(connections, "http_client", None)
    detail = (
        (FIXTURE_DIR / "match_timezone_singapore.html")
        .read_text()
        .replace("2026-10-09", "2026-01-09")
        .replace("October 9", "January 9")
        .replace("5:00 PM +08", "5:00 AM EST")
    )
    soup = BeautifulSoup((FIXTURE_DIR / "team_624_completed_page1.html").read_bytes(), "lxml")
    soup.select_one(".m-item-date").string = "2026/06/07 5:00 pm"
    requested = []

    def respond(request):
        requested.append(str(request.url))
        content = detail if request.url.path == "/542272" else str(soup)
        return httpx2.Response(200, text=content, headers={"content-type": "text/html"}, request=request)

    monkeypatch.setattr(connections, "build_transport", lambda: httpx2.MockTransport(respond))
    async with lifespan(app):
        await connections.http_client.get("https://www.vlr.gg/542272")
        completed = await team.get_team_matches_page("624")

    assert completed[0].date == datetime(2026, 6, 7, 21, tzinfo=UTC)
    assert requested == ["https://www.vlr.gg/542272", team.completed_matches_url("624", 1)]


@pytest.mark.asyncio
async def test_machine_timestamps_need_no_source_timezone_probe(monkeypatch):
    monkeypatch.setattr(settings, "DETECT_SOURCE_TIMEZONE", True)
    monkeypatch.setattr(settings, "VLR_REQUEST_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(connections, "http_client", None)
    soup = BeautifulSoup((FIXTURE_DIR / "matches.html").read_bytes(), "lxml")
    for card in soup.select("a.match-item"):
        card.select_one(".match-item-time")["data-utc-ts"] = "2026-10-09 05:00:00"
    requested = []

    def respond(request):
        requested.append(str(request.url))
        return httpx2.Response(200, text=str(soup), headers={"content-type": "text/html"}, request=request)

    monkeypatch.setattr(connections, "build_transport", lambda: httpx2.MockTransport(respond))
    upcoming = await matches.get_upcoming_matches(None)

    assert upcoming[0].time == datetime(2026, 10, 9, 9, tzinfo=UTC)
    assert requested == [constants.UPCOMING_MATCHES_URL]


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
