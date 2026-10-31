"""Domain bounds and bounded model views remain distinct for registered records."""

import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.agent_kernel.context_budget import estimate_tokens
from pdos_next.agent_kernel.result_continuation import handle_for, page_view, serialized
from pdos_next.domain.external_wait.schemas import Create
from pdos_next.enterprise_search.assistant_adapter import structured_quote


def record():
    return {
        "action": "create", "title": "合成登记记录", "target": "合成联系人",
        "request_content": "请" * 4_000, "closure_condition": "结" * 4_000,
        "blocking": True, "next_check_at": None, "original_timezone": "Asia/Shanghai",
        "calendar": None, "milestone": None, "build": None, "replaces": None,
    }


def test_two_legal_domain_fields_keep_full_values_across_bounded_result_fragments():
    data = Create.model_validate(record()).model_dump(mode="json")
    values = {"facts": {"wait": {key: data[key] for key in (
        "title", "request_content", "closure_condition",
    )}}}
    body = json.dumps(values, ensure_ascii=False)
    assert len(body) > 6_000
    quote = structured_quote({"structured": values, "body": body})
    assert quote in body and len(quote) <= 1_000
    result = {"rows": [{"values": values, "quote": quote}]}
    handle = handle_for(uuid4(), result)
    first = page_view(result, handle, 1)
    assert first["total_pages"] > 1
    pages = [page_view(result, handle, index)
             for index in range(1, first["total_pages"] + 1)]
    assert all(estimate_tokens(serialized(page)) <= 4_000 for page in pages)
    assert json.loads("".join(page["preview"] for page in pages)) == result


@pytest.mark.parametrize("field", ["request_content", "closure_condition"])
def test_continuation_never_relaxes_native_field_size_constraints(field):
    data = record()
    data[field] += "越"
    with pytest.raises(ValidationError) as error:
        Create.model_validate(data)
    assert error.value.errors()[0]["loc"] == (field,)
