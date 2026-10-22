"""Actual shared schema, authenticated COMMON save and default runtime route."""

from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.bootstrap import Bootstrap, RuntimePorts
from pdos_next.agent_kernel.models import TenantAdministrator
from pdos_next.api import create_app
from pdos_next.errors import DomainError
from pdos_next.model_configuration.persistence import (
    ModelConfigurationHead,
    ModelConfigurationVersion,
)
from pdos_next.model_configuration.ports import SecretBinding, SecretMaterial
from pdos_next.models import Audit, Confirmation, Outbox, Receipt
from pdos_next.schemas.model_configuration import ModelMetadata
from tests.agent_kernel.test_transactions import human_session, run


class SyntheticSecrets:
    def __init__(self, tenant):
        self.binding = SecretBinding(tenant, uuid4(), uuid4(), "openai-compatible", True)

    def current(self, tenant, protocol):
        return (
            self.binding
            if (tenant, protocol) == (self.binding.tenant_id, self.binding.protocol)
            else None
        )

    def resolve(self, binding):
        return SecretMaterial(binding, SecretStr("synthetic-fixture-only"))


def configured(setup):
    with Session(setup.admin) as s, s.begin():
        s.add(TenantAdministrator(tenant_id=setup.tenant, principal_id=setup.human))
    secrets = SyntheticSecrets(setup.tenant)
    ports = RuntimePorts(secrets=secrets)
    client = TestClient(create_app(setup.engine, setup.auth, agent_runtime_ports=ports))
    command = {
        "command_id": str(uuid4()),
        "idempotency_key": str(uuid4()),
        "operation": "model.configuration.save",
        "category_id": str(setup.category),
        "expected_revision": 1,
        "product_id": None,
        "source_read_set": [],
        "payload": {
            "expected_revision": 0,
            "enabled": True,
            "metadata": ModelMetadata(
                protocol="openai-compatible",
                base_url="https://synthetic.invalid/v1",
                model="synthetic-model",
                model_version="synthetic@1",
            ).model_dump(mode="json"),
        },
    }
    return client, ports, command


def submit(setup, client, command, *, preview=True):
    path = f"/v1/categories/{setup.category}/commands"
    if preview:
        response = client.post(path + "/preview", json=command, headers=setup.headers)
        assert response.status_code == 200, response.text
        command = response.json()["command"]
    return client.post(path, json=command, headers=setup.headers), command


def test_actual_configuration_save_recovery_and_default_agent_route(setup):
    client, ports, command = configured(setup)
    path = f"/v1/categories/{setup.category}/model-configuration"
    empty = client.get(path, headers=setup.headers)
    assert empty.status_code == 200 and empty.json()["configuration"] is None
    with human_session(setup) as s:
        assert s.get(ModelConfigurationHead, setup.tenant).revision == 0
    result, prepared = submit(setup, client, command)
    assert result.status_code == 200, result.text
    assert result.json()["result"]["requires_requalification"] is True
    saved = client.get(path, headers=setup.headers)
    assert saved.status_code == 200 and saved.json()["configuration"]["revision"] == 1
    assert "synthetic-fixture-only" not in saved.text
    assert "secret_reference" not in saved.text and "secret_version" not in saved.text
    _, scope = run(setup)
    bootstrap = Bootstrap(setup.engine, ports=ports)
    route = bootstrap.route_for(scope)
    assert route.version == "synthetic@1" and route.configuration_digest
    ports.secrets.binding = replace(ports.secrets.binding, version=uuid4())
    with pytest.raises(DomainError) as failure:
        bootstrap.route_for(scope)
    assert failure.value.code == "SOURCE_UNAVAILABLE"
    # Original completed recovery does not borrow current write/config/secret eligibility.
    replay, _ = submit(setup, client, prepared, preview=False)
    assert replay.status_code == 200 and replay.json() == result.json()
    with Session(setup.admin) as s:
        for table in (ModelConfigurationVersion, Receipt, Audit, Outbox):
            assert (
                s.scalar(
                    select(func.count()).select_from(table).where(table.tenant_id == setup.tenant)
                )
                == 1
            )


def test_configuration_rotation_invalidates_review_and_nonadmin_cannot_save(setup):
    client, ports, command = configured(setup)
    path = f"/v1/categories/{setup.category}/commands"
    preview = client.post(path + "/preview", json=command, headers=setup.headers)
    assert preview.status_code == 200, preview.text
    ports.secrets.binding = replace(ports.secrets.binding, version=uuid4())
    stale = client.post(path, json=preview.json()["command"], headers=setup.headers)
    assert stale.status_code == 409 and stale.json()["code"] == "CONFIRMATION_REQUIRED", stale.text
    assert stale.json()["detail"]["reason"] == "CONFIRMATION_SCOPE_CHANGED"
    denied = client.post(
        path + "/preview",
        json=command,
        headers={"Authorization": "Bearer " + setup.tokens[setup.peer]},
    )
    assert denied.status_code == 403 and denied.json()["code"] == "FORBIDDEN_SCOPE"
    with Session(setup.admin) as s:
        assert s.get(ModelConfigurationHead, setup.tenant).revision == 0
        assert (
            s.scalar(
                select(func.count())
                .select_from(ModelConfigurationVersion)
                .where(ModelConfigurationVersion.tenant_id == setup.tenant)
            )
            == 0
        )
        assert not s.scalar(
            select(Confirmation.consumed).where(Confirmation.tenant_id == setup.tenant)
        )


def test_configuration_receipt_tail_failure_rolls_back_entire_save(setup):
    client, _, command = configured(setup)
    preview = client.post(
        f"/v1/categories/{setup.category}/commands/preview", json=command, headers=setup.headers
    )
    assert preview.status_code == 200, preview.text

    def fail_tail(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO outbox_events"):
            raise RuntimeError("synthetic terminal failure")

    event.listen(setup.engine, "before_cursor_execute", fail_tail)
    try:
        with pytest.raises(RuntimeError, match="synthetic terminal failure"):
            submit(setup, client, preview.json()["command"], preview=False)
    finally:
        event.remove(setup.engine, "before_cursor_execute", fail_tail)
    with Session(setup.admin) as s:
        assert s.get(ModelConfigurationHead, setup.tenant).revision == 0
        assert not s.scalar(
            select(Confirmation.consumed).where(Confirmation.tenant_id == setup.tenant)
        )
        for table in (ModelConfigurationVersion, Receipt, Audit, Outbox):
            assert (
                s.scalar(
                    select(func.count()).select_from(table).where(table.tenant_id == setup.tenant)
                )
                == 0
            )
    result, _ = submit(setup, client, preview.json()["command"], preview=False)
    assert result.status_code == 200, result.text


def test_direct_configuration_dml_cannot_bypass_confirmation_atom(setup):
    client, _, command = configured(setup)
    result, _ = submit(setup, client, command)
    assert result.status_code == 200, result.text
    with pytest.raises(DBAPIError):
        with human_session(setup) as s:
            s.execute(
                text("UPDATE model_configuration_heads SET revision=revision+1 WHERE tenant_id=:t"),
                {"t": setup.tenant},
            )
    with Session(setup.admin) as s:
        assert s.get(ModelConfigurationHead, setup.tenant).revision == 1
        assert not s.scalar(
            text("SELECT has_table_privilege('pdos_agent','model_configuration_versions','INSERT')")
        )
