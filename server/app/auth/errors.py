"""Domain errors mapped to stable authentication API responses."""


class SetupAlreadyCompletedError(RuntimeError):
    """Raised when the one-time bootstrap endpoint has already been consumed."""


class InvalidCredentialsError(RuntimeError):
    """Raised without revealing which credential component was invalid."""


class InvalidAccessTokenError(RuntimeError):
    """Raised when an access token is missing, malformed, expired, or untrusted."""


class TenantContextDeniedError(RuntimeError):
    """Raised when a valid identity has no active server-side tenant context."""
