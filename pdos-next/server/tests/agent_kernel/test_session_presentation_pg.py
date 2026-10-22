"""Bounded actual P20 metadata transactions; only root executes PostgreSQL.

Run/Session creation and cancellation use the real controlled services, with no
worker, model, network or fabricated result. The one Project ACL reduction is a
precise isolated negative fixture, not a user-facing audience-revoke command.
"""

import json
import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from pdos_next.clock import using_clock
from pdos_next.database import tenant_session
from pdos_next.domain.preproject.models import (
    ProjectOpenItem,
    Proposal,
    ProposalDecision,
    ProposalItem,
    ProposalItemVersion,
    ProposalRevision,
    ProposalSubmission,
)
from pdos_next.domain.products.models import DefinitionRevision
from pdos_next.domain.projects.models import Project, ProjectProductLink
from pdos_next.errors import DomainError
from pdos_next.models import (
    Audit,
    Category,
    Confirmation,
    Grant,
    ObjectAudience,
    Outbox,
    Product,
    Receipt,
    RequestKey,
)
from pdos_next.safety import verify_test_target
from pdos_next.service import digest

# Initialize common business models before kernel children.
# isort: split
from pdos_next.agent_kernel.models import (
    AgentEvent,
    AgentInput,
    AgentRun,
    AgentSession,
    AgentToolCall,
)
from pdos_next.agent_kernel.persistence import cancel_run, create_run
from pdos_next.agent_kernel.session_presentation import PresentationInput, change
from pdos_next.agent_kernel.session_presentation_models import AgentSessionPresentation
from tests.g0_fixture import create_g0_project

PROTECTED_MODELS = (
    AgentSession,
    AgentRun,
    AgentEvent,
    AgentInput,
    AgentToolCall,
    Receipt,
    Audit,
    Outbox,
    RequestKey,
    Confirmation,
    Category,
    Product,
    Project,
    ProjectProductLink,
    DefinitionRevision,
    Proposal,
    ProposalItem,
    ProposalItemVersion,
    ProposalRevision,
    ProposalSubmission,
    ProposalDecision,
    ProjectOpenItem,
    Grant,
    ObjectAudience,
)


def _context(setup, *, personal=False, actor=None):
    principal = actor or setup.human
    return replace(
        setup.ctx,
        actor_id=principal,
        requester_id=principal,
        category_id=None if personal else setup.category,
    )


def _transaction(setup, ctx, *, read_snapshot=False):
    return tenant_session(
        setup.engine,
        ctx.tenant_id,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        category_id=ctx.category_id,
        read_snapshot=read_snapshot,
    )


def _protected_snapshot(setup):
    assert len({model.__tablename__ for model in PROTECTED_MODELS}) == len(PROTECTED_MODELS)
    with Session(setup.admin) as session:
        result = {}
        for model in PROTECTED_MODELS:
            rows = [
                digest(dict(row))
                for row in session.execute(
                    select(model.__table__)
                    .where(model.tenant_id == setup.tenant)
                    .order_by(model.id)
                ).mappings()
            ]
            result[model.__tablename__] = {"count": len(rows), "sha256": digest(rows)}
        return result


def _headers(setup, actor=None):
    return {"Authorization": f"Bearer {setup.tokens[actor or setup.human]}"}


def _base(setup, personal=False):
    return "/v1/personal" if personal else f"/v1/categories/{setup.category}"


def _read(setup, path, *, params=None, actor=None):
    query = params or {}
    response = setup.client.get(path, headers=_headers(setup, actor), params=query)
    return {
        "path": path,
        "params": query,
        "status_code": response.status_code,
        "body": response.json(),
    }


def _write(setup, path, data, *, actor=None):
    response = setup.client.post(path, headers=_headers(setup, actor), json=data)
    return {"path": path, "status_code": response.status_code, "body": response.json()}


