from typing import Annotated

from fastapi import APIRouter, Query

from app import cache, constants, schemas
from app.api import deps
from app.services import matches

router = APIRouter()


@router.get("/")
async def get_matches(
    client: deps.RedisDep,
    completed_pages: Annotated[int, Query(description="Completed history pages; <= 0 fetches all.")] = 1,
    include_completed: bool = True,
) -> list[schemas.Match]:
    if include_completed and completed_pages == 1 and (data := await cache.get("matches", client=client)):
        return schemas.MatchListAdapter.validate_json(data)
    return await matches.match_list(
        redis_client=client, completed_pages=completed_pages, include_completed=include_completed
    )


@router.get("/completed")
async def get_completed_matches_page(
    client: deps.RedisDep,
    page: Annotated[int, Query(ge=1, le=constants.MAX_PAGINATION_PAGES)] = 1,
) -> list[schemas.Match]:
    return await matches.get_completed_matches_page(client, page)


@router.get("/{id}")
async def get_match_by_id(id: str, client: deps.RedisDep) -> schemas.MatchWithDetails:
    cache_key = f"match:{id}"
    if data := await cache.get(cache_key, client=client):
        return schemas.MatchWithDetails.model_validate_json(data)
    result = await matches.match_by_id(id, client)
    await cache.set(cache_key, result.model_dump_json(), ttl=constants.CACHE_TTL_MATCH, client=client)
    return result
