from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import constants
from app.api.v1.endpoints.series import router
from app.exceptions import ScrapingError
from app.services import series

FIXTURE = Path(__file__).parent / "fixtures" / "series_86.html"


def test_series_endpoint_discovers_unique_events_with_clean_names(http_response):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/series")
    response = http_response(constants.SERIES_URL.format("86"), FIXTURE.read_bytes())

    with patch("httpx2.AsyncClient.get", return_value=response) as get, TestClient(app) as client:
        result = client.get("/api/v1/series/86")

    assert result.status_code == 200
    assert result.json() == {
        "id": "86",
        "name": "Valorant Champions Tour 2026",
        "events": [
            {
                "id": "2766",
                "name": "Valorant Champions 2026",
                "url": "https://www.vlr.gg/event/2766/valorant-champions-2026",
                "status": "completed",
            },
            {
                "id": "2977",
                "name": "VCT 2026: Americas Stage 2",
                "url": "https://www.vlr.gg/event/2977/vct-2026-americas-stage-2",
                "status": None,
            },
        ],
    }
    get.assert_called_once_with(constants.SERIES_URL.format("86"))


@pytest.mark.asyncio
async def test_series_upstream_error_is_not_an_empty_event_list(http_response):
    url = constants.SERIES_URL.format("86")
    with (
        patch("httpx2.AsyncClient.get", return_value=http_response(url, b"", status=503)),
        pytest.raises(ScrapingError),
    ):
        await series.get_series_by_id("86")
