import asyncio
import itertools
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta, timezone, tzinfo
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import dateutil.parser
import httpx2
from bs4 import BeautifulSoup
from redis.asyncio import ConnectionPool

from app.constants import PREFIX, REQUEST_TIMEOUT
from app.core.config import settings
from app.exceptions import ScrapingError
from app.utils import parse_match_datetime

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from app.services.apns import APNsClient

redis_pool: ConnectionPool | None = None
http_client: httpx2.AsyncClient | None = None
apns_client: APNsClient | None = None
database_engine: AsyncEngine | None = None
subscription_sessions: async_sessionmaker[AsyncSession] | None = None
_user_agents = itertools.cycle(settings.USER_AGENTS)


async def rotate_user_agent(request: httpx2.Request) -> None:
    """Set the next configured user agent on an outgoing request.

    :param request: Outgoing HTTP request.
    :return: None.
    """
    request.headers["User-Agent"] = next(_user_agents)


class VLRRequestPacer:
    """Space VLR request starts across one shared client and its event loop."""

    def __init__(self, interval: float) -> None:
        self._interval = interval
        self._lock = asyncio.Lock()
        self._next_request_at = 0.0

    async def __call__(self, request: httpx2.Request) -> None:
        """Wait for the next VLR request slot before sending the request."""
        if not self._interval or request.url.host not in {"vlr.gg", "www.vlr.gg"}:
            return
        loop = asyncio.get_running_loop()
        async with self._lock:
            delay = self._next_request_at - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)
            self._next_request_at = loop.time() + self._interval


class VLRSourceTimezone:
    """Calibrate rendered wall clocks once for the lifetime of an HTTP client."""

    def __init__(self) -> None:
        self.client: httpx2.AsyncClient | None = None
        self.zone: tzinfo | None = None
        self._lock = asyncio.Lock()

    async def __call__(self, response: httpx2.Response) -> None:
        if (
            not settings.DETECT_SOURCE_TIMEZONE
            or response.request.url.host not in {"vlr.gg", "www.vlr.gg"}
            or response.status_code != 200
            or "html" not in response.headers.get("content-type", "text/html").lower()
        ):
            return
        if self.zone is not None:
            response.extensions["vlr_timezone"] = self.zone
            return
        await response.aread()
        soup = BeautifulSoup(response.content, "lxml")
        timing = soup.select(".match-header-date .moment-tz-convert")
        visible = " ".join(node.get_text(" ", strip=True) for node in timing)
        timestamp = next((node.get("data-utc-ts") for node in timing if node.get("data-utc-ts")), None)
        if self.zone is None and timestamp and "tbd" not in visible.casefold():
            clock = re.search(r"\d{1,2}:\d{2}\s*(?:AM|PM)\s+([A-Z]{2,5}|[+-]\d{2}(?::?\d{2})?)\b", visible)
            if clock and (instant := parse_match_datetime("", str(timestamp))) is not None:
                rendered = dateutil.parser.parse(visible, default=instant.replace(tzinfo=None), ignoretz=True)
                offset = rendered - instant.replace(tzinfo=None)
                if offset > timedelta(days=180):
                    rendered = rendered.replace(year=rendered.year - 1)
                elif offset < -timedelta(days=180):
                    rendered = rendered.replace(year=rendered.year + 1)
                offset = rendered - instant.replace(tzinfo=None)
                suffix = clock[1]
                zones = {
                    "EST": ("America/New_York",),
                    "EDT": ("America/New_York",),
                    "CST": ("America/Chicago", "Asia/Shanghai"),
                    "CDT": ("America/Chicago",),
                    "MST": ("America/Denver", "America/Phoenix"),
                    "MDT": ("America/Denver",),
                    "PST": ("America/Los_Angeles", "Asia/Manila"),
                    "PDT": ("America/Los_Angeles",),
                    "GMT": ("Europe/London",),
                    "BST": ("Europe/London", "Asia/Dhaka"),
                    "CET": ("Europe/Paris",),
                    "CEST": ("Europe/Paris",),
                    "EET": ("Europe/Helsinki",),
                    "EEST": ("Europe/Helsinki",),
                    "IST": ("Asia/Kolkata", "Asia/Jerusalem", "Europe/Dublin"),
                    "JST": ("Asia/Tokyo",),
                    "KST": ("Asia/Seoul",),
                    "SGT": ("Asia/Singapore",),
                    "HKT": ("Asia/Hong_Kong",),
                    "AEST": ("Australia/Sydney", "Australia/Brisbane"),
                    "AEDT": ("Australia/Sydney",),
                    "NZST": ("Pacific/Auckland",),
                    "NZDT": ("Pacific/Auckland",),
                    "UTC": ("UTC",),
                }
                candidates = [ZoneInfo(settings.TIMEZONE), *(ZoneInfo(name) for name in zones.get(suffix, ()))]
                matching = {
                    zone.key: zone
                    for zone in candidates
                    if instant.astimezone(zone).utcoffset() == offset and instant.astimezone(zone).tzname() == suffix
                }
                if settings.TIMEZONE in matching:
                    self.zone = matching[settings.TIMEZONE]
                elif len(matching) == 1:
                    self.zone = next(iter(matching.values()))
                if self.zone is None and (numeric := re.fullmatch(r"([+-])(\d{2})(?::?(\d{2}))?", suffix)):
                    explicit = timedelta(hours=int(numeric[2]), minutes=int(numeric[3] or 0))
                    if numeric[1] == "-":
                        explicit = -explicit
                    if offset == explicit and abs(offset) <= timedelta(hours=14):
                        self.zone = timezone(offset, suffix)
        if timing:
            if self.zone is not None:
                response.extensions["vlr_timezone"] = self.zone
            return
        cards = soup.select("a.match-item, a.m-item")
        anchor = next(
            (
                card.get("href")
                for card in cards
                if card.select_one("[data-utc-ts]") is None
                and (date := card.select_one(".m-item-date, .match-item-time")) is not None
                and "tbd" not in date.get_text().casefold()
                and re.search(r"\d{1,2}:\d{2}", date.get_text())
            ),
            None,
        )
        if anchor and self.zone is None:
            async with self._lock:
                if self.zone is None:
                    if self.client is None:
                        raise ScrapingError("Unable to determine VLR's rendered timezone", url=str(response.url))
                    detail = await self.client.get(f"{PREFIX}/{str(anchor).lstrip('/')}")
                    if detail.status_code != 200 or self.zone is None:
                        raise ScrapingError("Unable to determine VLR's rendered timezone", url=str(response.url))
        if self.zone is not None:
            response.extensions["vlr_timezone"] = self.zone


