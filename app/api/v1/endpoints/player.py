from typing import Annotated

from fastapi import APIRouter, Query

from app import constants, schemas
from app.services import player

router = APIRouter()


@router.get("/{player_id}")
async def get_player_by_id(
    player_id: str,
    match_pages: Annotated[
        int,
        Query(description="Pages of match history to include (50 per page); <= 0 fetches all."),
    ] = 1,
    include_matches: bool = True,
) -> schemas.Player:
    return await player.get_player_data(player_id, match_pages=match_pages, include_matches=include_matches)


@router.get("/{player_id}/matches")
async def get_player_matches_page(
    player_id: str,
    page: Annotated[int, Query(ge=1, le=constants.MAX_PAGINATION_PAGES)] = 1,
) -> list[schemas.PlayerMatch]:
    return await player.get_player_matches_page(player_id, page)
