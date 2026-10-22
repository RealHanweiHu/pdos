import logging

from pdos_next.error_catalog import REASONS


class DomainError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status: int = 409,
        *,
        detail: dict | None = None,
        recovery: dict | None = None,
    ):
        self.reason = code
        self.code = REASONS.get(code, "INTERNAL_ERROR")
        if code not in REASONS:
            logging.getLogger(__name__).error("Unregistered domain reason: %r", code)
            self.reason, message, status = "UNREGISTERED_REASON", "内部条件尚未核对，请重试。", 500
        self.message = message
        self.status = (401 if status == 401 else 403) if self.code == "FORBIDDEN_SCOPE" else status
        if self.code == "INTERNAL_ERROR" and self.status < 500:
            self.status = 500
        if self.code == "RATE_LIMITED":
            self.status = 429
        self.detail = {**(detail or {}), "reason": self.reason}
        self.recovery = recovery
        super().__init__(message)

    def payload(self):
        result = {"code": self.code, "message": self.message, "detail": self.detail}
        if self.recovery is not None:
            result["recovery"] = self.recovery
        return result
