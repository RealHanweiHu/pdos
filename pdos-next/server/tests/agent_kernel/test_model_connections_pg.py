"""Real authenticated API/T1 transactions; secret storage is an isolated in-memory double."""

import json
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.api import create_app
from pdos_next.model_configuration.persistence import ModelConfigurationVersion
from pdos_next.models import Confirmation
from tests.agent_kernel.test_model_configuration_transactions import configured, submit
from tests.agent_kernel.test_transactions import run
from tests.model_configuration.test_connections import KEY, configured_host, request
from tests.model_configuration.test_host_runtime import document


def client_host(setup, tmp_path):
    old_client, ports, command = configured(setup)
    old_client.close()
    host, kms = configured_host(tmp_path, setup.tenant)
    ports = replace(ports, secrets=host, provider_for=host.provider_for,
        rate_card_for=host.rate_card_for, output_limit_for=host.output_limit_for)
    client = TestClient(create_app(setup.engine, setup.auth, agent_runtime_ports=ports))
    return client, host, kms, ports, command


def body(setup, *, key=KEY, name="Provider one"):
    value = request().model_dump(mode="json")
    return {**value, "api_key": key, "name": name,
        "pricing": document(setup.tenant)["models"][0]["pricing"]}


def test_add_two_providers_confirm_switch_and_use_each_correct_key(setup, tmp_path):
    client, host, kms, ports, command = client_host(setup, tmp_path)
    path = f"/v1/categories/{setup.category}/model-connections"
    first_body = body(setup)
    first_body["metadata"]["context_window_tokens"] = 200000
    first = client.post(path, json=first_body, headers=setup.headers)
    assert first.status_code == 200, first.text
    assert KEY not in first.text + host.path.read_text()
    replay = client.post(path, json=first_body, headers=setup.headers)
    assert replay.json() == first.json() and kms.writes == 1
    second = client.post(path, json=body(setup, key="synthetic-provider-two", name="Provider two"),
        headers=setup.headers)
    assert second.status_code == 200, second.text
    listing = client.get(path, headers=setup.headers)
    assert listing.status_code == 200 and len(listing.json()["connections"]) == 3
    assert KEY not in listing.text and "secret_arn" not in listing.text
    for revision, (connection, expected_key) in enumerate([
        (first.json(), KEY), (second.json(), "synthetic-provider-two"), (first.json(), KEY)
    ]):
        command.update(command_id=str(uuid4()), idempotency_key=str(uuid4()))
        current = client.get(f"/v1/categories/{setup.category}/model-configuration",
            headers=setup.headers).json()
        command["expected_revision"] = current["category_revision"]
        command["payload"] = {"expected_revision": revision,
            "metadata": connection["metadata"], "enabled": True}
        saved, prepared = submit(setup, client, command)
        assert saved.status_code == 200, saved.text
        _, scope = run(setup)
        selected = Bootstrap(setup.engine, ports=ports).route_for(scope)
        assert selected.api_key.get_secret_value() == expected_key
        assert str(selected.connection_id) == connection["id"]
        assert selected.context_window_tokens == connection["metadata"].get("context_window_tokens")
        assert host.rate_card_for(scope, selected).provider == "custom.invalid"
        restored, _ = submit(setup, client, prepared, preview=False)
        assert restored.json() == saved.json()
    with Session(setup.admin) as session:
        versions = session.scalars(select(ModelConfigurationVersion).where(
            ModelConfigurationVersion.tenant_id == setup.tenant)).all()
        snapshots = session.scalars(select(Confirmation.snapshot).where(
            Confirmation.tenant_id == setup.tenant)).all()
        assert len(versions) == 3
        assert KEY not in json.dumps([row.public_metadata for row in versions] + snapshots)
    client.close()


def test_nonadmin_cross_scope_and_invalid_keys_fail_without_secret_side_effects(setup, tmp_path):
    client, _, kms, _, command = client_host(setup, tmp_path)
    path = f"/v1/categories/{setup.category}/model-connections"
    peer = {"Authorization": "Bearer " + setup.tokens[setup.peer]}
    for method in (client.get, client.post):
        kwargs = {"json": body(setup)} if method == client.post else {}
        assert method(path, headers=peer, **kwargs).status_code == 403
    malformed = client.post(path, json=body(setup, key="synthetic\nprivate"), headers=setup.headers)
    assert malformed.status_code == 422 and "synthetic" not in malformed.text
    assert kms.writes == 0
    created = client.post(path, json=body(setup), headers=setup.headers).json()
    command["payload"]["metadata"] = {**created["metadata"], "connection_id": str(uuid4())}
    rejected, _ = submit(setup, client, command, preview=False)
    assert rejected.status_code != 200
    assert kms.writes == 1
    client.close()


def test_interrupted_secure_save_returns_unknown_and_same_request_recovers(
    setup, tmp_path, monkeypatch
):
    import pdos_next.model_configuration.connections as connections

    client, host, kms, _, _ = client_host(setup, tmp_path)
    path = f"/v1/categories/{setup.category}/model-connections"
    data = body(setup)
    replace_file = connections.os.replace

    def fail_replacement(*_):
        raise OSError("synthetic lost metadata write")

    monkeypatch.setattr(connections.os, "replace", fail_replacement)
    interrupted = client.post(path, json=data, headers=setup.headers)
    assert interrupted.status_code == 503 and KEY not in interrupted.text
    assert not host.configuration().connections and kms.writes == 1
    monkeypatch.setattr(connections.os, "replace", replace_file)
    recovered = client.post(path, json=data, headers=setup.headers)
    assert recovered.status_code == 200 and kms.writes == 1
    assert len(host.configuration().connections) == 1
    client.close()


@pytest.mark.parametrize("field", [
    "tenant_id", "provider", "secret_arn", "development_unlimited_budget"
])
def test_client_cannot_submit_server_authority_fields(setup, tmp_path, field):
    client, _, kms, _, _ = client_host(setup, tmp_path)
    data = {**body(setup), field: "synthetic-injected-authority"}
    response = client.post(f"/v1/categories/{setup.category}/model-connections",
        json=data, headers=setup.headers)
    assert response.status_code == 422 and KEY not in response.text
    assert kms.writes == 0
    client.close()
