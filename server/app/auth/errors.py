"""Domain errors mapped to stable authentication API responses."""


class SetupAlreadyCompletedError(RuntimeError):
    """Raised when the one-time bootstrap endpoint has already been consumed."""


class InvalidCredentialsError(RuntimeError):
    """Raised without revealing which credential component was invalid."""


class InvalidCurrentPasswordError(RuntimeError):
    """Raised when a signed-in user cannot prove the current local credential."""


class LocalPasswordUnavailableError(RuntimeError):
    """Raised when an externally provisioned account has no local credential."""


class PasswordReuseError(RuntimeError):
    """Raised when a password change attempts to retain the current credential."""


class InvalidAccessTokenError(RuntimeError):
    """Raised when an access token is missing, malformed, expired, or untrusted."""


class TenantContextDeniedError(RuntimeError):
    """Raised when a valid identity has no active server-side tenant context."""


class ObjectPermissionDeniedError(RuntimeError):
    """Raised when a tenant-bound identity cannot perform an object action."""
