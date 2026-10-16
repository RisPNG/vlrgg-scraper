"""Request transactions for the optional persistence-backed APIs."""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import connections
from app.exceptions import ServiceUnavailableError
from app.services.subscription_store import SubscriptionStore


async def get_subscription_session() -> AsyncGenerator[AsyncSession]:
    """Commit a request transaction before sending its response.

    :return: Request-scoped session.
    :raises ServiceUnavailableError: If the store is absent or fails.
    """
    sessions = connections.subscription_sessions
    if sessions is None:
        raise ServiceUnavailableError("Database is unavailable")
    try:
        async with sessions.begin() as session:
            yield session
    except SQLAlchemyError as exc:
        raise ServiceUnavailableError("Subscription store is unavailable") from exc


DatabaseSessionDep = Annotated[AsyncSession, Depends(get_subscription_session, scope="function")]


def get_subscription_store(session: DatabaseSessionDep) -> SubscriptionStore:
    """Bind the request transaction to the subscription store.

    :param session: Request-scoped database session.
    :return: Subscription store.
    """
    return SubscriptionStore(session)


SubscriptionStoreDep = Annotated[SubscriptionStore, Depends(get_subscription_store)]
