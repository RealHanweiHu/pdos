"""Change a real project team through the owner's public command, as the product does."""

from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from pdos_next.domain.projects.models import Project


def remove_member(setup, project_id, person):
    """The project owner removes one member (P34-1); returns the departed record.

    A private project's audience follows its members, so this is the only way a
    test may withdraw someone's project audience while keeping model access.
    """
    with Session(setup.admin) as session:
        project = session.get(Project, UUID(str(project_id)))
        category, product, owner = project.category_id, project.product_id, project.owner_id
    path = f"/v1/categories/{category}/products/{product}/projects/{project_id}/team"
    headers = {"Authorization": f"Bearer {setup.tokens[owner]}"}
    team = setup.client.get(path, headers=headers)
    assert team.status_code == 200, team.text
    removed = setup.client.post(
        path,
        headers=headers,
        json={
            "expected_revision": team.json()["revision"],
            "request_key": str(uuid4()),
            "changes": [{"action": "remove", "principal_id": str(person)}],
        },
    )
    assert removed.status_code == 200, removed.text
    return next(item for item in removed.json()["departed"] if item["principal_id"] == str(person))
