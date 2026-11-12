"""Shared synthetic PG helpers for the D47 loops (P95–P97, P100).

Everything here is local and synthetic: extra named people, synthetic named
duties and qualifications from the test-only issuer, and project team roles
written through the real team endpoint. No real qualification is implied.
"""

import secrets
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.bootstrap.professional_import import import_professional_fact
from pdos_next.core.database import tenant_session
from pdos_next.core.models import Grant, LoginSession, Principal, now
from pdos_next.core.service import digest
from pdos_next.domain.builds.professional_authority import service as authority
from pdos_next.domain.projects.models import Project

SOURCE_QUOTE = "Synthetic requirement is unverified"


def command(setup, operation, payload, *, reads=()):
    return {
        "category_id": str(setup.category),
        "command_id": str(uuid4()),
        "idempotency_key": str(uuid4()),
        "operation": operation,
        "product_id": str(setup.product),
        "expected_revision": 1,
        "source_read_set": [dict(read) for read in reads],
        "payload": payload,
    }


def post(setup, cmd, headers=None):
    return setup.client.post(
        f"/v1/categories/{setup.category}/commands", headers=headers or setup.headers, json=cmd
    )


def preview(setup, cmd, headers=None):
    return setup.client.post(
        f"/v1/categories/{setup.category}/commands/preview",
        headers=headers or setup.headers,
        json=cmd,
    )


def confirmed(setup, cmd, headers=None):
    shown = preview(setup, cmd, headers)
    assert shown.status_code == 200, shown.text
    saved = post(setup, shown.json()["command"], headers)
    assert saved.status_code == 200, saved.text
    return saved.json(), shown.json()


def get(setup, path, headers=None):
    return setup.client.get(
        f"/v1/categories/{setup.category}/products/{setup.product}/{path}",
        headers=headers or setup.headers,
    )


def person(setup, name="Synthetic extra person"):
    """Another named human in the same tenant with category write access and a login."""
    principal, token = uuid4(), secrets.token_urlsafe(32)
    with Session(setup.admin) as s, s.begin():
        s.add(Principal(id=principal, tenant_id=setup.tenant, name=name, kind="human"))
        s.flush()
        s.add(
            Grant(
                tenant_id=setup.tenant,
                category_id=setup.category,
                principal_id=principal,
                can_write=True,
                expires_at=now() + timedelta(hours=1),
            )
        )
        s.add(
            LoginSession(
                tenant_id=setup.tenant,
                principal_id=principal,
                token_hash=digest(token),
                expires_at=now() + timedelta(hours=1),
            )
        )
    return SimpleNamespace(id=principal, headers={"Authorization": f"Bearer {token}"})


def headers_for(setup, principal_id):
    return {"Authorization": f"Bearer {setup.tokens[principal_id]}"}


def project_purpose(setup, project_id):
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
    ) as s:
        return s.scalar(select(Project.purpose).where(Project.id == UUID(str(project_id))))


def team(setup, project_id, members):
    """members: {principal_id: [role keys]}; written by the project owner through the real API."""
    path = f"/v1/categories/{setup.category}/products/{setup.product}/projects/{project_id}/team"
    current = setup.client.get(path, headers=setup.headers)
    assert current.status_code == 200, current.text
    view = current.json()
    present = {row["principal_id"] for row in view.get("members", [])}
    body = {
        "expected_revision": view.get("revision", 0),
        "request_key": str(uuid4()),
        "changes": [
            {
                "action": "set_roles" if str(principal) in present else "add",
                "principal_id": str(principal),
                "roles": [{"key": key} for key in roles],
            }
            for principal, roles in members.items()
        ],
    }
    saved = setup.client.post(path, headers=setup.headers, json=body)
    assert saved.status_code == 200, saved.text
    return saved.json()


