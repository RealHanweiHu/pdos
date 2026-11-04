"""Model-supplied tool arguments: an invalid shape is a tool error the model can fix."""

from pydantic import ValidationError

from pdos_next.errors import DomainError

MESSAGE = "工具参数不符合要求，请按工具定义修正。"


def tool_arguments(schema, arguments, *, message=MESSAGE):
    """Validate the arguments a model sent to a tool.

    Tool definitions come from these same schemas, but cross-field validators
    cannot be expressed in JSON Schema, so arguments can pass the definition and
    still fail here. That is a tool rejection returned to the model, not a worker
    failure that ends the run. Each failing field gives its path and error type;
    a validator's message is added only when it repeats none of the submitted text.
    """
    try:
        return schema.model_validate(arguments)
    except ValidationError as error:
        submitted = _strings(arguments)
        fields = []
        for item in error.errors(include_input=False, include_url=False):
            field = {"path": ".".join(str(part) for part in item["loc"]), "type": item["type"]}
            if not any(text in item["msg"] for text in submitted):
                field["message"] = item["msg"]
            fields.append(field)
        raise DomainError("VALIDATION_FAILED", message, 422, detail={"fields": fields}) from error


def _strings(value):
    """Submitted text values long enough to matter if echoed back.

    Keys are left out: they are field names, and the path already shows them.
    """
    if isinstance(value, dict):
        return {text for item in value.values() for text in _strings(item)}
    if isinstance(value, list | tuple):
        return {text for item in value for text in _strings(item)}
    text = value if isinstance(value, str) else None
    return {text} if text is not None and len(text) >= 4 else set()
