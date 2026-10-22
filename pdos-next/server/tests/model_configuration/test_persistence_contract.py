"""Pure caller-Session contract checks and SQL compilation; no engine or database."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from pdos_next.errors import DomainError
from pdos_next.model_configuration.persistence import (
    ModelConfigurationHead,
    ModelConfigurationVersion,
    SessionConfigurationStore,
    decode,
)
from pdos_next.model_configuration.ports import SecretBinding
from pdos_next.model_configuration.service import ConfigurationVersion
from pdos_next.schemas.model_configuration import ModelMetadata


class SyntheticSession:
    def __init__(self, results):
        self.results = list(results)
        self.statements = []
        self.added = []
        self.flush_count = 0
        # No engine, execute, commit or rollback is provided.

    def scalar(self, statement):
        self.statements.append(statement)
        return self.results.pop(0)

    def add(self, row):
        self.added.append(row)

    def flush(self):
        self.flush_count += 1


def version():
    tenant = uuid4()
    metadata = ModelMetadata(
        protocol="openai-compatible",
        base_url="https://synthetic.invalid/v1",
        model="synthetic",
        model_version="v1",
    )
    return ConfigurationVersion(
        tenant,
        uuid4(),
        1,
        metadata,
        False,
        uuid4(),
        datetime(2026, 10, 2, tzinfo=UTC),
        SecretBinding(tenant, uuid4(), uuid4(), metadata.protocol, True),
    )


def test_append_tenant_lock_cas_roundtrip_no_commit():
    value = version()
    head = ModelConfigurationHead(tenant_id=value.tenant_id, revision=0)
    session = SyntheticSession([head])
    store = SessionConfigurationStore(session)
    store.append(value, expected_revision=0)
    assert session.flush_count == 1
    assert len(session.added) == 1 and head.revision == 1
    row = session.added[0]
    assert decode(row) == value
    query = session.statements[0].compile(dialect=postgresql.dialect())
    assert "FOR UPDATE" in str(query)
    assert value.tenant_id in query.params.values()
    assert row.public_metadata == value.metadata.model_dump(mode="json")
    assert "api_key" not in row.public_metadata
    assert not hasattr(row, "credential")


@pytest.mark.parametrize("head", [None, ModelConfigurationHead(tenant_id=uuid4(), revision=1)])
def test_failed_cas_never_flushes_or_appends(head):
    value = version()
    if head is not None:
        head.tenant_id = value.tenant_id
    session = SyntheticSession([head])
    with pytest.raises(DomainError) as error:
        SessionConfigurationStore(session).append(value, expected_revision=0)
    assert error.value.reason in {
        "MODEL_CONFIGURATION_STALE",
        "MODEL_CONFIGURATION_STORAGE_NOT_PROVISIONED",
    }
    assert session.added == [] and session.flush_count == 0


def test_provisioned_revision_zero_is_explicitly_unconfigured():
    value = version()
    session = SyntheticSession([ModelConfigurationHead(tenant_id=value.tenant_id, revision=0)])
    assert SessionConfigurationStore(session).current(value.tenant_id) is None
    assert len(session.statements) == 1


def test_reading_tenant_and_exact_head_revision_no_fallback():
    value = version()
    session = SyntheticSession([ModelConfigurationHead(tenant_id=value.tenant_id, revision=1)])
    row = ModelConfigurationVersion(
        id=value.id,
        tenant_id=value.tenant_id,
        revision=1,
        public_metadata=value.metadata.model_dump(mode="json"),
        enabled=False,
        created_by=value.created_by,
        created_at=value.created_at,
        secret_reference=value.secret.reference,
        secret_version=value.secret.version,
        secret_available=True,
        binding_digest=value.binding_digest,
    )
    session.results.append(row)
    assert SessionConfigurationStore(session).current(value.tenant_id) == value
    query = session.statements[1].compile(dialect=postgresql.dialect())
    assert value.tenant_id in query.params.values() and 1 in query.params.values()
    row.binding_digest = "tampered"
    with pytest.raises(DomainError) as error:
        decode(row)
    assert error.value.reason == "MODEL_CONFIGURATION_STORAGE_INVALID"
