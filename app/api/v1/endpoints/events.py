from fastapi import APIRouter

from app import cache, schemas
from app.api import deps
from app.services import events

router = APIRouter()


@router.get("/")
async def list_events(client: deps.RedisDep) -> list[schemas.Event]:
    if data := await cache.get("events", client=client):
        return schemas.EventListAdapter.validate_json(data)
    return await events.get_events(client)


@router.get("/{id}")
async def event_by_id(id: str, client: deps.RedisDep) -> schemas.EventWithDetails:
    return await events.get_event_by_id(id, client)


@router.get("/{id}/matches")
async def event_matches(id: str) -> list[schemas.EventMatch]:
    return [schemas.EventMatch.model_validate(match) for match in await events.parse_match_data(id)]
