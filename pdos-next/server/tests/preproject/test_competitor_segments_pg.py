"""Fixed competitor segment assignments through actual knowledge HTTP commands.

Only ordinary synthetic category/ACL setup uses the fixture admin. Knowledge,
supersession, withdrawal and promotion use existing commands; root alone runs PG.
"""
# ruff: noqa: F811 -- pytest injects the imported real G0 fixture.

import json
import os
from copy import copy, deepcopy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pdos_next.domain.preproject.category_models import (
    KnowledgeCurrent,
    KnowledgeEntry,
    PromotionProof,
)
from pdos_next.domain.preproject.schemas import Reference
from pdos_next.models import Category, Grant, RequestKey, now
from tests.preproject.test_category_context_pg import add_knowledge
from tests.preproject.test_category_matrix_pg import counts, matrix
from tests.preproject.test_evidence_commands_pg import artifact, record_claim, withdraw_request
from tests.preproject.test_g0 import create, post, request, save
from tests.preproject.test_g0 import work as work
from tests.preproject.test_proposal_views_pg import named_source, other_category


def business_counts(work):
    with Session(work.admin) as session:
        extra = {
            model.__tablename__: session.scalar(
                select(func.count()).select_from(model).where(model.tenant_id == work.tenant)
            )
            for model in (PromotionProof, RequestKey)
        }
    return {**counts(work), **extra}


def assignment(work, identity, *, actor=None, category=None):
    return work.client.get(
        f"/v1/categories/{category or work.category}/competitors/{identity}/segment-assignment",
        headers={"Authorization": f"Bearer {work.tokens[actor or work.human]}"},
    )


def successful(work, entry, **scope):
    response = assignment(work, entry["entry_id"], **scope)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["version"] == "competitor-segment-assignment/v1"
    assert data["category_id"] == str(work.category)
    assert data["principal_id"] == str(scope.get("actor") or work.human)
    assert data["as_of"]
    assert data["competitor"]["id"] == entry["entry_id"]
    assert data["competitor"]["lineage_id"] == entry["lineage_id"]
    assert data["competitor"]["version"] == entry["version"]
    assert set(data["competitor"]) == {
        "id",
        "lineage_id",
        "version",
        "origin",
        "writer_id",
        "run_id",
        "confirmed_by",
        "content",
        "regions",
        "source_refs",
    }
    assert isinstance(data["can_edit"], bool) and isinstance(data["blockers"], list)
    for row in data["selected_segments"]:
        assert set(row) == {"entry_id", "version", "lineage_id", "label", "status", "source_refs"}
    for row in data["segments"]:
        assert set(row) == {"entry_id", "version", "lineage_id", "label", "source_refs"}
    return data


def segment(work, label="合成汽车应急细分", **changes):
    return add_knowledge(work, kind="segment", content={"segment": label}, **changes)


def ref(entry):
    return {"entry_id": entry["entry_id"], "version": entry["version"]}


def competitor_content(work, model="合成竞品便携款", **changes):
    return {
        "brand": "合成品牌",
        "model": model,
        "prices": [
            {
                "amount": "150.000000000001",
                "currency": "CNY",
                "observed_on": "2026-10-17",
                "price_type": "retail",
                "includes_tax": True,
                "source_ref": named_source(work),
            }
        ],
        **changes,
    }


def competitor(work, **changes):
    return add_knowledge(work, kind="competitor", content=competitor_content(work, **changes))


def edit_request(work, current, refs, *, source_refs=()):
    base = current["competitor"]
    assert base["content"] is not None
    return request(
        work,
        "category.knowledge.add",
        {
            "kind": "competitor",
            "content": {**deepcopy(base["content"]), "segment_refs": refs},
            "regions": base["regions"],
            "source_refs": list(source_refs),
            "supersedes": {"lineage_id": base["lineage_id"], "expected_version": base["version"]},
        },
    )


def edit(work, current, refs, **changes):
    receipt, command = save(work, edit_request(work, current, refs, **changes))
    return receipt["result"], receipt, command


def competitor_points(data, identity):
    return [
        (group, row, cell, point)
        for group in data["groups"]
        for row in group["rows"]
        for cell in row["cells"]
        for point in cell["competitors"]
        if point["subject"]["id"] == identity
    ]


def projected(work):
    response = matrix(work)
    assert response.status_code == 200, response.text
    return response.json()


def unavailable(work, entry, refs):
    before = business_counts(work)
    command = edit_request(work, successful(work, entry), refs)
    for preview in (True, False):
        response = post(work, command, preview=preview)
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "SOURCE_UNAVAILABLE"
        assert response.json()["detail"]["reason"] == "competitor_segment_unavailable"
    assert business_counts(work) == before


