"""Real ordinary read binding/restoration; no model provider is invoked."""

from copy import deepcopy
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.domain.products.platform_schemas import PlatformLinkInput, PlatformReadInput
from pdos_next.errors import DomainError
from pdos_next.models import Grant, now
from tests.agent_kernel.test_m3_definition_diff_pg import invoke, reader
from tests.products.test_definition_item_commands_pg import confirmed
from tests.products.test_platform_links_pg import request
from tests.products.test_variants_transactions import definition, derive, source


def test_ordinary_host_restore_rechecks_platform_versions_and_permission(setup):
    saved, _ = confirmed(setup, request(setup))
    f = reader(setup, {"product_id": str(setup.product)}, tool="platform.read")
    first = invoke(f)
    assert first["link_scope"] == "category_shared"
    assert first["items"][0]["links"][0]["version"] == 1
    assert invoke(f) == first
    confirmed(
        setup,
        request(
            setup,
            new_platform=None,
            platform_id=saved["result"]["platform_id"],
            expected_link_version=1,
            compatibility="修订后的真实范围",
        ),
    )
    with pytest.raises(DomainError) as stale:
        invoke(f)
    assert stale.value.code == "SOURCE_STALE"
    with Session(setup.admin) as s, s.begin():
        s.scalar(select(Grant).where(Grant.principal_id == setup.agent)).can_write = False
        s.scalar(select(Grant).where(Grant.principal_id == setup.agent)).expires_at = (
            now() - timedelta(seconds=1)
        )
    with pytest.raises(DomainError) as denied:
        invoke(f)
    assert denied.value.code == "FORBIDDEN_SCOPE"


def test_agent_platform_read_omits_private_variant_and_forbids_private_target(setup):
    artifact = source(setup)
    parent = definition(setup, artifact)
    variant, _, _ = derive(setup, parent, artifact, kind="customer", visibility="private")
    saved, _ = confirmed(
        setup, request(setup, variant_id=variant["id"], compatibility="客户私有要求")
    )
    f = reader(setup, {}, tool="platform.read")
    result = invoke(f)
    assert result["items"][0]["id"] == saved["result"]["platform_id"]
    assert result["items"][0]["links"] == []
    private = reader(
        setup,
        {
            "product_id": str(setup.product),
            "variant_id": variant["id"],
        },
        tool="platform.read",
    )
    with pytest.raises(DomainError) as denied:
        invoke(private)
    assert denied.value.code in {"SOURCE_UNAVAILABLE", "FORBIDDEN_SCOPE"}
    if denied.value.code == "SOURCE_UNAVAILABLE":
        assert denied.value.detail["reason"] == "private_material_context_binding_required"


def test_registered_schema_is_strict_and_product_scope_cannot_be_replaced(setup):
    from pydantic import ValidationError

    from pdos_next.agent_kernel.tools import default_registry
    from tests.products.test_platform_links_pg import payload

    registry = default_registry()
    assert registry.get("platform.link.create").tier == "T1"
    assert "product_id" in registry.get("platform.read").input_schema["properties"]
    f = reader(setup, {"product_id": str(uuid4())}, product_bound=True, tool="platform.read")
    with pytest.raises(DomainError) as denied:
        invoke(f)
    assert denied.value.code == "FORBIDDEN_SCOPE"
    for changes in (
        {"platform_id": uuid4()},
        {"action": "detach"},
        {"expected_link_version": 1},
        {"prepared_by_run_id": uuid4()},
        {"confirmed_by": setup.human},
    ):
        with pytest.raises(ValidationError):
            PlatformLinkInput.model_validate({**deepcopy(payload(setup)), **changes})
    with pytest.raises(ValidationError):
        PlatformReadInput(variant_id=UUID(int=2))
