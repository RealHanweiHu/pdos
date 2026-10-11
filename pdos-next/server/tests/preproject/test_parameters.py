"""Dictionary validation and old-version reads without database access."""

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.domain.preproject import category_service
from pdos_next.domain.preproject.category_schemas import ParameterPublish, PriceObservation
from pdos_next.errors import DomainError


def publish(**changes):
    return ParameterPublish(
        **{
            "expected_current_version": 0,
            "key": "pressure",
            "name": "压力",
            "value_type": "number",
            "direction": "higher",
            "change_note": "初始草稿",
            **changes,
        }
    )


def test_unknown_dictionary_fields_remain_null():
    value = publish()
    assert (value.unit, value.standard_condition, value.method, value.acceptance_criterion) == (
        None,
        None,
        None,
        None,
    )
    with pytest.raises(ValidationError):
        publish(origin="human")
    with pytest.raises(ValidationError):
        publish(expected_current_version=1)
    with pytest.raises(ValidationError):
        publish(parameter_id=uuid4())


def test_enum_preserves_unknown_options_and_known_options_are_distinct():
    assert publish(value_type="enum").enum_values is None
    with pytest.raises(ValidationError):
        publish(value_type="enum", enum_values=["a", "a"])
    assert publish(value_type="enum", enum_values=["a", "b"]).enum_values == ["a", "b"]


def test_money_uses_decimal_without_invented_tax_status():
    price = PriceObservation(
        amount="0.100000000001",
        source_ref={"type": "human", "id": uuid4(), "version": 1, "statement": "观察记录"},
    )
    assert price.amount == Decimal("0.100000000001")
    assert price.includes_tax is None and price.includes_shipping is None


def test_exact_old_version_allowed_but_unit_mismatch_rejected():
    queries = []
    old = SimpleNamespace(unit="psi", value_type="number", version=1)
    session = SimpleNamespace(scalar=lambda q: queries.append(q) or old)
    ctx = SimpleNamespace(tenant_id=uuid4(), category_id=uuid4())
    identity = uuid4()
    assert category_service.check_parameter(session, ctx, identity, 1, "psi", "number") is old
    assert "parameter_current" not in str(queries[0])
    assert queries[0].compile().params["version_1"] == 1
    with pytest.raises(DomainError) as caught:
        category_service.check_parameter(session, ctx, identity, 1, "bar")
    assert caught.value.detail["reason"] == "parameter_unit_mismatch"
