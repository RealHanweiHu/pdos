"""Synthetic transport with actual native commands, Outbox and derived SQL storage."""

from dataclasses import replace
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from pdos_agent_runtime.graph import in_registered_agent_graph
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.models import TenantAdministrator
from pdos_next.api import create_app
from pdos_next.enterprise_search.embedding_activities import EmbeddingPorts
from pdos_next.enterprise_search.embedding_schemas import (
    EmbeddingMetadata,
    EmbeddingResponse,
)
from pdos_next.model_configuration.ports import SecretBinding, SecretMaterial
from pdos_next.models import Category, Outbox, Receipt
from pdos_next.service import digest
from tests.agent_kernel.test_cost_budget import rate


class SyntheticEmbedding:
    def __init__(self, tenant):
        self.binding = SecretBinding(tenant, uuid4(), uuid4(), "openai-compatible", True)
        self.calls = []
        self.dimensions = 2
        self.fail_once = False

    def provider_for(self, tenant, metadata):
        assert tenant == self.binding.tenant_id
        return metadata.provider

    def current_embedding(self, tenant, metadata):
        assert metadata.connection_id is not None
        return self.binding if tenant == self.binding.tenant_id else None

    def resolve(self, binding):
        assert binding == self.binding
        return SecretMaterial(binding, SecretStr("synthetic-embedding-only"))

    def embed(self, metadata, texts, credential, *, timeout):
        assert in_registered_agent_graph() and credential.binding == self.binding
        assert timeout <= 30 and metadata.dimensions == self.dimensions
        self.calls.append(digest(texts))
        if self.fail_once:
            self.fail_once = False
            raise TimeoutError("Synthetic uncertain delivery")
        return EmbeddingResponse(
            tuple(tuple([1.0] + [0.0] * (metadata.dimensions - 1)) for _ in texts), input_tokens=10
        )


def ports_for(setup):
    with Session(setup.admin) as session, session.begin():
        session.add(TenantAdministrator(tenant_id=setup.tenant, principal_id=setup.human))
    provider = SyntheticEmbedding(setup.tenant)
    base = rate()

    def price(_tenant, metadata):
        return replace(
            base,
            provider=metadata.provider,
            model=metadata.model,
            configuration_version=metadata.model_version,
        )

    return provider, EmbeddingPorts(provider, price, provider)


def command_for(
    setup, *, profile_id=None, revision=0, budget_revision=0, enabled=True, dimensions=2
):
    with Session(setup.admin) as session:
        category_revision = session.get(Category, setup.category).revision
    metadata = EmbeddingMetadata(
        base_url="https://embedding.invalid/v1",
        model="synthetic-embed",
        model_version="synthetic@1",
        dimensions=dimensions,
        connection_id=uuid4(),
        data_categories=["internal"],
    )
    return {
        "command_id": str(uuid4()),
        "idempotency_key": str(uuid4()),
        "operation": "embedding.profile.save",
        "category_id": str(setup.category),
        "product_id": None,
        "expected_revision": category_revision,
        "source_read_set": [],
        "payload": {
            "profile_id": str(profile_id or uuid4()),
            "expected_revision": revision,
            "expected_budget_revision": budget_revision,
            "metadata": metadata.model_dump(mode="json"),
            "enabled": enabled,
            "index_budget_micro_usd": 100_000_000,
        },
    }


def save_profile(setup, ports, command):
    with TestClient(create_app(setup.engine, setup.auth, embedding_ports=ports)) as client:
        path = f"/v1/categories/{setup.category}/commands"
        preview = client.post(path + "/preview", json=command, headers=setup.headers)
        assert preview.status_code == 200, preview.text
        saved = client.post(path, json=preview.json()["command"], headers=setup.headers)
        assert saved.status_code == 200, saved.text
        replay = client.post(path, json=preview.json()["command"], headers=setup.headers)
        assert replay.status_code == 200 and replay.json() == saved.json()
    return saved.json(), preview.json()


def reference_for(setup, receipt):
    with Session(setup.admin) as session:
        actual = session.get(Receipt, UUID(receipt["id"]))
        event = session.scalar(select(Outbox).where(Outbox.receipt_id == actual.id))
        return {
            "tenant_id": str(setup.tenant),
            "category_id": str(setup.category),
            "actor_id": str(event.actor_id),
            "requester_id": str(actual.requester_id),
            "event_id": str(event.id),
            "subject_id": str(event.subject_id),
            "subject_revision": event.subject_revision,
            "event_type": event.type,
            "product_id": None,
            "schema_version": event.schema_version,
            "correlation_id": str(event.correlation_id),
            "lease_id": str(uuid4()),
        }