class RotatingAddressTransport(httpx2.AsyncBaseTransport):
    """Rotate one request at a time across the configured local addresses.

    Direct callers may pass an empty list to leave requests unbound and let the
    kernel pick the source. build_transport() returns None for empty settings so
    httpx retains its default transport and environment-proxy discovery.
    """

    def __init__(self, addresses: list[str]) -> None:
        self._transports = [httpx2.AsyncHTTPTransport(local_address=address) for address in addresses] or [
            httpx2.AsyncHTTPTransport()
        ]
        self._cycle = itertools.cycle(self._transports)

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        """Send a request using the next address in round-robin order.

        :param request: Outgoing HTTP request.
        :return: HTTP response from the selected transport.
        """
        return await next(self._cycle).handle_async_request(request)

    async def aclose(self) -> None:
        """Close each underlying transport."""
        for transport in self._transports:
            await transport.aclose()


def build_transport() -> httpx2.AsyncBaseTransport | None:
    """Build the HTTP transport for the configured local addresses.

    :return: A rotating transport, or None for httpx's default and proxy discovery.
    """
    addresses = settings.HTTP_LOCAL_ADDRESSES
    return RotatingAddressTransport(addresses) if addresses else None


@asynccontextmanager
async def get_http_client() -> AsyncIterator[httpx2.AsyncClient]:
    """Yield the shared HTTP client, or a temporary one if not initialized (e.g. tests)."""
    if http_client is not None:
        yield http_client
    else:
        pace_requests = VLRRequestPacer(settings.VLR_REQUEST_INTERVAL_SECONDS)
        source_timezone = VLRSourceTimezone()
        async with httpx2.AsyncClient(
            transport=build_transport(),
            timeout=REQUEST_TIMEOUT,
            headers={},
            event_hooks={"request": [pace_requests, rotate_user_agent], "response": [source_timezone]},
        ) as client:
            source_timezone.client = client
            try:
                yield client
            finally:
                source_timezone.client = None
