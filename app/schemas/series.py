from pydantic import BaseModel, HttpUrl

from app.constants import EventStatus


class SeriesEvent(BaseModel):
    id: str
    name: str
    url: HttpUrl
    status: EventStatus | None = None


class Series(BaseModel):
    id: str
    name: str
    events: list[SeriesEvent]