def _presentation_rows(setup):
    with Session(setup.admin) as session:
        return [
            dict(row)
            for row in session.execute(
                select(AgentSessionPresentation.__table__)
                .where(AgentSessionPresentation.tenant_id == setup.tenant)
                .order_by(AgentSessionPresentation.session_id, AgentSessionPresentation.revision)
            ).mappings()
        ]


def _row(page, session_id):
    return next(item for item in page["items"] if item["session_id"] == session_id)


def _list(setup, *, personal=False, actor=None, **params):
    return _read(setup, _base(setup, personal) + "/agent-conversations", params=params, actor=actor)


def _presentation_path(setup, work, *, personal=False):
    return _base(setup, personal) + f"/agent-sessions/{work['session_id']}/presentation"


def _assert_receipt(setup, response, work, data, *, personal=False, actor=None):
    body = _ok(response)
    assert body["version"] == "agent-session-presentation/v1"
    assert body["principal_id"] == str(actor or setup.human)
    assert body["scope"] == {
        "category_id": None if personal else str(setup.category),
        "proposal_id": None,
    }
    assert body["session"] == {
        "session_id": work["session_id"],
        "category_id": None if personal else str(setup.category),
        "product_id": None if personal else str(setup.product),
        "proposal_id": None,
        "project_id": work.get("project_id"),
    }
    value = body["presentation"]
    assert UUID(value["id"])
    assert value["revision"] == data["expected_revision"] + 1
    assert value["action"] == data["action"] and value["request_key"] == data["request_key"]
    assert datetime.fromisoformat(value["created_at"]).tzinfo is not None
    return body


def _ok(read):
    assert read["status_code"] == 200, read["body"]
    return read["body"]


def _error(read, status, code):
    assert read["status_code"] == status, read["body"]
    assert read["body"]["code"] == code
    assert "items" not in read["body"]


def _real_run(setup, *, personal=False, actor=None, project=None, goal):
    ctx = _context(setup, personal=personal, actor=actor)
    with _transaction(setup, ctx) as session:
        run = create_run(
            session,
            ctx,
            goal=goal,
            writer_id=setup.agent,
            intent_key="p20-actual-run:" + str(uuid4()),
            product_id=setup.product if project else None,
            project_id=UUID(project) if project else None,
        )
        return {"run_id": str(run.id), "session_id": str(run.session_id)}


def _fixture(setup):
    verify_test_target(setup.admin)
    verify_test_target(setup.engine)
    project = create_g0_project(
        setup,
        visibility="category",
        name="Synthetic P20 owned project",
        purpose="Only session presentation metadata; no configuration or manufacturing chain",
    )
    instant = datetime.now(UTC)
    with using_clock(lambda: instant):
        personal = [
            _real_run(
                setup,
                personal=True,
                goal=f"Synthetic P20 original personal goal {index}; keep the original Run",
            )
            for index in (1, 2)
        ]
        category = _real_run(
            setup,
            project=project.project_id,
            goal="Synthetic P20 original owner project goal; never infer a business result",
        )
        peer = _real_run(
            setup,
            actor=setup.peer,
            project=project.project_id,
            goal="Synthetic P20 peer-owned session on the root-owned Project",
        )
    # One real cancellation supplies a nonempty immutable AgentEvent history;
    # no fake accepted event or worker transition is inserted by fixture SQL.
    with _transaction(setup, _context(setup, personal=True)) as session:
        result = cancel_run(session, _context(setup, personal=True), UUID(personal[0]["run_id"]))
        assert result["status"] == "cancelled"
    target, other = sorted(personal, key=lambda row: row["session_id"])
    category["project_id"] = peer["project_id"] = project.project_id
    return {
        "project": project,
        "personal": target,
        "other_personal": other,
        "category": category,
        "peer": peer,
    }


