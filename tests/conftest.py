import asyncio
import os
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from importlib.util import find_spec
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.exceptions import ScrapingError
from tests.live_upstream import UPSTREAM_NETWORK_ERRORS, is_upstream_outage

LIVE_MARKERS = ("live_golden", "live_health")
OPTIONAL_TEST_DEPENDENCIES = {
    "test_agent_runner.py": ("openai",),
    "test_ask_endpoint.py": ("openai",),
    "test_cron.py": ("sqlalchemy", "firebase_admin", "jwt"),
    "test_favorites.py": ("sqlalchemy",),
    "test_team_rankings.py": ("sqlalchemy",),
    "test_video_round_history.py": ("sqlalchemy", "firebase_admin", "jwt"),
}


@pytest.fixture(autouse=True)
def fixture_source_timezone(request, monkeypatch):
    """Offline HTML fixtures have a fixed source zone unless a test enables live calibration."""
    if not any(marker in request.keywords for marker in LIVE_MARKERS):
        monkeypatch.setattr("app.core.config.settings.DETECT_SOURCE_TIMEZONE", False)


def pytest_ignore_collect(collection_path):
    return any(find_spec(dependency) is None for dependency in OPTIONAL_TEST_DEPENDENCIES.get(collection_path.name, ()))


def _run_admin_sql(database_url: str, statement: str) -> None:
    """Run one statement on the test server's maintenance database.

    :param database_url: Explicitly configured test server's maintenance database.
    :param statement: SQL that cannot run inside a transaction, such as CREATE DATABASE.
    :return: None.
    """

    import asyncpg

    async def run() -> None:
        connection = await asyncpg.connect(database_url)
        try:
            await connection.execute(statement)
        finally:
            await connection.close()

    # A thread of its own, because async tests call this from inside their event loop.
    with ThreadPoolExecutor(1) as pool:
        pool.submit(asyncio.run, run()).result()


@pytest.fixture
def make_database():
    """Create empty scratch PostgreSQL databases, dropped after the test."""
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL tests")
    pytest.importorskip("asyncpg", reason="Install the database extra to run PostgreSQL tests")
    make_url = pytest.importorskip("sqlalchemy.engine").make_url
    maintenance_url = make_url(database_url).set(drivername="postgresql")
    database_url = maintenance_url.render_as_string(hide_password=False)
    names = []

    def create() -> str:
        name = f"vlrgg_test_{uuid4().hex}"
        # template0, because template1 carries whatever the server's admin put in it.
        _run_admin_sql(database_url, f'CREATE DATABASE "{name}" TEMPLATE template0')
        names.append(name)
        return maintenance_url.set(drivername="postgresql+asyncpg", database=name).render_as_string(hide_password=False)

    yield create
    for name in names:
        _run_admin_sql(database_url, f'DROP DATABASE "{name}" WITH (FORCE)')


@pytest.fixture
def http_response():
    """Build the small HTTP response surface used by service tests."""

    def build(url: str, content: bytes, status: int = 200):
        response = AsyncMock()
        response.status_code = status
        response.content = content
        response.url = url
        response.extensions = {}
        return response

    return build


@pytest.fixture
def http_get(http_response):
    """Route mocked HTTP GET calls by URL."""

    def build(pages: dict[str, bytes], fallback: bytes = b"<html><body></body></html>", failures=None):
        failures = failures or {}

        async def get(url: str, *_args, **_kwargs):
            return http_response(url, pages.get(url, fallback), failures.get(url, 200))

        return get

    return build


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    """Turn VLR outages into skips for every live test, in any directory.

    Applied by marker rather than by fixture so that a new live test cannot
    forget to opt in -- the same drift that previously left the daily job
    silently skipping everything.
    """
    outcome = yield
    if not any(marker in item.keywords for marker in LIVE_MARKERS):
        return

    exc = outcome.excinfo[1] if outcome.excinfo else None
    if exc is None:
        return
    if isinstance(exc, ScrapingError) and is_upstream_outage(exc.upstream_status):
        outcome.force_exception(pytest.skip.Exception(f"VLR unreachable: HTTP {exc.upstream_status}"))
    elif isinstance(exc, UPSTREAM_NETWORK_ERRORS):
        outcome.force_exception(pytest.skip.Exception(f"VLR network error: {exc!r}"))


class InlineExecutor(Executor):
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()

    def submit(self, fn, /, *args, **kwargs):
        future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as exc:  # noqa: BLE001 - executors preserve BaseException semantics
            future.set_exception(exc)
        return future


@pytest.fixture(autouse=True)
def use_inline_executor_for_rankings(monkeypatch):
    from app.services import rankings

    monkeypatch.setattr(rankings, "ProcessPoolExecutor", InlineExecutor)
