"""Superseded work leaves active queues without deleting its audit/history."""

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.schema import tables
from tests.test_my_work_api import (
    NOW,
    bearer_headers,
    bootstrap,
    client,  # noqa: F401
    isolated_my_work_database,  # noqa: F401
)


@pytest.mark.parametrize("status", ["pending_review", "accepted"])
def test_replaced_finding_leaves_queue_but_preserves_history(
    client: TestClient,  # noqa: F811
    isolated_my_work_database: str,  # noqa: F811
    status: str,
) -> None:
    seed = bootstrap(client, isolated_my_work_database)
    try:
        project = seed.project("REPLACED")["project_id"]
        first = seed.finding(project, title="Original suggestion")
        # Reuse the same actual run's invocation for a second independent candidate.
        with seed.engine.begin() as c:
            original = dict(
                c.execute(select(tables.findings).where(tables.findings.c.id == first))
                .mappings()
                .one()
            )

            second = uuid4()
            c.execute(
                tables.findings.insert().values(
                    **{
                        **{key: value for key, value in original.items() if value is not None},
                        "id": second,
                        "origin_key": str(second),
                        "title": "Other candidate",
                    }
                )
            )
            if status == "accepted":
                c.execute(
                    tables.findings.update()
                    .where(tables.findings.c.id == first)
                    .values(
                        status=status,
                        reviewed_by_user_id=seed.owner_id,
                        reviewed_at=NOW,
                        accepted_payload={"title": "Original suggestion"},
                    )
                )
        headers = bearer_headers(client, username="owner")
        before = client.get("/api/me/work?collection=findings&limit=1", headers=headers)
        assert before.status_code == 200, before.text
        assert before.json()["counts"]["findings"] == 2
        revision = before.json()["pages"]["findings"]["revision"]
        next_page = client.get(
            f"/api/me/work?collection=findings&offset=1&expected_revision={revision}",
            headers=headers,
        )
        assert next_page.status_code == 200, next_page.text
        assert len(next_page.json()["findings"]) == 1
        replacement = str(UUID(int=55))
        with seed.engine.begin() as c:
            c.execute(
                tables.agent_runs.update()
                .where(tables.agent_runs.c.id == original["run_id"])
                .values(run_context={"superseded_by": replacement})
            )
        current = client.get("/api/me/work?collection=findings", headers=headers)
        assert current.status_code == 200, current.text
        assert current.json()["counts"]["findings"] == 0
        assert current.json()["findings"] == []
        assert current.json()["pages"]["findings"]["revision"] != revision
        expired_page = client.get(
            f"/api/me/work?collection=findings&offset=1&expected_revision={revision}",
            headers=headers,
        )
        assert expired_page.status_code == 409, expired_page.text
        inbox = client.get("/api/ai/findings", headers=headers)
        assert inbox.status_code == 200, inbox.text
        assert inbox.json()["items"] == []
        history = client.get(f"/api/ai/findings/{first}", headers=headers)
        assert history.status_code == 200, history.text
        assert history.json()["status"] == status
        assert history.json()["superseded_by"] == replacement
        with seed.engine.connect() as c:
            assert c.execute(
                select(tables.findings.c.id).where(tables.findings.c.id.in_((first, second)))
            ).all()
    finally:
        seed.dispose()
