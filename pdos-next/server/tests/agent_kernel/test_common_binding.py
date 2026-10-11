from dataclasses import replace
from uuid import uuid4

import pytest

from pdos_next.contracts import Command
from pdos_next.errors import DomainError
from pdos_next.service import Context, command_digest
from tests.agent_kernel.test_gateway import configured_route


def test_execution_context_cannot_borrow_two_run_namespaces_or_an_unowned_call():
    values = [uuid4() for _ in range(3)]
    with pytest.raises(DomainError):
        Context(*values, run_id=uuid4(), agent_run_id=uuid4())
    with pytest.raises(DomainError):
        Context(*values, agent_call_id=uuid4())


def test_command_fingerprint_is_normalized_and_binds_the_actual_category():
    command = Command(
        command_id=uuid4(),
        idempotency_key=str(uuid4()),
        category_id=uuid4(),
        operation="evidence.artifact.register",
        expected_revision=1,
        payload={"title": "source", "source_label": "synthetic", "content": "exact text"},
    )
    normalized = command.model_copy(
        update={"payload": {**command.payload, "visibility": "private"}}
    )
    assert command_digest(command) == command_digest(normalized)
    assert command_digest(command) != command_digest(
        command.model_copy(update={"category_id": uuid4()})
    )


def test_configuration_rotation_changes_route_binding_without_inventing_a_model_version():
    route = configured_route()
    one = replace(route, configuration_digest="a" * 64)
    two = replace(route, configuration_digest="b" * 64)
    assert one.version == two.version == route.version
    assert one.digest != two.digest
