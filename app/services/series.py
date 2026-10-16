import http
import re

from bs4 import BeautifulSoup

from app import constants, schemas, utils
from app.core.connections import get_http_client
from app.exceptions import ScrapingError


async def get_series_by_id(id: str) -> schemas.Series:
    async with get_http_client() as client:
        response = await client.get(constants.SERIES_URL.format(id))
        if response.status_code != http.HTTPStatus.OK:
            raise ScrapingError(url=str(response.url), upstream_status=response.status_code)

    soup = BeautifulSoup(response.content, "lxml")
    title = soup.find("div", class_="wf-title")
    if title is None:
        raise ScrapingError(url=str(response.url))

    events = []
    seen = set()
    for event in soup.select("a.event-item[href]"):
        href = utils.get_href(event["href"])
        if (match := re.match(r"/event/([0-9]+)(?:/|$)", href)) is None or match[1] in seen:
            continue
        event_title = event.find("div", class_="event-item-title")
        if event_title is None:
            raise ScrapingError(url=str(response.url))
        seen.add(match[1])
        status = event.find("span", class_="event-item-desc-item-status")
        events.append(
            schemas.SeriesEvent.model_validate(
                {
                    "id": match[1],
                    "name": utils.clean_string(event_title.get_text()),
                    "url": utils.expand_url(href),
                    "status": utils.clean_string(status.get_text()).lower() if status is not None else None,
                }
            )
        )
    return schemas.Series(id=id, name=utils.clean_string(title.get_text()), events=events)
