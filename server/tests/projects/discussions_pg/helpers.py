"""HTTP helpers for discussions and notifications over real G0 projects (D37 ⑤)."""

from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from pdos_next.domain.my_work.notifications.models import Notification


def headers(setup, person):
    return {"Authorization": f"Bearer {setup.tokens[person]}"}


def project_root(setup, project):
    return f"/v1/categories/{setup.category}/products/{project.product_id}/projects/{project.project_id}"


def start_topic(setup, project, person, title, body, *, expect=201):
    response = setup.client.post(
        project_root(setup, project) + "/discussions",
        headers=headers(setup, person),
        json={"title": title, "body": body, "request_key": str(uuid4())},
    )
    assert response.status_code == expect, response.text
    return response.json()


def reply(setup, project, person, thread_id, body, *, expect=201, key=None):
    response = setup.client.post(
        project_root(setup, project) + f"/discussions/{thread_id}/messages",
        headers=headers(setup, person),
        json={"body": body, "request_key": str(key or uuid4())},
    )
    assert response.status_code == expect, response.text
    return response.json()


def comment(setup, project, person, subject_type, subject_id, body, *, expect=201):
    response = setup.client.post(
        project_root(setup, project) + f"/comments/{subject_type}/{subject_id}",
        headers=headers(setup, person),
        json={"body": body, "request_key": str(uuid4())},
    )
    assert response.status_code == expect, response.text
    return response.json()


def comments(setup, project, person, subject_type, subject_id, *, expect=200):
    response = setup.client.get(
        project_root(setup, project) + f"/comments/{subject_type}/{subject_id}",
        headers=headers(setup, person),
    )
    assert response.status_code == expect, response.text
    return response.json()


def thread(setup, project, person, thread_id, *, expect=200):
    response = setup.client.get(
        project_root(setup, project) + f"/discussions/{thread_id}", headers=headers(setup, person)
    )
    assert response.status_code == expect, response.text
    return response.json()


def topics(setup, project, person, *, expect=200):
    response = setup.client.get(
        project_root(setup, project) + "/discussions", headers=headers(setup, person)
    )
    assert response.status_code == expect, response.text
    return response.json()


def notes(setup, person, **query):
    response = setup.client.get(
        "/v1/personal/notifications", headers=headers(setup, person), params=query
    )
    assert response.status_code == 200, response.text
    return response.json()


def note_state(setup, person, action, ids=(), **extra):
    response = setup.client.post(
        "/v1/personal/notifications/state",
        headers=headers(setup, person),
        json={"notification_ids": [str(value) for value in ids], "action": action, **extra},
    )
    return response


def mention(person, name):
    return f"@[{name}](person:{person})"


def age_notifications(setup, person, minutes):
    """Move a person's notifications back in time (the merge window is a SQL clock)."""
    with Session(setup.admin) as s, s.begin():
        # Test-only clock move: the immutability guard is a trigger, skipped here.
        s.execute(text("SET LOCAL session_replication_role = replica"))
        s.execute(
            update(Notification)
            .where(Notification.tenant_id == setup.tenant, Notification.recipient_id == person)
            .values(
                first_at=Notification.first_at - timedelta(minutes=minutes),
                last_at=Notification.last_at - timedelta(minutes=minutes),
            )
        )


def all_notifications(setup, person):
    with Session(setup.admin) as s:
        return list(
            s.scalars(
                select(Notification)
                .where(Notification.tenant_id == setup.tenant, Notification.recipient_id == person)
                .order_by(Notification.change_seq)
            )
        )


def uuid(value):
    return value if isinstance(value, UUID) else UUID(str(value))
