"""One isolated stage journey: scoped API reads and durable synthetic webhook delivery."""

import base64
import hmac
import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import NoReturn
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select

from app.db.engine import get_engine
from app.db.schema import tables
from app.domain import open_api_calls, project_webhooks
from app.integrations import webhook_protocol, webhook_worker
from app.integrations.webhook_protocol import WebhookTransport
from app.integrations.webhook_worker import WebhookWorker
from app.settings import get_settings
from tests.test_product_engineering_api import SETUP_PAYLOAD, bearer_headers
from tests.test_product_engineering_api import client as client
from tests.test_product_engineering_api import (
    isolated_product_database as isolated_product_database,
)
from tests.test_projects_api import approved_case, create_project

SYNTHETIC_URL = "https://n7-receiver.invalid/pdos-stage"
ISSUE_FIELDS = {"id", "title", "status", "severity", "owner_user_id", "updated_at"}


def object_body(value: object) -> dict[str, object]:
    assert isinstance(value, dict) and all(isinstance(key, str) for key in value)
    return dict(value)


def items(value: object) -> list[dict[str, object]]:
    assert isinstance(value, list)
    return [object_body(item) for item in value]


def string(value: object) -> str:
    assert isinstance(value, str)
    return value


def post(
    client: TestClient,
    path: str,
    headers: dict[str, str],
    body: dict[str, object],
    *,
    status: int = 200,
) -> dict[str, object]:
    result = client.post(path, headers=headers, json=body)
    assert result.status_code == status, result.text
    assert result.headers["cache-control"] == "no-store"
    return object_body(result.json())


class SyntheticReceiver(WebhookTransport):
    """In-memory receiver; no sockets, DNS lookup, or actual HTTPS request."""

    def __init__(self, secret: bytes) -> None:
        self.secret = secret
        self.requests: list[tuple[bytes, dict[str, str]]] = []

    def post(self, url: str, body: bytes, headers: dict[str, str]) -> tuple[int, bytes]:
        assert url == SYNTHETIC_URL
        payload = object_body(json.loads(body))
        assert headers["X-PDOS-Webhook-Version"] == "pdos.webhook.v1"
        assert payload["protocol"] == "pdos.webhook.v1"
        assert payload["delivery_id"] == headers["X-PDOS-Delivery-ID"]
        timestamp = int(headers["X-PDOS-Timestamp"])
        assert abs(int(datetime.now(UTC).timestamp()) - timestamp) <= 300
        signed = (
            f"v1.{timestamp}.{headers['X-PDOS-Delivery-ID']}."
            f"{headers['X-PDOS-Attempt-ID']}.{sha256(body).hexdigest()}"
        ).encode()
        expected = "v1=" + hmac.new(self.secret, signed, sha256).hexdigest()
        assert hmac.compare_digest(headers["X-PDOS-Signature"], expected)
        self.requests.append((body, dict(headers)))
        if len(self.requests) == 1:
            return 503, b'{"accepted":false}'
        return 200, json.dumps(
            {
                "delivery_id": payload["delivery_id"],
                "event_id": payload["event_id"],
                "accepted": True,
            }
        ).encode()


def reject_real_delivery(
    self: WebhookTransport, url: str, body: bytes, headers: dict[str, str]
) -> NoReturn:
    raise AssertionError("This stage scenario must use its in-memory synthetic receiver")


