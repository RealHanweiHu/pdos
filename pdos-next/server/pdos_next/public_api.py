"""One public failure envelope, including HTTP routing and unexpected failures."""

from fastapi import Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from pdos_next.error_catalog import CATEGORIES


def install(app):
    @app.exception_handler(HTTPException)
    async def http_failure(_request: Request, error: HTTPException):
        code = {
            401: "FORBIDDEN_SCOPE",
            403: "FORBIDDEN_SCOPE",
            404: "NOT_FOUND",
            405: "VALIDATION_FAILED",
            413: "VALIDATION_FAILED",
            415: "VALIDATION_FAILED",
            429: "RATE_LIMITED",
            503: "SOURCE_UNAVAILABLE",
        }.get(error.status_code, "INTERNAL_ERROR")
        return JSONResponse(
            status_code=error.status_code,
            headers=error.headers,
            content={
                "code": code,
                "message": "此请求当前无法办理。",
                "detail": {"reason": f"HTTP_{error.status_code}"},
            },
        )

    @app.exception_handler(Exception)
    async def unexpected_failure(_request: Request, _error: Exception):
        # SQL parameters, provider credentials and source content never enter the
        # HTTP failure or a generic exception log. Specific owners retain safe diagnostics.
        return JSONResponse(
            status_code=500,
            content={
                "code": "INTERNAL_ERROR",
                "message": "内部条件尚未核对，请重试。",
                "detail": {"reason": "UNEXPECTED_FAILURE"},
            },
        )

    def openapi():
        if app.openapi_schema is None:
            schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
            schema.setdefault("components", {}).setdefault("schemas", {})["PDOSFailure"] = {
                "type": "object",
                "required": ["code", "message", "detail"],
                "properties": {
                    "code": {"type": "string", "enum": sorted(CATEGORIES)},
                    "message": {"type": "string"},
                    "detail": {
                        "type": "object",
                        "required": ["reason"],
                        "properties": {"reason": {"type": "string"}},
                        "additionalProperties": True,
                    },
                    "recovery": {"type": "object", "additionalProperties": True},
                },
            }
            for path in schema["paths"].values():
                for operation in path.values():
                    if not isinstance(operation, dict) or "responses" not in operation:
                        continue
                    for status in (401, 403, 404, 405, 409, 422, 429, 500, 503):
                        operation["responses"][str(status)] = {
                            "description": "统一错误码与具体原因",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/PDOSFailure"}
                                }
                            },
                        }
            app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = openapi
