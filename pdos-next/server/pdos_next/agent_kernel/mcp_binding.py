"""A connector's admitted target and tool contracts define the grant identity."""

import hashlib
import json

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError
from referencing import Registry
from referencing.exceptions import Unresolvable

from pdos_next.errors import DomainError


def connector_binding(connector, tool=None):
    body = {key: getattr(connector, key) for key in ("key", "endpoint", "secret_ref")}
    if tool is not None:
        body.update(tool=tool, contract=connector.tools.get(tool))
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def check_schema(schema):
    if schema.get("type") != "object":
        raise ValueError("工具参数和结构化结果须使用 object 类型的 JSON Schema。")
    if len(json.dumps(schema, ensure_ascii=False).encode()) > 200_000:
        raise ValueError("单份工具结构超出请求大小，请收窄工具接口。")
    stack = [schema]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            for key in ("$ref", "$dynamicRef", "$recursiveRef"):
                if key in value and (
                    not isinstance(value[key], str) or not value[key].startswith("#")
                ):
                    raise ValueError("工具结构引用须包含在同一份登记中，不读取外部地址。")
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError:
        raise ValueError("工具 JSON Schema 结构无效。") from None
    return schema


def validate_arguments(spec, arguments):
    schema = spec.get("input_schema")
    if not isinstance(schema, dict):
        raise DomainError("SOURCE_UNAVAILABLE", "MCP 工具参数结构尚未登记。")
    try:
        # An empty registry has no network retriever, including for nested references.
        Draft202012Validator(schema, registry=Registry()).validate(arguments)
    except (ValidationError, Unresolvable, RecursionError):
        raise DomainError("VALIDATION_FAILED", "MCP 参数与已登记工具结构不一致。", 422) from None