def test_http_segment_assignment_append_matrix_exact_price_replay_history_and_readonly(work):
    target = segment(work)
    original = competitor(work)
    read_before = business_counts(work)
    initial = successful(work, original)
    assert initial["can_edit"] is True and initial["selected_segments"] == []
    assert initial["competitor"]["origin"] == "human"
    with Session(work.admin) as session:
        old = session.get(KnowledgeEntry, UUID(original["entry_id"]))
        old_content, old_sources = deepcopy(old.content), deepcopy(old.source_refs)
        assert not session.scalar(
            select(Grant.product_manager).where(
                Grant.category_id == work.category,
                Grant.principal_id == work.human,
            )
        )
    assert business_counts(work) == read_before
    candidate = post(
        work,
        edit_request(
            work, initial, [ref(target)], source_refs=initial["competitor"]["source_refs"]
        ),
        preview=True,
    )
    assert candidate.status_code == 200, candidate.text
    preview_token = candidate.json().get("confirmation_token")
    assert isinstance(preview_token, str) and len(preview_token) >= 20
    assert candidate.json()["command"]["payload"]["confirmation_token"] == preview_token
    response = post(work, candidate.json()["command"])
    assert response.status_code == 200, response.text
    receipt = response.json()
    current = receipt["result"]
    assert current["lineage_id"] == original["lineage_id"] and current["version"] == 2
    data = successful(work, current)
    assert data["competitor"]["content"]["segment_refs"] == [ref(target)]
    assert data["selected_segments"][0]["entry_id"] == target["entry_id"]
    assert data["selected_segments"][0]["status"] == "available"
    before = business_counts(work)
    view = projected(work)
    [(group, row, cell, point)] = competitor_points(view, current["entry_id"])
    assert cell["band_id"] == "band:1"
    assert Decimal(point["price"]["amount"]) == Decimal("150.000000000001")
    assert group["basis"]["currency"] == "CNY" and group["basis"]["basis"] == "retail"
    assert row["segment"]["entry_id"] == target["entry_id"] and row["segment"]["version"] == 1
    assert competitor_points(view, original["entry_id"]) == []
    replay = post(work, candidate.json()["command"])
    assert replay.status_code == 200 and replay.json()["id"] == receipt["id"]
    assert business_counts(work) == before
    with Session(work.admin) as session:
        old = session.get(KnowledgeEntry, UUID(original["entry_id"]))
        new = session.get(KnowledgeEntry, UUID(current["entry_id"]))
        assert old.content == old_content and old.source_refs == old_sources
        assert {**new.content, "segment_refs": []} == {**old.content, "segment_refs": []}
        assert new.source_refs == old.source_refs
        assert all(source.get("id") != target["entry_id"] for source in new.source_refs)


def test_http_competitor_source_roundtrip_preserves_explicit_and_nested_duplicate_counts(work):
    target = segment(work)
    shared = Reference.model_validate(named_source(work)).model_dump(mode="json")
    distinct = {**shared, "statement": "合成第二条具名说明；重复引用保留次数与顺序。"}
    explicit = [shared, distinct, shared]
    original = add_knowledge(
        work,
        kind="competitor",
        content=competitor_content(work),
        source_refs=explicit,
    )
    initial = successful(work, original)
    assert initial["competitor"]["source_refs"] == explicit
    assert initial["competitor"]["content"]["prices"][0]["source_ref"] == shared
    with Session(work.admin) as session:
        old = session.get(KnowledgeEntry, UUID(original["entry_id"]))
        old_content, old_sources = deepcopy(old.content), deepcopy(old.source_refs)
    assert old_sources == [shared, distinct, shared, shared]
    current, _, _ = edit(
        work,
        initial,
        [ref(target)],
        source_refs=initial["competitor"]["source_refs"],
    )
    refreshed = successful(work, current)
    assert refreshed["competitor"]["source_refs"] == explicit
    with Session(work.admin) as session:
        old = session.get(KnowledgeEntry, UUID(original["entry_id"]))
        new = session.get(KnowledgeEntry, UUID(current["entry_id"]))
        assert old.content == old_content and old.source_refs == old_sources
        assert new.content == {**old_content, "segment_refs": [ref(target)]}
        assert new.source_refs == old_sources
        assert new.source_refs.count(shared) == 3 and new.source_refs.count(distinct) == 1


