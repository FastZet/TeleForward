
"""
TeleForward ORM model registry.

Import all database models here so SQLAlchemy registers their
tables with Base.metadata.

Keep this module as the central import point for ORM models.
"""

from app.database.base import Base

from app.models.user import User
from app.models.telegram_account import TelegramAccount
from app.models.chat import TelegramChat
from app.models.forwarding_rule import ForwardingRule
from app.models.filter_rule import FilterRule
from app.models.message import Message
from app.models.forwarded_message import ForwardedMessage
from app.models.scheduled_task import ScheduledTask
from app.models.backfill_job import BackfillJob
from app.models.processing_queue import ProcessingQueue
from app.models.application_setting import ApplicationSetting
from app.models.audit_log import AuditLog
from app.models.notification import Notification, NotificationDelivery


__all__ = [
    "Base",
    "User",
    "TelegramAccount",
    "TelegramChat",
    "ForwardingRule",
    "FilterRule",
    "Message",
    "ForwardedMessage",
    "ScheduledTask",
    "BackfillJob",
    "ProcessingQueue",
    "ApplicationSetting",
    "AuditLog",
    "Notification",
    "NotificationDelivery",
]
