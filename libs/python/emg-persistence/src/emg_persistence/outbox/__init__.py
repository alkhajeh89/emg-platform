"""Transactional outbox model and repository contract."""

from .model import OutboxEvent
from .repository import OutboxRepository

__all__ = ["OutboxEvent", "OutboxRepository"]