def test_http_segment_assignment_keeps_old_version_then_withdraws_reassigns_and_clears(work):
    old = segment(work, "SYNTHETIC_FIXED_OLD_SEGMENT")
    replacement = segment(work, "合成新适用细分")
    entry = competitor(work, segment_refs=[ref(old)])
    newer = segment(
        work,
        "SYNTHETIC_CURRENT_NEW_SEGMENT_NAME",
        supersedes={"lineage_id": old["lineage_id"], "expected_version": 1},
    )
    data = successful(work, entry)
    [selected] = data["selected_segments"]
    assert selected["entry_id"] == old["entry_id"] and selected["version"] == 1
    assert selected["label"] == "SYNTHETIC_FIXED_OLD_SEGMENT" and selected["status"] == "available"
    assert newer["entry_id"] in {option["entry_id"] for option in data["segments"]}
    [(_, row, _, _)] = competitor_points(projected(work), entry["entry_id"])
    assert row["segment"]["label"] == selected["label"] and row["segment"]["version"] == 1
    save(
        work,
        request(
            work,
            "category.knowledge.withdraw",
            {
                "lineage_id": old["lineage_id"],
                "expected_version": 2,
                "reason": "合成细分撤回重研",
            },
        ),
    )
    invalid = successful(work, entry)
    [selected] = invalid["selected_segments"]
    assert selected["status"] == "unavailable" and selected["label"] is None
    assert selected["source_refs"] == [] and invalid["can_edit"] is True
    view = projected(work)
    assert competitor_points(view, entry["entry_id"]) == []
    assert "SYNTHETIC_FIXED_OLD_SEGMENT" not in json.dumps(view)
    assert "SYNTHETIC_CURRENT_NEW_SEGMENT_NAME" not in json.dumps(view)
    changed, _, _ = edit(work, invalid, [ref(replacement)])
    assert len(competitor_points(projected(work), changed["entry_id"])) == 1
    cleared, _, _ = edit(work, successful(work, changed), [])
    assert successful(work, cleared)["selected_segments"] == []
    assert competitor_points(projected(work), cleared["entry_id"]) == []


def test_http_segment_assignment_rejects_wrong_fixed_versions_kinds_and_duplicates_atomically(work):
    target = segment(work)
    wrong_kind = add_knowledge(work)
    entry = competitor(work)
    for refs in (
        [{"entry_id": target["entry_id"], "version": 99}],
        [ref(wrong_kind)],
        [{"entry_id": str(uuid4()), "version": 1}],
    ):
        unavailable(work, entry, refs)
    for refs in ([ref(target), ref(target)], [{"entry_id": target["entry_id"], "version": 0}]):
        before = business_counts(work)
        response = post(work, edit_request(work, successful(work, entry), refs), preview=True)
        assert response.status_code == 422 and response.json()["code"] == "VALIDATION_FAILED"
        assert business_counts(work) == before


def test_http_segment_assignment_supersedes_rejects_lost_update_without_overwriting_history(work):
    first, second = segment(work, "合成细分甲"), segment(work, "合成细分乙")
    original = competitor(work)
    old = successful(work, original)
    candidate = post(work, edit_request(work, old, [ref(first)]), preview=True)
    assert candidate.status_code == 200, candidate.text
    current, _, winning = edit(work, old, [ref(second)])
    before = business_counts(work)
    stale = post(work, candidate.json()["command"])
    assert stale.status_code == 409 and stale.json()["code"] == "VERSION_CONFLICT"
    assert business_counts(work) == before
    moved = assignment(work, original["entry_id"])
    assert moved.status_code == 409
    assert moved.json()["detail"]["reason"] == "competitor_version_moved"
    assert successful(work, current)["competitor"]["content"]["segment_refs"] == [ref(second)]
    cleared, _, _ = edit(work, successful(work, current), [])
    replay = post(work, winning)
    assert replay.status_code == 200, replay.text
    with Session(work.admin) as session:
        pointer = session.get(KnowledgeCurrent, (work.tenant, UUID(original["lineage_id"])))
        assert str(pointer.current_entry_id) == cleared["entry_id"] and pointer.current_version == 3
        history = list(
            session.scalars(
                select(KnowledgeEntry)
                .where(
                    KnowledgeEntry.tenant_id == work.tenant,
                    KnowledgeEntry.lineage_id == UUID(original["lineage_id"]),
                )
                .order_by(KnowledgeEntry.version)
            )
        )
        assert [row.version for row in history] == [1, 2, 3]
        assert history[1].content["segment_refs"] == [ref(second)]
        assert history[2].content["segment_refs"] == []