def test_scoped_api_and_webhook_journey_preserves_receipts_and_stops_revoked_access(
    client: TestClient, isolated_product_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Scope synthetic enablement to these services; never modify the deployment environment.
    settings = get_settings().model_copy(
        update={
            "open_api_enabled": True,
            "webhook_delivery_enabled": True,
            "webhook_encryption_key": SecretStr(base64.urlsafe_b64encode(b"n7" * 16).decode()),
        }
    )
    for module in (open_api_calls, project_webhooks, webhook_protocol, webhook_worker):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
    monkeypatch.setattr(WebhookTransport, "post", reject_real_delivery)

    setup = client.post("/api/setup", json=SETUP_PAYLOAD)
    assert setup.status_code == 201, setup.text
    manager = bearer_headers(client)
    case = approved_case(client, manager, suffix="N7-INTEGRATION-SYNTHETIC")
    created = create_project(client, manager, case["id"], code="N7-INTEGRATION-SYNTHETIC")
    assert created.status_code == 201, created.text
    project = UUID(string(object_body(created.json())["id"]))
    base = f"/api/projects/{project}"
    api = base + "/open-api"
    webhooks = base + "/webhooks"
    external = f"/api/open/v1/projects/{project}"
    expires_at = (datetime.now(UTC) + timedelta(days=1)).isoformat()

    credential_command: dict[str, object] = {
        "request_id": str(uuid4()),
        "label": "Synthetic stage engineering reader",
        "audience": "internal",
        "scopes": ["work.read"],
        "expires_at": expires_at,
        "purpose": "Synthetic stage verification; no real external integration",
    }
    issued = post(client, api + "/create", manager, credential_command)
    credential = object_body(issued["credential"])
    credential_id = UUID(string(credential["id"]))
    token = string(issued["access_token"])
    external_headers = {"Authorization": f"Bearer {token}"}
    repeated = post(client, api + "/create", manager, credential_command)
    assert repeated["credential"] == credential and repeated["access_token"] is None

    endpoint_command: dict[str, object] = {
        "request_id": str(uuid4()),
        "label": "Synthetic stage receiver; in-memory transport only",
        "url": SYNTHETIC_URL,
        "audience": "internal",
        "topics": ["work.updated"],
        "expires_at": expires_at,
        "purpose": "Synthetic notification and receipt verification; never send over a network",
    }
    issued_endpoint = post(client, webhooks + "/create", manager, endpoint_command)
    endpoint = object_body(issued_endpoint["endpoint"])
    endpoint_id = UUID(string(endpoint["id"]))
    assert endpoint["status"] == "paused" and endpoint["version"] == 0
    secret = base64.urlsafe_b64decode(string(issued_endpoint["signing_key"]))
    assert len(secret) == 32
    repeated_endpoint = post(client, webhooks + "/create", manager, endpoint_command)
    assert repeated_endpoint["endpoint"] == endpoint and repeated_endpoint["signing_key"] is None
    activation = post(
        client,
        webhooks + "/control",
        manager,
        {
            "endpoint_id": str(endpoint_id),
            "request_id": str(uuid4()),
            "expected_version": 0,
            "status": "active",
            "receiver_contract_confirmed": True,
            "delivery_authorized": True,
            "reason": "Authorize only this synthetic in-memory receiver for the stage test",
        },
    )
    assert activation["status"] == "active" and activation["version"] == 1

    issue = post(
        client,
        base + "/issues",
        manager,
        {
            "title": "Synthetic N7 integration issue",
            "description": "Synthetic private detail outside the external field allowlist",
            "severity": "medium",
        },
        status=201,
    )
    issue_id = UUID(string(issue["id"]))
    query: dict[str, object] = {"request_id": str(uuid4()), "kind": "issue"}
    first = post(client, external + "/work/query", external_headers, query)
    projected = items(object_body(first["result"])["items"])
    assert len(projected) == 1 and set(projected[0]) == ISSUE_FIELDS
    assert projected[0]["id"] == str(issue_id)
    assert {key: projected[0][key] for key in ISSUE_FIELDS - {"updated_at"}} == {
        key: issue[key] for key in ISSUE_FIELDS - {"updated_at"}
    }
    assert datetime.fromisoformat(string(projected[0]["updated_at"])) == datetime.fromisoformat(
        string(issue["updated_at"])
    )
    assert first["replayed"] is False
    replay = post(client, external + "/work/query", external_headers, query)
    assert replay == {**first, "replayed": True}
    post(
        client,
        external + "/work/query",
        external_headers,
        {**query, "kind": "task"},
        status=409,
    )
    post(
        client,
        external + "/customer-reports/query",
        external_headers,
        {"request_id": str(uuid4())},
        status=403,
    )
    calls_before_revoke = post(
        client, api + "/calls", manager, {"credential_id": str(credential_id)}
    )
    retained_calls = items(calls_before_revoke["items"])
    assert len(retained_calls) == 2 and {item["status_code"] for item in retained_calls} == {
        200,
        403,
    }
    revocation: dict[str, object] = {
        "credential_id": str(credential_id),
        "request_id": str(uuid4()),
        "reason": "Synthetic API consumer finished; stop both new calls and replay",
    }
    revoked = post(client, api + "/revoke", manager, revocation)
    assert post(client, api + "/revoke", manager, revocation) == revoked
    post(client, external + "/work/query", external_headers, query, status=401)
    post(
        client,
        external + "/work/query",
        external_headers,
        {**query, "request_id": str(uuid4())},
        status=401,
    )
    assert (
        post(client, api + "/calls", manager, {"credential_id": str(credential_id)})
        == calls_before_revoke
    )

    with get_engine().connect() as connection:
        stored_credential = (
            connection.execute(
                select(tables.open_api_credentials).where(
                    tables.open_api_credentials.c.id == credential_id
                )
            )
            .mappings()
            .one()
        )
        assert stored_credential["verifier"] == sha256(token.encode()).hexdigest()
        source = (
            connection.execute(
                select(tables.events).where(
                    tables.events.c.project_id == project,
                    tables.events.c.entity_id == issue_id,
                    tables.events.c.event_type == "ISSUE_CREATED",
                )
            )
            .mappings()
            .one()
        )

    receiver = SyntheticReceiver(secret)
    worker = WebhookWorker(get_engine(), receiver)
    first_delivery = worker.run_once()
    assert first_delivery["status"] == "retry_wait" and first_delivery["queued"] == 1
    history = post(client, webhooks + "/deliveries", manager, {"endpoint_id": str(endpoint_id)})
    deliveries = items(history["items"])
    assert len(deliveries) == 1 and len(receiver.requests) == 1
    delivery = deliveries[0]
    delivery_id = UUID(string(delivery["id"]))
    assert delivery["source_event_id"] == source["id"]
    payload = object_body(delivery["payload"])
    assert payload["event_id"] == source["event_id"] and payload["event_type"] == "work.updated"
    assert object_body(payload["data"])["current_record"] == projected[0]
    assert delivery["payload_digest"] == sha256(receiver.requests[0][0]).hexdigest()
    assert delivery["last_error"] == "receiver_temporarily_unavailable"
    assert [row["outcome"] for row in items(delivery["attempts"])] == ["retryable"]

    retry: dict[str, object] = {
        "delivery_id": str(delivery_id),
        "request_id": str(uuid4()),
        "action": "retry",
        "reason": "Synthetic receiver recovered; reuse the original retained notification",
    }
    retry_receipt = post(client, webhooks + "/delivery-action", manager, retry)
    assert post(client, webhooks + "/delivery-action", manager, retry) == retry_receipt
    # A fresh worker must recover the same persisted delivery, not rely on process memory.
    worker = WebhookWorker(get_engine(), receiver)
    assert worker.run_once()["status"] == "delivered"
    assert len(receiver.requests) == 2 and receiver.requests[0][0] == receiver.requests[1][0]
    assert (
        receiver.requests[0][1]["X-PDOS-Attempt-ID"] != receiver.requests[1][1]["X-PDOS-Attempt-ID"]
    )
    completed = items(
        post(client, webhooks + "/deliveries", manager, {"endpoint_id": str(endpoint_id)})["items"]
    )[0]
    assert completed["id"] == str(delivery_id) and completed["attempt_count"] == 2
    assert [row["outcome"] for row in items(completed["attempts"])] == ["retryable", "delivered"]
    assert len(items(completed["actions"])) == 1

    second_issue = post(
        client,
        base + "/issues",
        manager,
        {"title": "Synthetic pending notification to stop", "severity": "low"},
        status=201,
    )
    assert worker.dispatch() == 1
    held_attempt = worker.claim()
    assert held_attempt is not None
    paused = post(
        client,
        webhooks + "/control",
        manager,
        {
            "endpoint_id": str(endpoint_id),
            "request_id": str(uuid4()),
            "expected_version": 1,
            "status": "paused",
            "reason": "Synthetic pause after claim must prevent transport dispatch",
        },
    )
    assert paused["version"] == 2 and paused["status"] == "paused"
    assert worker.deliver(held_attempt) == "retry_wait"
    assert worker.run_once()["status"] == "idle" and len(receiver.requests) == 2
    pending_history = items(
        post(client, webhooks + "/deliveries", manager, {"endpoint_id": str(endpoint_id)})["items"]
    )
    pending = next(row for row in pending_history if row["id"] != str(delivery_id))
    assert pending["last_error"] == "endpoint_paused"
    pending_data = object_body(object_body(pending["payload"])["data"])
    pending_record = object_body(pending_data["current_record"])
    assert pending_record["id"] == second_issue["id"]
    assert [row["outcome"] for row in items(pending["attempts"])] == ["abandoned"]
    endpoint_revoked = post(
        client,
        webhooks + "/control",
        manager,
        {
            "endpoint_id": str(endpoint_id),
            "request_id": str(uuid4()),
            "expected_version": 2,
            "status": "revoked",
            "reason": "Synthetic consumer retired; cancel the pending retained notification",
        },
    )
    assert endpoint_revoked["version"] == 3 and endpoint_revoked["status"] == "revoked"
    assert worker.run_once()["status"] == "idle" and len(receiver.requests) == 2
    post(
        client,
        webhooks + "/delivery-action",
        manager,
        {**retry, "delivery_id": pending["id"], "request_id": str(uuid4())},
        status=409,
    )
    final = items(
        post(client, webhooks + "/deliveries", manager, {"endpoint_id": str(endpoint_id)})["items"]
    )
    assert {row["id"]: row["status"] for row in final} == {
        str(delivery_id): "delivered",
        string(pending["id"]): "cancelled",
    }
    assert (
        next(row for row in final if row["id"] == pending["id"])["last_error"] == "endpoint_revoked"
    )

    with get_engine().connect() as connection:
        scans = (
            connection.execute(
                select(tables.webhook_scans).where(
                    tables.webhook_scans.c.endpoint_id == endpoint_id
                )
            )
            .mappings()
            .all()
        )
        assert len(scans) == 2 and all(row["result"] == "queued" for row in scans)
        assert {str(row["delivery_id"]) for row in scans} == {row["id"] for row in final}
