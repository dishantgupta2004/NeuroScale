"""
Custom exception hierarchy.

Every business-logic exception inherits from AppException, which carries an
HTTP status code. The FastAPI exception handler in main.py translates these
to clean JSON responses without leaking stack traces.
"""
from __future__ import annotations


class AppException(Exception):
    """Base for all application-defined exceptions."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class NotFoundError(AppException):
    status_code = 404
    code = "not_found"


class UnauthorizedError(AppException):
    status_code = 401
    code = "unauthorized"


class ForbiddenError(AppException):
    status_code = 403
    code = "forbidden"


class ValidationError(AppException):
    status_code = 400
    code = "validation_error"


class ConflictError(AppException):
    status_code = 409
    code = "conflict"


class UpstreamError(AppException):
    """An upstream dependency (LLM, S3, SES) failed."""
    status_code = 502
    code = "upstream_error"