def test_http_segment_assignment_category_tenant_and_current_write_acl_are_enforced(work):
    entry = competitor(work)
    other = copy(work)
    other.category = UUID(other_category(work))
    other.ctx = replace(work.ctx, category_id=other.category)
    cross_category = segment(other, "SYNTHETIC_OTHER_CATEGORY_SEGMENT")
    unavailable(work, entry, [ref(cross_category)])
    assert assignment(work, entry["entry_id"], category=other.category).status_code == 404
    foreign = copy(work)
    foreign.tenant, foreign.human, foreign.category = work.other_tenant, work.other_human, uuid4()
    foreign.headers = {"Authorization": f"Bearer {work.tokens[work.other_human]}"}
    foreign.ctx = replace(
        work.ctx,
        tenant_id=foreign.tenant,
        actor_id=foreign.human,
        requester_id=foreign.human,
        category_id=foreign.category,
    )
    with Session(work.admin) as session, session.begin():
        session.add(
            Category(
                id=foreign.category,
                tenant_id=foreign.tenant,
                owner_id=foreign.human,
                name="合成其他租户品类",
                purpose="隔离知识引用测试",
            )
        )
        session.flush()
        session.add(
            Grant(
                tenant_id=foreign.tenant,
                category_id=foreign.category,
                principal_id=foreign.human,
                can_write=True,
            )
        )
    cross_tenant = segment(foreign, "SYNTHETIC_OTHER_TENANT_SEGMENT")
    unavailable(work, entry, [ref(cross_tenant)])
    assert assignment(work, entry["entry_id"], actor=work.other_human).status_code == 403
    readonly = successful(work, entry, actor=work.peer)
    assert readonly["can_edit"] is False
    before = business_counts(work)
    denied = post(work, edit_request(work, readonly, []), actor=work.peer)
    assert denied.status_code == 403, denied.text
    assert business_counts(work) == before
    with Session(work.admin) as session, session.begin():
        grant = session.scalar(
            select(Grant).where(Grant.category_id == work.category, Grant.principal_id == work.peer)
        )
        grant.expires_at = now() - timedelta(seconds=1)
    assert assignment(work, entry["entry_id"], actor=work.peer).status_code == 403
    assert assignment(work, str(uuid4())).status_code == 404
    assert assignment(work, cross_category["entry_id"]).status_code == 404


def test_http_segment_source_withdrawal_redacts_selected_label_and_allows_safe_clear(work):
    quote = "SYNTHETIC_WITHDRAWN_SEGMENT_SOURCE_QUOTE"
    source = artifact(work, body=quote)
    claim = record_claim(work, source, quote=quote, text="合成可撤回细分依据")
    claim_ref = {
        "type": "claim",
        "id": claim["subject_id"],
        "version": 1,
        "line": 1,
        "quote": quote,
    }
    target = segment(work, "SYNTHETIC_WITHDRAWN_SEGMENT_LABEL", source_refs=[claim_ref])
    entry = competitor(work, segment_refs=[ref(target)])
    sourced = add_knowledge(
        work,
        kind="competitor",
        content=competitor_content(work, model="SYNTHETIC_WITHDRAWN_COMPETITOR_BODY"),
        source_refs=[claim_ref],
    )
    assert successful(work, entry)["can_edit"] is True
    save(work, withdraw_request(work, claim["subject_id"]))
    invalid = successful(work, entry)
    assert invalid["can_edit"] is True and invalid["competitor"]["content"] is not None
    [selected] = invalid["selected_segments"]
    assert selected["label"] is None and selected["source_refs"] == []
    assert selected["status"] == "unavailable"
    assert target["entry_id"] not in {option["entry_id"] for option in invalid["segments"]}
    assert quote not in json.dumps(invalid)
    assert "SYNTHETIC_WITHDRAWN_SEGMENT_LABEL" not in json.dumps(invalid)
    unavailable(work, entry, [ref(target)])
    view = projected(work)
    assert competitor_points(view, entry["entry_id"]) == []
    assert "SYNTHETIC_WITHDRAWN_SEGMENT_LABEL" not in json.dumps(view)
    blocked = successful(work, sourced)
    assert blocked["can_edit"] is False and blocked["competitor"]["content"] is None
    assert blocked["competitor"]["source_refs"] == []
    assert "SYNTHETIC_WITHDRAWN_COMPETITOR_BODY" not in json.dumps(blocked)
    cleared, _, _ = edit(work, invalid, [])
    assert successful(work, cleared)["selected_segments"] == []


