from fastapi import APIRouter

from app import schemas
from app.services import series

router = APIRouter()


@router.get("/{id}")
async def get_series_by_id(id: str) -> schemas.Series:
    return await series.get_series_by_id(id)
