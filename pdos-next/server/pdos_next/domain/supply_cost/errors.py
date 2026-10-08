"""Stable integration errors. No database, HTTP or model error-path calls."""


class SupplyBusinessError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def unconnected(name: str):
    raise SupplyBusinessError("PORT_UNCONNECTED", f"{name} is pending mainline integration")
