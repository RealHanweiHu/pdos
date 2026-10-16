"""Fixed MCP graph entry points; endpoints, credentials and authority are host facts."""

import json
from uuid import UUID

from pydantic import Field, ValidationError, model_validator

from pdos_next.errors import DomainError
from pdos_next.schema_base import StrictModel


def parse_input(schema, arguments):
    try:
        return schema.model_validate(arguments)
    except ValidationError:
        raise DomainError("VALIDATION_FAILED", "MCP 参数与登记的入口结构不一致。", 422) from None


class McpListInput(StrictModel):
    connector_id: UUID | None = None
    cursor: UUID | None = None
    page_size: int = Field(default=30, ge=1, le=100, strict=True)


class McpReadInput(StrictModel):
    connector_id: UUID
    tool: str = Field(min_length=1, max_length=160)
    arguments_json: str = Field(min_length=2, max_length=200_000)

    @model_validator(mode="after")
    def object_arguments(self):
        value = json.loads(self.arguments_json)
        if not isinstance(value, dict):
            raise ValueError("MCP arguments must be a JSON object")
        return self

    @property
    def arguments(self):
        return json.loads(self.arguments_json)


class McpResultInput(StrictModel):
    cursor: int = Field(default=0, ge=0, strict=True)
    page_chars: int = Field(default=16_000, ge=1, le=20_000, strict=True)


class McpRow(StrictModel):
    text: str = Field(min_length=1, max_length=4000)
    quote: str = Field(min_length=1, max_length=2000)
    start: int = Field(ge=0, strict=True)
    end: int = Field(gt=0, strict=True)


SCHEMAS = {
    "mcp.tools.list": McpListInput,
    "mcp.read": McpReadInput,
    "mcp.result.read": McpResultInput,
}
