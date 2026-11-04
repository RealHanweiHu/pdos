"""Model tool arguments that pass the tool definition but fail stricter validators (D245).

In W1 these raised a bare pydantic ValidationError that ended the whole run as
INTERNAL_ERROR. They must come back to the model as VALIDATION_FAILED instead.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator
from pydantic import field_validator

import pdos_next.core.models  # noqa: F401  # Load ORM models in the app's import order.
from pdos_next.agent.enterprise_search.assistant_adapter import AssistantReadAdapter
from pdos_next.agent.enterprise_search.assistant_schemas import PassageInput
from pdos_next.agent.kernel.extract_service import ExtractionService
from pdos_next.agent.kernel.platform_reads import PlatformReads
from pdos_next.agent.kernel.tool_arguments import tool_arguments
from pdos_next.agent.kernel.tools import default_registry
from pdos_next.core.schema_base import StrictModel
from pdos_next.errors import DomainError

SCOPE = SimpleNamespace()  # Validation runs before any scope, store or database use.


def passes_definition(tool, arguments):
    schema = default_registry().get(tool).input_schema
    assert not list(Draft202012Validator(schema).iter_errors(arguments))


@pytest.mark.parametrize(
    "tool,call,arguments,expected",
    [
        (
            "evidence.extract",
            lambda args: ExtractionService(None, None, None).extract(SCOPE, args, graph=None),
            {"row_schema": {"kind": "spec_row", "version": "1"}},
            "explicit artifact version list",
        ),
        (
            "platform.read",
            lambda args: PlatformReads(None, None).call(SCOPE, args),
            {"variant_id": str(uuid4())},
            "Select a product for the variant",
        ),
        (
            "assistant.passage.read",
            lambda args: AssistantReadAdapter(None, None).passage(SCOPE, args),
            {"citation_id": "citation-7"},
            None,
        ),
    ],
)
def test_w1_crash_sites_return_a_tool_error(tool, call, arguments, expected):
    passes_definition(tool, arguments)
    with pytest.raises(DomainError) as caught:
        call(arguments)
    error = caught.value
    assert error.code == "VALIDATION_FAILED" and error.status == 422
    assert error.detail["fields"]
    if expected is not None:
        assert any(expected in field.get("message", "") for field in error.detail["fields"])


class Echoing(StrictModel):
    name: str
    size: int

    @field_validator("name")
    @classmethod
    def plain(cls, value):
        raise ValueError(f"name {value} is not allowed")


def test_fields_list_path_and_type_without_echoing_submitted_text():
    with pytest.raises(DomainError) as caught:
        tool_arguments(Echoing, {"name": "PRIVATE_SECRET", "size": "PRIVATE_SIZE"})
    fields = {field["path"]: field for field in caught.value.detail["fields"]}
    assert fields["name"]["type"] == "value_error" and "message" not in fields["name"]
    assert fields["size"]["type"] == "int_parsing" and "message" in fields["size"]
    assert "PRIVATE_" not in str(caught.value.payload())


def test_valid_arguments_return_the_model():
    value = tool_arguments(PassageInput, {"citation_id": str(uuid4()), "cursor": 3})
    assert value.cursor == 3 and value.page_chars == 1600
