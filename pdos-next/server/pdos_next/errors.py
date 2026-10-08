class DomainError(Exception):
    def __init__(self, code: str, message: str, status: int = 409, *, recovery: dict | None = None):
        self.code = code
        self.message = message
        self.status = status
        self.recovery = recovery
        super().__init__(message)