def _revoke_peer_project_fixture(setup, project_id):
    """Narrow exactly one synthetic Project, retaining its actual lifecycle clock."""
    verify_test_target(setup.admin)
    with Session(setup.admin) as session, session.begin():

        def rows(model):
            return {
                row["id"]: dict(row)
                for row in session.execute(
                    select(model.__table__)
                    .where(model.tenant_id == setup.tenant)
                    .order_by(model.id)
                ).mappings()
            }

        models = (Project, Product, ObjectAudience)
        before = {model.__tablename__: rows(model) for model in models}
        project = session.scalar(
            select(Project).where(
                Project.tenant_id == setup.tenant,
                Project.category_id == setup.category,
                Project.product_id == setup.product,
                Project.id == UUID(project_id),
                Project.owner_id == setup.human,
                Project.visibility == "category",
            )
        )
        assert project is not None and project.owner_id != setup.peer
        product = session.get(Product, setup.product)
        assert product is not None and product.visibility == "category"
        assert project.product_id == product.id
        expected = {
            table: {identity: dict(row) for identity, row in values.items()}
            for table, values in before.items()
        }
        expected[Project.__tablename__][project.id]["visibility"] = "private"
        # The existing lifecycle_reference trigger on Project UPDATE increments
        # only its Product's derived clock. Do not disable or undo that guard.
        expected[Product.__tablename__][product.id]["lifecycle_epoch"] += 1
        audience_ids = {
            identity
            for identity, row in before[ObjectAudience.__tablename__].items()
            if row["category_id"] == setup.category
            and row["object_type"] == "projects"
            and row["subject_id"] == project.id
            and row["owner_id"] == setup.human
            and row["principal_id"] == setup.peer
        }
        for identity in audience_ids:
            del expected[ObjectAudience.__tablename__][identity]
        project.visibility = "private"
        session.flush()
        removed = session.execute(
            delete(ObjectAudience).where(
                ObjectAudience.tenant_id == setup.tenant,
                ObjectAudience.category_id == setup.category,
                ObjectAudience.object_type == "projects",
                ObjectAudience.subject_id == project.id,
                ObjectAudience.owner_id == setup.human,
                ObjectAudience.principal_id == setup.peer,
            )
        )
        assert removed.rowcount == len(audience_ids)
        after = {model.__tablename__: rows(model) for model in models}
        assert after == expected
        changed_tables = {
            Project.__tablename__,
            Product.__tablename__,
            *({ObjectAudience.__tablename__} if audience_ids else set()),
        }
        assert {table for table in before if before[table] != after[table]} == changed_tables
        changed_rows = []
        for table in before:
            for identity in before[table]:
                previous, current = before[table][identity], after[table].get(identity)
                if previous == current:
                    continue
                changed_rows.append(
                    {
                        "table": table,
                        "id": str(identity),
                        "operation": "delete" if current is None else "update",
                        "changed_fields": sorted(
                            key
                            for key in previous
                            if current is not None and previous[key] != current[key]
                        ),
                        "before_sha256": digest(previous),
                        "after_sha256": digest(current) if current is not None else None,
                    }
                )
        return {
            "nature": "synthetic ACL reduction with the existing lifecycle_reference trigger",
            "changed_tables": sorted(changed_tables),
            "changes": changed_rows,
            "row_hashes": {
                table: {
                    "before": {
                        str(identity): digest(row) for identity, row in before[table].items()
                    },
                    "after": {str(identity): digest(row) for identity, row in after[table].items()},
                }
                for table in before
            },
            "project_visibility": {"before": "category", "after": "private"},
            "product_lifecycle_epoch": {
                "product_id": str(product.id),
                "before": before[Product.__tablename__][product.id]["lifecycle_epoch"],
                "after": after[Product.__tablename__][product.id]["lifecycle_epoch"],
            },
            "removed_peer_audience_ids": sorted(str(identity) for identity in audience_ids),
        }


