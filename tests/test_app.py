import importlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx2
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import constants
from app.core import connections
from app.core.config import Settings, settings
from app.services import player

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def stateless_app(request, monkeypatch):
    with monkeypatch.context() as configuration:
        for name in Settings.model_fields:
            configuration.delenv(name, raising=False)
        defaults = Settings(_env_file=None)
        for name in Settings.model_fields:
            configuration.setattr(settings, name, getattr(defaults, name))
        configuration.setattr(settings, "API_KEYS", getattr(request, "param", {}))
        configuration.setattr(settings, "DETECT_SOURCE_TIMEZONE", False)

        import app.api.v1.api as api_module
        import app.api.v2.api as api_v2_module
        import app.main as app_module

        importlib.reload(api_module)
        importlib.reload(api_v2_module)
        importlib.reload(app_module)
        yield app_module.app

    importlib.reload(api_module)
    importlib.reload(api_v2_module)
    importlib.reload(app_module)


@pytest.mark.parametrize(
    "stateless_app", [{}, {"calendar": "test-key"}], indirect=True, ids=["public", "authenticated"]
)
def test_stateless_app_serves_scraped_data_through_the_full_lifecycle(stateless_app):
    pages = {
        constants.UPCOMING_MATCHES_URL: "matches.html",
        constants.PAST_MATCHES_URL: "matches_results.html",
        constants.MATCH_URL_WITH_ID.format("12345"): "match_12345.html",
        constants.TEAM_URL.format("624"): "team_624.html",
        constants.TEAM_UPCOMING_MATCHES_URL.format("624"): "team_624_upcoming.html",
        constants.TEAM_COMPLETED_MATCHES_URL.format("624"): "team_624_completed_page1.html",
        constants.PLAYER_URL.format("45"): "player_45.html",
        player.player_matches_url("45", 1): "player_matches_45_page1.html",
        constants.EVENTS_URL: "events_page1.html",
    }

    def vlr_response(request):
        return httpx2.Response(200, content=(FIXTURE_DIR / pages[str(request.url)]).read_bytes(), request=request)

    with (
        patch("app.core.connections.build_transport", return_value=httpx2.MockTransport(vlr_response)),
        TestClient(stateless_app) as client,
    ):
        shared_client = connections.http_client
        assert shared_client is not None and not shared_client.is_closed
        assert connections.database_engine is None
        assert connections.subscription_sessions is None
        assert connections.redis_pool is None
        assert client.get("/health").json() == {"status": "ok"}

        paths = client.get("/openapi.json").json()["paths"]
        for prefix in (
            "/api/v2/",
            "/api/v1/favorites",
            "/api/v1/live-updates",
            "/api/v1/internal",
            "/api/v1/video",
            "/api/v1/ask",
        ):
            assert not any(path.startswith(prefix) for path in paths)

        headers = {}
        if settings.API_KEYS:
            assert client.get("/api/v1/matches/").status_code == 401
            assert client.get("/api/v1/matches/", headers={"Authorization": "Bearer invalid"}).status_code == 401
            headers = {"Authorization": "Bearer test-key"}

        response = client.get("/api/v1/matches/", headers=headers)
        assert response.status_code == 200
        matches = {match["id"]: match for match in response.json()}
        assert matches["684611"]["team1"]["name"] == "FULL SENSE"
        assert matches["684612"]["team2"]["name"] == "Global Esports"
        assert matches["684611"]["time"]
        assert all(match["current_map"] is None for match in matches.values())

        response = client.get("/api/v1/matches/12345", headers=headers)
        assert response.status_code == 200
        match = response.json()
        assert match["teams"][0]["name"] == "Team A"
        assert match["data"][0]["map"] == "Lotus"
        assert match["insights"] is None

        response = client.get("/api/v1/team/624", headers=headers)
        assert response.status_code == 200
        team = response.json()
        assert team["name"] == "Paper Rex"
        assert team["completed"][0]["opponent"] == "EDward Gaming"
        assert len(team["completed"]) == 50

        response = client.get("/api/v1/player/45", headers=headers)
        assert response.status_code == 200
        player_data = response.json()
        assert (player_data["alias"], player_data["name"]) == ("SicK", "Hunter Mims")
        assert len(player_data["matches"]) == 50

        response = client.get("/api/v1/events/", headers=headers)
        assert response.status_code == 200
        assert response.json()[0]["id"] == "2765"

    assert shared_client.is_closed
    assert connections.http_client is None
    assert connections.database_engine is None
    assert connections.subscription_sessions is None
    assert connections.redis_pool is None


