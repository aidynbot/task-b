"""Domain exceptions mapped to client-facing HTTP errors by the API layer."""


class DomainError(Exception):
    """Base exception carrying a safe message for API clients."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class EntityNotFoundError(DomainError):
    """Raised when a requested company, manager, or meeting does not exist."""


class SlotConflictError(DomainError):
    """Raised when an active meeting conflicts with a requested booking."""


class BusinessRuleError(DomainError):
    """Raised when a request violates a CRM business rule."""
