import time
from typing import Annotated

from fastapi import APIRouter, Query

from app import cache, constants, schemas
from app.api import deps
from app.core.config import settings
from app.services import matches

router = APIRouter()


@router.get("/")
async def get_matches(
    client: deps.RedisDep,
    completed_pages: Annotated[int, Query(description="Completed history pages; <= 0 fetches all.")] = 1,
    include_completed: bool = True,
) -> list[schemas.ListedMatch]:
    if include_completed and completed_pages == 1 and (data := await cache.get("matches", client=client)):
        listed = schemas.MatchListAdapter.validate_json(data)
    else:
        listed = await matches.match_list(
            redis_client=client, completed_pages=completed_pages, include_completed=include_completed
        )
    return await matches.with_broadcast_map(listed, client)


@router.get("/completed")
async def get_completed_matches_page(
    client: deps.RedisDep,
    page: Annotated[int, Query(ge=1, le=constants.MAX_PAGINATION_PAGES)] = 1,
) -> list[schemas.Match]:
    return await matches.get_completed_matches_page(client, page)


@router.get("/{id}")
async def get_match_by_id(id: deps.MatchId, client: deps.RedisDep) -> schemas.MatchDetailsResponse:
    deadline = time.monotonic() + settings.INSIGHTS_REQUEST_BUDGET_SECONDS
    details = await matches.cached_match_by_id(id, client)
    if settings.ENABLE_DATABASE:
        from app.services import insights

        return await insights.attach(id, details, deadline)
    return schemas.MatchDetailsResponse(**dict(details))