def test_feature_configuration_requires_its_declared_services(monkeypatch):
    for name in Settings.model_fields:
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ValidationError, match="ENABLE_DATABASE requires DATABASE_URL"):
        Settings(_env_file=None, ENABLE_DATABASE=True)
    with pytest.raises(ValidationError, match="ENABLE_ID_MAPPING requires ENABLE_CACHE"):
        Settings(_env_file=None, ENABLE_ID_MAPPING=True)
    with pytest.raises(ValidationError, match="ENABLE_LIVE_PUSH requires ENABLE_DATABASE"):
        Settings(_env_file=None, ENABLE_LIVE_PUSH=True)
    with pytest.raises(ValidationError, match="ENABLE_LIVE_PUSH requires API_KEYS"):
        Settings(
            _env_file=None,
            ENABLE_DATABASE=True,
            DATABASE_URL="postgresql+asyncpg://localhost/unused",
            ENABLE_LIVE_PUSH=True,
        )

    cache_only = Settings(_env_file=None, ENABLE_CACHE=True, ENABLE_ID_MAPPING=True)
    assert cache_only.needs_redis
    assert not cache_only.ENABLE_DATABASE
    assert not cache_only.ENABLE_LIVE_PUSH
    database_configured = Settings(_env_file=None, DATABASE_URL="postgresql+asyncpg://localhost/unused")
    assert not database_configured.ENABLE_DATABASE
    assert not database_configured.needs_redis
    stateless_insights = Settings(
        _env_file=None,
        PREDICTION_SERVICE_URL="https://predictions.example.com",
        ENABLE_MATCH_SUMMARIES=True,
        LLM_API_KEY="test-key",
    )
    assert not stateless_insights.needs_redis
    rate_limited = Settings(_env_file=None, LLM_RATE_LIMIT_ENABLED=True)
    assert rate_limited.needs_redis
    assert not rate_limited.needs_worker


def test_cache_only_lifecycle_schedules_scraping_without_database_or_push(stateless_app, monkeypatch):
    from app.cron.worker import arq_worker

    monkeypatch.setattr(settings, "ENABLE_CACHE", True)
    monkeypatch.setattr(settings, "ENABLE_ID_MAPPING", True)
    monkeypatch.setattr(settings, "RIOT_API_KEY", "test-riot-key")
    monkeypatch.setattr(settings, "LLM_API_KEY", "test-llm-key")
    monkeypatch.setattr(arq_worker, "task", None)
    run_worker = AsyncMock()
    monkeypatch.setattr(arq_worker, "_run", run_worker)
    redis_pool = MagicMock(aclose=AsyncMock())

    with patch("app.main.redis.ConnectionPool", return_value=redis_pool), TestClient(stateless_app) as client:
        shared_client = connections.http_client
        assert client.get("/health").status_code == 200
        assert connections.redis_pool is redis_pool
        assert connections.database_engine is None
        assert connections.subscription_sessions is None
        run_worker.assert_awaited_once()
        jobs = run_worker.await_args.args[0]
        assert {job.coroutine.__name__ for job in jobs} == {
            "rankings_cron",
            "matches_cron",
            "events_cron",
            "news_cron",
            "standings_cron",
        }

    redis_pool.aclose.assert_awaited_once()
    assert arq_worker.task.done()
    assert shared_client.is_closed
    assert connections.redis_pool is None
    assert connections.http_client is None


@pytest.mark.asyncio
async def test_rankings_cache_job_parses_and_caches_without_database(monkeypatch, http_response):
    from app import schemas
    from app.cron.jobs import rankings_cron

    monkeypatch.setattr(connections, "subscription_sessions", None)
    redis = AsyncMock()
    response = http_response(constants.RANKINGS_URL, (FIXTURE_DIR / "rankings.html").read_bytes())

    with patch("httpx2.AsyncClient.get", return_value=response):
        await rankings_cron({"redis": redis})

    redis.set.assert_awaited_once()
    cache_key, payload = redis.set.await_args.args
    assert cache_key == "rankings"
    rankings = schemas.RankingListAdapter.validate_json(payload)
    assert rankings[0].teams[0].name
    assert rankings[0].teams[0].rank == 1
    assert connections.database_engine is None
    assert connections.subscription_sessions is None