def _export(setup, work, phases, commands, checks):
    destination = os.environ.get("PDOS_UI_SESSION_PRESENTATION_EXPORT")
    if not destination:
        return
    output = Path(destination)
    assert output.is_absolute(), "Presentation export destination must be absolute"
    bundle = {
        "version": "session-presentation-projection-qa/v1",
        "fixture_nature": (
            "actual controlled create_run/cancel_run and authenticated HTTP over synthetic G0"
        ),
        "scope": {
            "tenant_id": str(setup.tenant),
            "category_id": str(setup.category),
            "product_id": str(setup.product),
            "project_id": work["project"].project_id,
            "principal_id": str(setup.human),
            "peer_principal_id": str(setup.peer),
            "foreign_principal_id": str(setup.other_human),
            "principal_ids_source": "actual test request contexts, not a server identity echo",
            **{key: work[key] for key in ("personal", "other_personal", "category", "peer")},
        },
        "phases": phases,
        "command_receipts": commands,
        "guard_checks": checks,
        "limitations": [
            "Only root executes against a freshly verified explicit isolated pdos_test target",
            "G0 is four actual public commands with synthetic human review; no real qualification",
            "Run creation/cancellation use actual services; no HTTP Start coverage",
            "No model, worker, Temporal, business configuration, Field or S2 chain executes",
            "Metadata actions must preserve all 24 explicit protected model row counts and digests",
            "AI rejection uses an actual service Context403; no authenticated AI HTTP coverage",
            "Project ACL reduction is a narrow negative fixture, not a user-facing revoke command",
            "No deletion, business approval, external send, production or formal stage acceptance",
        ],
    }
    encoded = json.dumps(bundle, ensure_ascii=False, indent=2)
    assert not any(token in encoded for token in setup.tokens.values())
    assert "Bearer " not in encoded
    assert "confirmation_token" not in encoded and "approval_token" not in encoded
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(encoded + "\n", encoding="utf-8")


