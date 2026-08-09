"""Bounded failure classes used by the projector hot path."""


class ProjectorError(Exception):
    """Base projector failure."""


class RetryableDeliveryError(ProjectorError):
    """Delivery may be attempted again without changing its immutable input."""


class PermanentDeliveryError(ProjectorError):
    """Delivery cannot succeed without operator remediation."""


class CredentialMismatchError(PermanentDeliveryError):
    """Issued token does not match the configured tenant/client binding."""


class ProjectionError(PermanentDeliveryError):
    """Immutable ledger content cannot be projected without fabrication."""


class ShutdownRequested(RetryableDeliveryError):
    """Shutdown interrupted a multi-intent delivery before acknowledgement."""
