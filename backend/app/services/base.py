"""
Base abstractions for the TeleForward service layer.

Services encapsulate business logic and domain operations. Transaction
boundaries are managed by the application layer rather than individual
service methods.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession


class BaseService:
    """
    Common base class for database-backed services.

    Attributes:
        session: The asynchronous SQLAlchemy session used by the service.
        logger: Module-specific logger for service diagnostics.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = logging.getLogger(
            f"{self.__class__.__module__}.{self.__class__.__name__}"
        )