def test_actual_owner_metadata_replay_pagination_archive_and_current_parent_acl(setup):
    work = _fixture(setup)
    before = _protected_snapshot(setup)
    assert before[AgentSession.__tablename__]["count"] == 4
    assert before[AgentRun.__tablename__]["count"] == 4
    assert before[AgentEvent.__tablename__]["count"] > 0
    assert before[Receipt.__tablename__]["count"] == 4
    assert _presentation_rows(setup) == []
    phases, commands, checks = {}, [], {}
    personal, other, category, peer = (
        work[key] for key in ("personal", "other_personal", "category", "peer")
    )
    personal_path = _presentation_path(setup, personal, personal=True)
    category_path = _presentation_path(setup, category)
    peer_path = _presentation_path(setup, peer)

    # Existing reads provide the unchanged Run heads; defaults are server facts.
    phases["legacy_personal"] = _read(setup, _base(setup, True) + "/agent-sessions")
    legacy = _ok(phases["legacy_personal"])
    phases["default_personal"] = _list(setup, personal=True)
    page = _ok(phases["default_personal"])
    assert page["version"] == "agent-conversation-list/v1"
    assert page["principal_id"] == str(setup.human)
    assert page["scope"] == {"category_id": None, "proposal_id": None}
    assert [row["session_id"] for row in page["items"]] == [
        other["session_id"],
        personal["session_id"],
    ]
    for row in page["items"]:
        assert row["presentation"] == {
            "id": None,
            "revision": 0,
            "title": None,
            "pinned": False,
            "archived": False,
            "created_at": None,
        }
        previous = _row(legacy, row["session_id"])
        assert row["latest_run"] == previous["latest_run"]
        assert row["revision"] == previous["revision"]
        assert row["run_count"] == previous["run_count"] == 1
        assert row["scope"] == {
            "category_id": None,
            "product_id": None,
            "proposal_id": None,
            "project_id": None,
        }
    assert _ok(_list(setup, personal=True, view="archived"))["items"] == []
    phases["default_category"] = _list(setup)
    category_row = _row(_ok(phases["default_category"]), category["session_id"])
    assert category_row["scope"] == {
        "category_id": str(setup.category),
        "product_id": str(setup.product),
        "proposal_id": None,
        "project_id": work["project"].project_id,
    }
    assert category_row["latest_run"]["run_id"] == category["run_id"]

    title = "Synthetic P20 custom title %_\\ literal"
    rename = {
        "expected_revision": 0,
        "request_key": str(uuid4()),
        "action": "rename",
        "title": title,
    }
    renamed = _write(setup, personal_path, rename)
    rename_receipt = _assert_receipt(setup, renamed, personal, rename, personal=True)
    commands.append(renamed)
    pin = {"expected_revision": 1, "request_key": str(uuid4()), "action": "pin"}
    pinned = _write(setup, personal_path, pin)
    pin_receipt = _assert_receipt(setup, pinned, personal, pin, personal=True)
    commands.append(pinned)
    assert pin_receipt["presentation"]["title"] == title
    assert pin_receipt["presentation"]["pinned"] is True
    at_revision_two = _presentation_rows(setup)
    assert len(at_revision_two) == 2

    phases["pinned_first_page"] = _list(setup, personal=True, page_size=1)
    first_page = _ok(phases["pinned_first_page"])
    assert [row["session_id"] for row in first_page["items"]] == [personal["session_id"]]
    actual_cursor = first_page["next_cursor"]
    assert actual_cursor == personal["session_id"]
    phases["pinned_next_page"] = _list(setup, personal=True, page_size=1, cursor=actual_cursor)
    next_page = _ok(phases["pinned_next_page"])
    assert [row["session_id"] for row in next_page["items"]] == [other["session_id"]]
    assert next_page["next_cursor"] is None

    # A replay with original expected_revision=0 must return v1, while current stays v2.
    replay = _write(setup, personal_path, rename)
    recovered = _read(setup, personal_path + "/requests/" + rename["request_key"])
    assert _ok(replay) == _ok(recovered) == rename_receipt
    commands.extend((replay, recovered))
    current = _row(_ok(_list(setup, personal=True)), personal["session_id"])["presentation"]
    assert current["id"] == pin_receipt["presentation"]["id"] and current["revision"] == 2
    conflict = _write(setup, personal_path, {**rename, "title": "Changed original request"})
    _error(conflict, 409, "DUPLICATE_INTENT_CONFLICT")
    stale = _write(setup, personal_path, {**rename, "request_key": str(uuid4())})
    _error(stale, 409, "VERSION_CONFLICT")
    checks["changed_request_key"], checks["stale_revision"] = conflict, stale
    assert _presentation_rows(setup) == at_revision_two

    phases["custom_title_search"] = _list(setup, personal=True, q="%_\\")
    found = _ok(phases["custom_title_search"])
    assert [row["session_id"] for row in found["items"]] == [personal["session_id"]]
    assert found["items"][0]["matched_run"] is None
    assert found["items"][0]["presentation"]["title"] == title
    assert (
        _ok(_list(setup, personal=True, q=personal["run_id"]))["items"][0]["matched_run"][
            "match_kind"
        ]
        == "run_id"
    )

    archive = {"expected_revision": 2, "request_key": str(uuid4()), "action": "archive"}
    archived = _write(setup, personal_path, archive)
    _assert_receipt(setup, archived, personal, archive, personal=True)
    commands.append(archived)
    phases["archived_active"] = _list(setup, personal=True)
    assert [row["session_id"] for row in _ok(phases["archived_active"])["items"]] == [
        other["session_id"]
    ]
    phases["archived_view"] = _list(setup, personal=True, view="archived")
    archived_page = _ok(phases["archived_view"])
    assert [row["session_id"] for row in archived_page["items"]] == [personal["session_id"]]
    assert archived_page["items"][0]["presentation"]["archived"] is True
    checks["old_active_anchor"] = _list(setup, personal=True, cursor=actual_cursor)
    _error(checks["old_active_anchor"], 403, "FORBIDDEN_SCOPE")
    phases["archived_original_run"] = _read(
        setup, _base(setup, True) + f"/agent-runs/{personal['run_id']}"
    )
    assert _ok(phases["archived_original_run"])["run_id"] == personal["run_id"]

    restore = {"expected_revision": 3, "request_key": str(uuid4()), "action": "restore"}
    restored = _write(setup, personal_path, restore)
    _assert_receipt(setup, restored, personal, restore, personal=True)
    commands.append(restored)
    phases["restored_active"] = _list(setup, personal=True)
    restored_row = _row(_ok(phases["restored_active"]), personal["session_id"])
    assert restored_row["presentation"]["archived"] is False
    assert restored_row["presentation"]["pinned"] is True
    assert _ok(_list(setup, personal=True, view="archived"))["items"] == []
    for data in (
        {"expected_revision": 4, "request_key": str(uuid4()), "action": "unpin"},
        {"expected_revision": 5, "request_key": str(uuid4()), "action": "rename", "title": None},
    ):
        result = _write(setup, personal_path, data)
        _assert_receipt(setup, result, personal, data, personal=True)
        commands.append(result)
    phases["restored_default_title"] = _list(setup, personal=True)
    final_personal = _row(_ok(phases["restored_default_title"]), personal["session_id"])
    assert final_personal["presentation"]["revision"] == 6
    assert final_personal["presentation"]["title"] is None
    assert final_personal["presentation"]["pinned"] is False

    category_rename = {
        "expected_revision": 0,
        "request_key": str(uuid4()),
        "action": "rename",
        "title": "Synthetic owner category conversation",
    }
    category_result = _write(setup, category_path, category_rename)
    _assert_receipt(setup, category_result, category, category_rename)
    commands.append(category_result)
    peer_rename = {
        "expected_revision": 0,
        "request_key": str(uuid4()),
        "action": "rename",
        "title": "Synthetic peer private conversation",
    }
    peer_result = _write(setup, peer_path, peer_rename, actor=setup.peer)
    _assert_receipt(setup, peer_result, peer, peer_rename, actor=setup.peer)
    commands.append(peer_result)
    phases["peer_own_category"] = _list(setup, actor=setup.peer)
    assert [row["session_id"] for row in _ok(phases["peer_own_category"])["items"]] == [
        peer["session_id"]
    ]
    assert _ok(_list(setup, personal=True, actor=setup.peer))["items"] == []
    phases["foreign_personal"] = _list(setup, personal=True, actor=setup.other_human)
    assert _ok(phases["foreign_personal"])["items"] == []
    checks["foreign_category"] = _list(setup, actor=setup.other_human)
    _error(checks["foreign_category"], 403, "FORBIDDEN_SCOPE")
    for name, actor, path in (
        ("peer_owner_write", setup.peer, category_path),
        ("foreign_owner_write", setup.other_human, personal_path),
        (
            "wrong_scope_write",
            setup.human,
            _base(setup, True) + f"/agent-sessions/{category['session_id']}/presentation",
        ),
    ):
        checks[name] = _write(setup, path, category_rename, actor=actor)
        _error(checks[name], 404, "NOT_FOUND")
    checks["peer_owner_recovery"] = _read(
        setup, category_path + "/requests/" + category_rename["request_key"], actor=setup.peer
    )
    _error(checks["peer_owner_recovery"], 404, "NOT_FOUND")
    checks["unknown_owner_request"] = _read(setup, personal_path + "/requests/" + str(uuid4()))
    _error(checks["unknown_owner_request"], 404, "NOT_FOUND")
    ai_ctx = replace(_context(setup, personal=True), actor_id=setup.agent)
    with pytest.raises(DomainError) as rejected, _transaction(setup, ai_ctx) as session:
        change(session, ai_ctx, UUID(personal["session_id"]), PresentationInput(**rename))
    assert rejected.value.status == 403 and rejected.value.code == "FORBIDDEN_SCOPE"
    checks["ai_service_transaction"] = {
        "status_code": rejected.value.status,
        "body": rejected.value.payload(),
        "transport": "actual service transaction; no AI login fixture",
    }

    metadata_rows = _presentation_rows(setup)
    assert len(metadata_rows) == 8
    assert all(row in metadata_rows for row in at_revision_two)
    for target, expected in ((personal, 6), (category, 1), (peer, 1)):
        history = [row for row in metadata_rows if str(row["session_id"]) == target["session_id"]]
        assert [row["revision"] for row in history] == list(range(1, expected + 1))
        assert history[0]["previous_id"] is None
        for previous, current in zip(history, history[1:], strict=False):
            assert current["previous_id"] == previous["id"]
    after_metadata = _protected_snapshot(setup)
    assert after_metadata == before
    checks["protected_metadata_boundary"] = {"before": before, "after": after_metadata}

    # Parent ACL reduction is separate from the metadata preservation boundary.
    peer_run_path = _base(setup) + f"/agent-runs/{peer['run_id']}"
    phases["peer_run_before_acl"] = _read(setup, peer_run_path, actor=setup.peer)
    assert _ok(phases["peer_run_before_acl"])["run_id"] == peer["run_id"]
    fixture_proof = _revoke_peer_project_fixture(setup, work["project"].project_id)
    after_acl = _protected_snapshot(setup)
    changed = {name for name in before if before[name] != after_acl[name]}
    assert changed == set(fixture_proof["changed_tables"])
    assert before[Project.__tablename__]["count"] == after_acl[Project.__tablename__]["count"]
    checks["acl_negative_fixture"] = fixture_proof
    phases["peer_after_acl"] = _list(setup, actor=setup.peer)
    assert _ok(phases["peer_after_acl"])["items"] == []
    # s0_0793 restrictive parent RLS hides the Session before _target can
    # inspect it; presentation deliberately returns NOT_FOUND for that result.
    # The existing Run endpoint has its own explicit FORBIDDEN_SCOPE response.
    for name, result, status, code in (
        (
            "peer_old_request_after_acl",
            _write(setup, peer_path, peer_rename, actor=setup.peer),
            404,
            "NOT_FOUND",
        ),
        (
            "peer_recovery_after_acl",
            _read(setup, peer_path + "/requests/" + peer_rename["request_key"], actor=setup.peer),
            404,
            "NOT_FOUND",
        ),
        (
            "peer_new_request_after_acl",
            _write(
                setup,
                peer_path,
                {
                    "expected_revision": 1,
                    "request_key": str(uuid4()),
                    "action": "pin",
                },
                actor=setup.peer,
            ),
            404,
            "NOT_FOUND",
        ),
        (
            "peer_run_after_acl",
            _read(setup, peer_run_path, actor=setup.peer),
            403,
            "FORBIDDEN_SCOPE",
        ),
    ):
        checks[name] = result
        _error(result, status, code)
    phases["owner_after_acl"] = _list(setup)
    assert (
        _row(_ok(phases["owner_after_acl"]), category["session_id"])["scope"]["project_id"]
        == work["project"].project_id
    )
    assert _ok(_read(setup, category_path + "/requests/" + category_rename["request_key"])) == (
        _ok(category_result)
    )
    after_denials = _protected_snapshot(setup)
    assert after_denials == after_acl
    assert _presentation_rows(setup) == metadata_rows
    checks["protected_acl_boundary"] = {
        "fixture_changes_only": sorted(changed),
        "before_metadata_denials": after_acl,
        "after_metadata_denials": after_denials,
    }
    checks["presentation_history"] = {
        "count": len(metadata_rows),
        "sha256": digest(metadata_rows),
        "revisions": {personal["session_id"]: 6, category["session_id"]: 1, peer["session_id"]: 1},
    }
    _export(setup, work, phases, commands, checks)
