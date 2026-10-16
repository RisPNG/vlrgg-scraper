from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl

from app.constants import MatchStatus


class Agent(BaseModel):
    name: str
    img: HttpUrl
    count: int
    percent: float
    rounds: int
    rating: float
    acs: float
    kd: float
    adr: float
    kast: float
    kpr: float
    apr: float
    fkpr: float
    fdpr: float
    k: int
    d: int
    a: int
    fk: int
    fd: int


class PlayerTeam(BaseModel):
    id: str
    name: str
    img: HttpUrl


# A single match from a player's paginated match history (`/player/matches/{id}`).
class PlayerMatch(BaseModel):
    id: str
    date: datetime | None = Field(default=None, description="Match start in UTC, or null when unannounced")
    event: str
    stage: str
    team: str  # The player's team in that match (first team listed on the card)
    opponent: str
    score: str  # Raw score string, e.g. "0:2"
    roster_core: str | None = None
    opponent_roster_core: str | None = None
    status: MatchStatus = MatchStatus.COMPLETED
    best_of: int | None = Field(default=None, ge=1, description="Scheduled best-of format, when VLR provides it")


# Response for `GET /api/v1/player/{id}`
class Player(BaseModel):
    name: str
    alias: str
    twitch: HttpUrl | None = None
    twitter: str | None = None
    country: str
    img: HttpUrl
    agents: list[Agent]
    total_winnings: float = 0.0
    current_team: PlayerTeam | None = None
    current_teams: list[PlayerTeam] = []
    past_teams: list[PlayerTeam] = []
    matches: list[PlayerMatch] = []
