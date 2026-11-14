"""Helpers for M2b scope-note tests: real preview/commit commands, real roles, no model."""

from uuid import uuid4

from sqlalchemy.orm import Session

from pdos_next.core.models import Product

SAVE, RETIRE, OBSERVE = "scope_note.save", "scope_note.retire", "scope_note.observation.record"


def headers(setup, person=None):
    return {"Authorization": f"Bearer {setup.tokens[person or setup.human]}"}


def envelope(setup, operation, payload, *, product=None):
    return {
        "category_id": str(setup.category), "command_id": str(uuid4()),
        "idempotency_key": str(uuid4()), "operation": operation,
        "product_id": str(product) if product else None, "expected_revision": 1,
        "source_read_set": [], "payload": payload,
    }


def preview(setup, operation, payload, *, person=None, product=None, status=200):
    response = setup.client.post(
        f"/v1/categories/{setup.category}/commands/preview", headers=headers(setup, person),
        json=envelope(setup, operation, payload, product=product))
    assert response.status_code == status, response.text
    return response.json()


def commit(setup, operation, payload, *, person=None, product=None, status=200):
    """Preview, then confirm once: the path a member's page action takes."""
    prepared = preview(setup, operation, payload, person=person, product=product)
    response = setup.client.post(
        f"/v1/categories/{setup.category}/commands", headers=headers(setup, person),
        json=prepared["command"])
    assert response.status_code == status, response.text
    return response.json(), prepared


def body(statement, *, kind="convention", **extra):
    return {"kind": kind, "statement": statement, **extra}


def anchor(setup, kind="category", identity=None):
    return {"kind": kind, "id": str(identity or setup.category)}


def save(setup, statement, *, kind="convention", at=None, person=None, product=None, status=200,
         evidence=(), relations=(), kept=(), **extra):
    payload = {"anchor": at or anchor(setup), "body": body(statement, kind=kind, **extra),
               "evidence": list(evidence), "relations": list(relations),
               "kept_similar": [str(value) for value in kept], "request_ref": str(uuid4())}
    receipt, _prepared = commit(setup, SAVE, payload, person=person, product=product,
                                status=status)
    return receipt


def listing(setup, kind="category", identity=None, *, person=None, everything=False,
            status=200):
    path = f"/v1/categories/{setup.category}/scope-notes/{kind}/{identity or setup.category}"
    response = setup.client.get(path + ("/all" if everything else ""),
                                headers=headers(setup, person))
    assert response.status_code == status, response.text
    return response.json()


def item(setup, note_id, *, person=None, status=200):
    response = setup.client.get(
        f"/v1/categories/{setup.category}/scope-note-items/{note_id}",
        headers=headers(setup, person))
    assert response.status_code == status, response.text
    return response.json()


def private_product(setup, *, owner=None, visibility="private"):
    identity = uuid4()
    with Session(setup.admin) as session, session.begin():
        session.add(Product(id=identity, tenant_id=setup.tenant, category_id=setup.category,
                            name="Synthetic private product", purpose="Scope note audience",
                            owner_id=owner or setup.human, visibility=visibility))
    return identity
