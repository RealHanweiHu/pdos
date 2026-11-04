"""D26: changes needing disciplines no professional role can sign off are refused up front."""

from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from pdos_next.core.clock import now
from pdos_next.domain.change import order_service
from pdos_next.domain.change import order_store as store
from pdos_next.errors import DomainError

SCOPE = {"product_id": str(uuid4())}


def policy(*disciplines):
    value = store.ControlledPolicy.model_construct(
        scope=SCOPE,
        purpose="synthetic purpose",
        owner_id=uuid4(),
        visibility="category",
        source=SimpleNamespace(kind="artifact"),
        required_disciplines=disciplines,
        valid_from=now() - timedelta(minutes=1),
        valid_until=now() + timedelta(minutes=15),
        owner_proof={"group": "synthetic"},
    )
    return order_service._policy(
        None, None, None, SimpleNamespace(model_dump=lambda mode: SCOPE),
        "synthetic purpose", None, None, (lambda *_, **__: value, None),
    )


@pytest.mark.parametrize("extra", ["regulatory", "customer"])
def test_unsigned_disciplines_are_refused_with_a_clear_reason(extra):
    with pytest.raises(DomainError) as caught:
        policy("engineering", "manufacturing", extra)
    assert caught.value.reason == "CHANGE_DISCIPLINE_UNSUPPORTED"
    assert caught.value.code == "VALIDATION_FAILED" and caught.value.status == 422
    assert caught.value.detail["disciplines"] == [extra]
    assert "暂不支持" in caught.value.message


def test_disciplines_with_signing_roles_still_pass():
    value = policy("engineering", "manufacturing", "quality")
    assert value.required_disciplines == ("engineering", "manufacturing", "quality")
