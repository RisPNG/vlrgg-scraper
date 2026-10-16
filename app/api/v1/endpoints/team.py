from typing import Annotated

from fastapi import APIRouter, Query

from app import constants, schemas
from app.services import team

router = APIRouter()


@router.get("/{team_id}", response_model=schemas.Team)
async def get_team_by_id(
    team_id: str,
    completed_pages: Annotated[int, Query(description="Completed history pages; <= 0 fetches all.")] = 1,
    include_completed: bool = True,
) -> schemas.Team:
    return await team.get_team_data(team_id, completed_pages=completed_pages, include_completed=include_completed)


@router.get("/{team_id}/matches")
async def get_team_matches_page(
    team_id: str,
    page: Annotated[int, Query(ge=1, le=constants.MAX_PAGINATION_PAGES)] = 1,
) -> list[schemas.CompletedMatch]:
    return await team.get_team_matches_page(team_id, page)
