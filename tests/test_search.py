from unittest.mock import patch

import httpx2
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.search import router


def test_search_preserves_punctuation_and_the_public_result_contract():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/search")
    requested = []

    def respond(request):
        requested.append(request)
        return httpx2.Response(
            200,
            text="""<a class="search-item" href="/team/624/paper-rex">
                <img src="//owcdn.net/img/team.png">
                <div class="search-item-title">Paper Rex</div>
                <div class="search-item-desc">Singapore</div>
            </a>""",
            request=request,
        )

    with (
        patch("app.core.connections.build_transport", return_value=httpx2.MockTransport(respond)),
        TestClient(app) as client,
    ):
        response = client.get("/api/v1/search/", params={"search_category": "teams", "search_term": "A&B + Academy"})

    assert response.status_code == 200
    assert response.json()[0] == {
        "id": "624",
        "name": "Paper Rex",
        "img": "https://owcdn.net/img/team.png",
        "category": "teams",
        "category_label": "Teams",
        "description": "Singapore",
    }
    assert len(requested) == 1
    assert dict(requested[0].url.params) == {"q": "A&B + Academy", "type": "teams"}