def test_http_competitor_promotion_validates_fixed_segment_refs_before_writing(work):
    target = segment(work)
    wrong = add_knowledge(work)
    proposal_id, _ = create(work)
    body = {
        "source_proposal_id": proposal_id,
        "source_proposal_revision": 1,
        "kind": "competitor",
        "deidentified_confirmed": True,
        "content": competitor_content(work, prices=[], segment_refs=[ref(wrong)]),
    }
    before = business_counts(work)
    denied = post(work, request(work, "category.knowledge.promote", body), preview=True)
    assert denied.status_code == 409 and denied.json()["code"] == "SOURCE_UNAVAILABLE"
    assert denied.json()["detail"]["reason"] == "competitor_segment_unavailable"
    assert business_counts(work) == before
    body["content"]["segment_refs"] = [ref(target)]
    receipt, _ = save(work, request(work, "category.knowledge.promote", body))
    promoted = receipt["result"]
    assert successful(work, promoted)["competitor"]["content"]["segment_refs"] == [ref(target)]
    with Session(work.admin) as session:
        assert (
            session.scalar(
                select(PromotionProof).where(
                    PromotionProof.knowledge_entry_id == UUID(promoted["entry_id"])
                )
            )
            is not None
        )


def test_http_legacy_competitor_candidate_stays_canonical_and_exports_actual_unassigned_qa(work):
    first, second = segment(work, "合成汽车应急"), segment(work, "合成自行车便携")
    command = request(
        work,
        "category.knowledge.add",
        {
            "kind": "competitor",
            "content": competitor_content(work, model="合成待关联竞品"),
        },
    )
    candidate = post(work, command, preview=True)
    assert candidate.status_code == 200, candidate.text
    prepared = candidate.json()["command"]
    assert "segment_refs" not in prepared["payload"]["content"]
    preview_token = candidate.json().get("confirmation_token")
    assert isinstance(preview_token, str) and len(preview_token) >= 20
    assert prepared["payload"]["confirmation_token"] == preview_token
    added = post(work, prepared)
    assert added.status_code == 200, added.text
    entry = added.json()["result"]
    before = business_counts(work)
    data = successful(work, entry)
    assert data["can_edit"] is True and data["selected_segments"] == []
    assert {item["entry_id"] for item in data["segments"]} == {
        first["entry_id"],
        second["entry_id"],
    }
    assert "segment_refs" not in data["competitor"]["content"]
    assert competitor_points(projected(work), entry["entry_id"]) == []
    assert business_counts(work) == before
    if destination := os.environ.get("PDOS_COMPETITOR_SEGMENTS_QA_RESPONSE_PATH"):
        output = Path(destination)
        assert output.is_absolute(), "QA response destination must be absolute"
        session_info = work.client.get("/v1/session", headers=work.headers)
        categories = work.client.get("/v1/categories", headers=work.headers)
        assert session_info.status_code == categories.status_code == 200
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                {
                    "assignment": data,
                    "session": session_info.json(),
                    "categories": categories.json(),
                    "competitor": data["competitor"],
                    "segments": data["segments"],
                    "preview": {"token_present": bool(preview_token)},
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    if os.environ.get("PDOS_COMPETITOR_SEGMENTS_QA_RESPONSE_PATH") or os.environ.get(
        "PDOS_COMPETITOR_SEGMENTS_QA_SESSION_PATH"
    ):
        private_preview = (
            Path(__file__).resolve().parents[3] / ".local" / "competitor-segments-preview.json"
        )
        private_preview.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            private_preview, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as private_file:
            os.fchmod(private_file.fileno(), 0o600)
            json.dump(candidate.json(), private_file, ensure_ascii=False)
            private_file.write("\n")
    if destination := os.environ.get("PDOS_COMPETITOR_SEGMENTS_QA_SESSION_PATH"):
        private_path = Path(destination)
        assert private_path.is_absolute(), "QA session destination must be absolute"
        private_path = private_path.resolve()
        private_root = (Path(__file__).resolve().parents[3] / ".local").resolve()
        assert private_path.is_relative_to(private_root), "QA session must stay in pdos-next/.local"
        private_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            private_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as private_file:
            os.fchmod(private_file.fileno(), 0o600)
            json.dump(
                {
                    "token": work.tokens[work.human],
                    "principal_id": str(work.human),
                    "category_id": str(work.category),
                    "competitor_entry_id": entry["entry_id"],
                    "lineage_id": entry["lineage_id"],
                    "segment_entry_id": first["entry_id"],
                    "segment_version": first["version"],
                },
                private_file,
            )
            private_file.write("\n")