class Professional:
    """Synthetic named duty + qualification for exact operations and the project purpose."""

    def __init__(self, setup, project_id, source):
        self.setup, self.project_id, self.source = setup, UUID(str(project_id)), source
        self.purpose = project_purpose(setup, project_id)
        self.issuer = authority.configure_local_synthetic(
            setup.engine,
            tenant_id=setup.tenant,
            product_id=setup.product,
            project_id=self.project_id,
            key=f"synthetic-d47-{setup.product}",
            enabled=True,
        )

    def grant(self, role, operations, subject=None, *, purpose=None):
        at = now()
        subject = subject or self.setup.human
        for kind in ("duty", "qualification"):
            payload = {
                "product_id": str(self.setup.product),
                "project_id": str(self.project_id),
                "subject_id": str(subject),
                "external_id": f"synthetic-{role}-{kind}-{subject}-{'-'.join(operations)}",
                "kind": kind,
                "role": role,
                "operations": list(operations),
                "purposes": [purpose or self.purpose],
                "state": "active",
                "valid_from": (at - timedelta(minutes=10)).isoformat(),
                "valid_until": (at + timedelta(minutes=50)).isoformat(),
                "approval": {
                    "system": "Synthetic named authority",
                    "external_id": f"SYN-{role}-{kind}-{uuid4()}",
                    "version": "local-synthetic-v1",
                    "approved_by": "Synthetic named issuer",
                    "issued_at": (at - timedelta(minutes=1)).isoformat(),
                },
                "sources": [
                    {
                        "artifact_id": self.source,
                        "expected_revision": 1,
                        "line": 1,
                        "quote": SOURCE_QUOTE,
                    }
                ],
                "reason": "Explicit local synthetic qualification only",
            }
            with tenant_session(
                self.setup.engine,
                self.setup.tenant,
                actor_id=self.setup.human,
                category_id=self.setup.category,
            ) as s:
                import_professional_fact(
                    s,
                    self.setup.ctx,
                    self.issuer,
                    payload,
                    request_key=str(uuid4()),
                    command_id=uuid4(),
                )

    def close(self):
        authority.disable_issuer(self.setup.engine, self.issuer.key)
        self.setup.engine._pdos_professional_synthetic = False


def shared_configuration(setup):
    """A category-visible G0 project, source, BOM and engineering configuration."""
    from tests.g0_fixture import create_g0_project

    setup.g0 = create_g0_project(setup, visibility="category", name="Synthetic shared development")
    registered = post(
        setup,
        command(
            setup,
            "evidence.artifact.register",
            {
                "title": "Synthetic shared input",
                "content": SOURCE_QUOTE,
                "source_label": "Synthetic fixture",
                "visibility": "category",
            },
        ),
    )
    assert registered.status_code == 200, registered.text
    source = registered.json()["subject_id"]
    reads = [{"artifact_id": source, "expected_revision": 1}]
    reference = {"artifact_id": source, "expected_revision": 1, "line": 1, "quote": SOURCE_QUOTE}
    common = {
        "visibility": "category",
        "reason": "Synthetic fixed preparation",
        "sources": [reference],
    }
    bom, _ = confirmed(
        setup,
        command(
            setup,
            "engineering.bom.revise",
            {
                **common,
                "name": "Synthetic shared BOM",
                "lines": [
                    {
                        "key": "motor",
                        "part": {"name": "Synthetic motor", "internal_number": "RD-MOTOR-S"},
                        "quantity": "2",
                        "unit": "ea",
                        "loss_rate": "0.1",
                        "critical": True,
                    }
                ],
            },
            reads=reads,
        ),
    )
    engineering, _ = confirmed(
        setup,
        command(
            setup,
            "engineering.configuration.create",
            {
                **common,
                "name": "Synthetic shared engineering",
                "definition_id": str(setup.g0.definition_id),
                "expected_definition_revision": 1,
                "bom_id": bom["subject_id"],
                "expected_bom_revision": 1,
            },
            reads=reads,
        ),
    )
    return SimpleNamespace(
        project=str(setup.g0.project_id),
        source=source,
        reads=reads,
        bom=bom["subject_id"],
        engineering=engineering["subject_id"],
    )
