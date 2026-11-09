"""Change a real project team through the owner's public command, as the product does."""

from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from pdos_next.domain.projects.models import Project


def _change(setup, project_id, change):
    with Session(setup.admin) as session:
        project = session.get(Project, UUID(str(project_id)))
        category, product, owner = project.category_id, project.product_id, project.owner_id
    path = f"/v1/categories/{category}/products/{product}/projects/{project_id}/team"
    headers = {"Authorization": f"Bearer {setup.tokens[owner]}"}
    team = setup.client.get(path, headers=headers)
    assert team.status_code == 200, team.text
    changed = setup.client.post(
        path,
        headers=headers,
        json={
            "expected_revision": team.json()["revision"],
            "request_key": str(uuid4()),
            "changes": [change],
        },
    )
    assert changed.status_code == 200, changed.text
    return changed.json()


def remove_member(setup, project_id, person):
    """The project owner removes one member (P34-1); returns the departed record.

    A private project's audience follows its members, so this is the only way a
    test may withdraw someone's project audience while keeping model access.
    """
    result = _change(setup, project_id, {"action": "remove", "principal_id": str(person)})
    return next(item for item in result["departed"] if item["principal_id"] == str(person))


def add_member(setup, project_id, person):
    """The project owner adds one person back without roles (P34-1).

    The counterpart of remove_member: the only way a test may give someone a
    project audience again.
    """
    return _change(setup, project_id, {"action": "add", "principal_id": str(person)})
