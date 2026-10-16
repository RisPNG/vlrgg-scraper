from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl, computed_field

from app import i18n
from app.constants import MatchStatus


class Player(BaseModel):
    id: str
    name: str | None = None
    alias: str
    role: str | None = None
    img: HttpUrl


class MatchBase(BaseModel):
    id: str
    event: str
    stage: str
    opponent: str
    opponent_tag: str | None = None
    date: datetime | None = Field(default=None, description="Match start in UTC, or null when unannounced")
    roster_core: str | None = None
    opponent_roster_core: str | None = None
    best_of: int | None = Field(default=None, ge=1, description="Scheduled best-of format, when VLR provides it")


class UpcomingMatch(MatchBase):
    status: MatchStatus = MatchStatus.UPCOMING
    eta: str | None = None


class CompletedMatch(MatchBase):
    status: MatchStatus = MatchStatus.COMPLETED
    score: str


# Response for `GET /api/v1/team/{id}`
class Team(BaseModel):
    name: str
    tag: str
    img: HttpUrl
    website: HttpUrl | None = None
    twitter: str | None = None
    country: str
    rank: int
    region: str
    roster: list[Player]
    upcoming: list[UpcomingMatch]
    completed: list[CompletedMatch]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def region_label(self) -> str:
        return i18n.label("region", self.region) if self.region else ""
