from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import deps
from app.api.v1.endpoints.matches import router as matches_router
from app.api.v1.endpoints.player import router as player_router
from app.api.v1.endpoints.team import router as team_router
from app.services import matches, player, team

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    ("path", "upstream", "fixture", "router", "prefix"),
    [
        (
            "/api/v1/matches/completed",
            matches.completed_matches_url(2),
            "matches_results_page2.html",
            matches_router,
            "/api/v1/matches",
        ),
        (
            "/api/v1/team/624/matches",
            team.completed_matches_url("624", 2),
            "team_624_completed_page2.html",
            team_router,
            "/api/v1/team",
        ),
        (
            "/api/v1/player/45/matches",
            player.player_matches_url("45", 2),
            "player_matches_45_page2.html",
            player_router,
            "/api/v1/player",
        ),
    ],
    ids=["global", "team", "player"],
)
def test_history_endpoint_fetches_only_the_requested_page(path, upstream, fixture, router, prefix, http_response):
    app = FastAPI()
    app.include_router(router, prefix=prefix)
    app.dependency_overrides[deps.get_redis_client] = lambda: None
    response = http_response(upstream, (FIXTURE_DIR / fixture).read_bytes())

    with patch("httpx2.AsyncClient.get", return_value=response) as get, TestClient(app) as client:
        result = client.get(path, params={"page": 2})
        assert result.status_code == 200
        history = result.json()
        assert len(history) == 50
        assert len({match["id"] for match in history}) == 50
        assert all(match["status"] == "completed" for match in history)
        assert all(match.get("date", match.get("time")) for match in history)
        get.assert_called_once_with(upstream)

        get.reset_mock()
        for invalid in (0, 51):
            assert client.get(path, params={"page": invalid}).status_code == 422
        get.assert_not_called()

        get.return_value = http_response(upstream, b"<html><body></body></html>")
        assert client.get(path, params={"page": 2}).json() == []

        get.return_value = http_response(upstream, b"", status=503)
        assert client.get(path, params={"page": 2}).status_code == 500
