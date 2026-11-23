"""Domain exceptions. The API layer maps each to an HTTP status (SPEC section 1.3)."""

from __future__ import annotations


class DomainError(Exception):
    code = "INTERNAL_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ValidationFailed(DomainError):
    code = "VALIDATION_ERROR"

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


class NotAuthenticated(DomainError):
    code = "UNAUTHENTICATED"


class Forbidden(DomainError):
    code = "FORBIDDEN"


class NotFound(DomainError):
    code = "NOT_FOUND"


class Conflict(DomainError):
    code = "CONFLICT"


class IllegalTransition(DomainError):
    code = "ILLEGAL_TRANSITION"
