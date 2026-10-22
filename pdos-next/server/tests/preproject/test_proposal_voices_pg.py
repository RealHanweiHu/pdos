"""Scoped fixed user voices from actual knowledge/proposal HTTP commands.

The root runs PostgreSQL checks against its explicitly verified isolated target.
Only a synthetic source ACL reduction uses the fixture admin; no policy, schema,
qualification or model result is manufactured here.
"""
# ruff: noqa: F811 -- pytest injects the imported real G0 fixture.

import json
import os
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from pdos_next.database import tenant_session
from pdos_next.domain.preproject.category_models import KnowledgeEntry
from pdos_next.models import Artifact, Product
from tests.preproject.test_category_context_pg import add_knowledge
from tests.preproject.test_category_matrix_pg import counts
from tests.preproject.test_evidence_commands_pg import (
    artifact,
    record_claim,
    share_request,
    withdraw_request,
)
from tests.preproject.test_g0 import create, payload, post, read, request, save, submit
from tests.preproject.test_g0 import work as work
from tests.preproject.test_proposal_views_pg import IDENTITY, other_category, view


def voices(work, identity, *, actor=None, category=None):
    return work.client.get(
        f"/v1/categories/{category or work.category}/proposals/{identity}/voices",
        headers={"Authorization": f"Bearer {work.tokens[actor or work.human]}"},
    )


def successful(work, identity, **scope):
    response = voices(work, identity, **scope)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["version"] == "proposal-voices/v1"
    assert data["category_id"] == str(work.category)
    assert set(data["document"]) == set(IDENTITY)
    assert data["document"]["proposal_id"] == identity
    assert data["counts"] == {
        "entries": len(data["entries"]),
        "unavailable_entries": len(data["unavailable"]),
    }
    return data


def source_refs(work, *quotes):
    identity = artifact(work, body="\n".join(quotes))
    return [
        {"type": "artifact", "id": str(identity), "version": 1, "line": index, "quote": quote}
        for index, quote in enumerate(quotes, 1)
    ]


def add_voice(work, label, refs, **changes):
    return add_knowledge(
        work,
        kind="voice",
        content={
            "label": label,
            "source_platform": "合成公开访谈",
            "representative_refs": refs,
        },
        **changes,
    )


def ref(entry):
    return {"type": "knowledge", "id": entry["entry_id"], "version": 1}


def context_proposal(work, entry):
    body = payload(work)
    body["context_refs"] = [ref(entry)]
    identity, _ = create(work, body)
    return identity


def assert_redacted(data, entry, *secrets):
    assert data["entries"] == []
    assert data["counts"] == {"entries": 0, "unavailable_entries": 1}
    [unavailable] = data["unavailable"]
    assert unavailable["reference"] == ref(entry)
    assert unavailable["reasons"]
    text = json.dumps(data, ensure_ascii=False)
    for secret in secrets:
        assert secret not in text
    assert "representative_refs" not in unavailable
    assert "source_refs" not in unavailable


def test_http_voices_only_explicit_references_dedupe_preserve_items_and_derived_sample_size(work):
    first, second = source_refs(work, "合成原话：收纳要方便", "合成原话：需要看清胎压")
    voice_a = add_voice(work, "合成便携与显示诉求", [first, first, second])
    voice_b = add_voice(work, "合成显示诉求", [second])
    unrelated = add_voice(work, "SYNTHETIC_UNRELATED_CATEGORY_VOICE", [first])
    boundary = add_knowledge(work)
    body = payload(work)
    body["title"] = "合成用户声音取舍提案"
    body["context_refs"] = [ref(voice_a), ref(voice_a), ref(boundary)]
    body["groups"]["items"][0]["source_refs"] = [ref(voice_a), ref(voice_a), ref(voice_b)]
    body["groups"]["items"].append(
        {
            "kind": "section",
            "content": {"key": "features_in_out", "text": "保留便携与清晰显示"},
            "source_refs": [ref(voice_a)],
        }
    )
    identity, _ = create(work, body)
    before = counts(work)
    data = successful(work, identity)
    assert data["counts"] == {"entries": 2, "unavailable_entries": 0}
    entries = {row["knowledge_id"]: row for row in data["entries"]}
    assert set(entries) == {voice_a["entry_id"], voice_b["entry_id"]}
    assert unrelated["entry_id"] not in json.dumps(data)
    a, b = entries[voice_a["entry_id"]], entries[voice_b["entry_id"]]
    assert a["used_in_context"] is True and b["used_in_context"] is False
    assert a["sample_size"] == 2 and b["sample_size"] == 1
    assert a["origin"] == "human" and a["version"] == a["current_version"] == 1
    assert {value["quote"] for value in a["representative_refs"]} == {
        first["quote"],
        second["quote"],
    }
    parent = read(work, identity)
    assert parent.status_code == 200, parent.text
    related = [
        item
        for item in parent.json()["items"]
        if item["kind"] == "section" and item["content"]["key"] in {"worth_it", "features_in_out"}
    ]
    assert {(item["item_id"], item["version"], item["kind"]) for item in a["related_items"]} == {
        (item["item_id"], item["version"], item["kind"]) for item in related
    }
    assert len(a["related_items"]) == 2 and len(b["related_items"]) == 1
    with Session(work.admin) as session:
        stored = session.get(KnowledgeEntry, UUID(voice_a["entry_id"]))
        assert stored.content["sample_size"] == a["sample_size"]
    owner_view = view(work, "definition-maturity", identity)
    assert owner_view.status_code == 200, owner_view.text
    assert data["document"] == {key: owner_view.json()[key] for key in IDENTITY}
    participants = work.client.get(
        f"/v1/categories/{work.category}/proposals/{identity}/participants",
        headers=work.headers,
    )
    assert participants.status_code == 200, participants.text
    categories = work.client.get("/v1/categories", headers=work.headers)
    assert categories.status_code == 200, categories.text
    assert successful(work, identity)["entries"] == data["entries"]
    assert counts(work) == before

    if destination := os.environ.get("PDOS_VOICES_QA_RESPONSE_PATH"):
        output = Path(destination)
        assert output.is_absolute(), "QA destination must be an explicit absolute path"
        actor = next(
            person for person in participants.json()["items"] if person["id"] == str(work.human)
        )
        category = next(row for row in categories.json() if row["id"] == str(work.category))
        bundle = {
            "category_id": str(work.category),
            "proposal_id": identity,
            "actor": {"principal_id": str(work.human), "name": actor["name"]},
            "category": category,
            "voices": data,
            "proposal": parent.json(),
            "participants": participants.json(),
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if destination := os.environ.get("PDOS_VOICES_QA_SESSION_PATH"):
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
                    "proposal_id": identity,
                },
                private_file,
            )
            private_file.write("\n")


def test_http_voices_fixed_version_does_not_substitute_current_label_or_quote(work):
    [old_source] = source_refs(work, "SYNTHETIC_OLD_VOICE_QUOTE")
    entry = add_voice(work, "合成固定旧声音", [old_source])
    identity = context_proposal(work, entry)
    [new_source] = source_refs(work, "SYNTHETIC_CURRENT_VOICE_QUOTE")
    add_voice(
        work,
        "SYNTHETIC_CURRENT_VOICE_LABEL",
        [new_source],
        supersedes={"lineage_id": entry["lineage_id"], "expected_version": 1},
    )
    data = successful(work, identity)
    [fixed] = data["entries"]
    assert fixed["knowledge_id"] == entry["entry_id"] and fixed["version"] == 1
    assert fixed["label"] == "合成固定旧声音" and fixed["current_version"] == 2
    assert fixed["representative_refs"][0]["quote"] == old_source["quote"]
    assert "SYNTHETIC_CURRENT_VOICE_QUOTE" not in json.dumps(data)
    assert "SYNTHETIC_CURRENT_VOICE_LABEL" not in json.dumps(data)


def test_http_voices_item_patch_changes_only_the_explicit_current_association(work):
    [source] = source_refs(work, "合成共用公开原话")
    first = add_voice(work, "合成取舍前声音", [source])
    second = add_voice(work, "合成取舍后声音", [source])
    body = payload(work)
    body["groups"]["items"][0]["source_refs"] = [ref(first)]
    identity, _ = create(work, body)
    assert successful(work, identity)["entries"][0]["knowledge_id"] == first["entry_id"]
    section = next(
        item for item in read(work, identity).json()["items"] if item["kind"] == "section"
    )
    save(
        work,
        request(
            work,
            "proposal.item.patch",
            {
                "proposal_id": identity,
                "ops": [
                    {
                        "item_id": section["item_id"],
                        "base_version": section["version"],
                        "kind": section["kind"],
                        "content": section["content"],
                        "source_refs": [ref(second)],
                    }
                ],
            },
        ),
    )
    data = successful(work, identity)
    [entry] = data["entries"]
    assert entry["knowledge_id"] == second["entry_id"]
    assert data["document"]["revision"] == 2
    assert entry["used_in_context"] is False
    [related] = entry["related_items"]
    assert (related["item_id"], related["version"]) == (section["item_id"], 2)
    assert first["entry_id"] not in json.dumps(data)


def test_http_voices_reviewer_uses_actual_frozen_submission_owner_uses_current_document(work):
    [source] = source_refs(work, "合成提交时固定原话")
    entry = add_voice(work, "合成提交时固定声音", [source])
    identity = context_proposal(work, entry)
    submit(work, identity)
    submission = read(work, identity, work.peer).json()["submission"]
    add_voice(
        work,
        "合成提交后Current新声音",
        [source],
        supersedes={"lineage_id": entry["lineage_id"], "expected_version": 1},
    )
    reviewer = successful(work, identity, actor=work.peer)
    assert reviewer["document"] == {
        "proposal_id": identity,
        "revision": submission["revision"],
        "document_digest": submission["document_digest"],
        "submission_id": submission["id"],
        "document_mode": "frozen",
    }
    assert reviewer["entries"][0]["knowledge_id"] == entry["entry_id"]
    assert reviewer["entries"][0]["label"] == "合成提交时固定声音"
    owner = successful(work, identity)
    current = view(work, "definition-maturity", identity)
    assert current.status_code == 200, current.text
    assert owner["document"] == {key: current.json()[key] for key in IDENTITY}
    assert owner["document"]["document_mode"] == "current"
    assert owner["document"]["submission_id"] is None
    assert read(work, identity, work.peer).json()["submission"] == submission


def test_http_voices_claim_withdrawal_redacts_label_and_representative_quote(work):
    marker = "SYNTHETIC_WITHDRAWN_VOICE_QUOTE"
    source = artifact(work, body=marker)
    claim = record_claim(work, source, quote=marker, text="合成可撤回公开声音事实")
    entry = add_voice(
        work,
        "SYNTHETIC_WITHDRAWN_VOICE_LABEL",
        [
            {
                "type": "claim",
                "id": claim["subject_id"],
                "version": 1,
                "line": 1,
                "quote": marker,
            }
        ],
    )
    identity = context_proposal(work, entry)
    assert successful(work, identity)["entries"][0]["label"] == "SYNTHETIC_WITHDRAWN_VOICE_LABEL"
    save(work, withdraw_request(work, claim["subject_id"]))
    assert_redacted(successful(work, identity), entry, marker, "SYNTHETIC_WITHDRAWN_VOICE_LABEL")


def test_http_voices_source_acl_reduction_redacts_body_for_a_readable_proposal(work):
    marker = "SYNTHETIC_NOW_PRIVATE_VOICE_QUOTE"
    command = request(
        work,
        "evidence.artifact.register",
        {
            "title": "合成型号范围声音来源",
            "source_label": "合成公开访谈",
            "content": marker,
            "visibility": "category",
        },
    )
    command["product_id"] = str(work.product)
    registered = post(work, command)
    assert registered.status_code == 200, registered.text
    source = {
        "type": "artifact",
        "id": registered.json()["subject_id"],
        "version": 1,
        "line": 1,
        "quote": marker,
    }
    entry = add_voice(work, "SYNTHETIC_NOW_PRIVATE_VOICE_LABEL", [source])
    identity = context_proposal(work, entry)
    save(work, share_request(work, identity, visibility="category"))
    assert successful(work, identity, actor=work.peer)["entries"]
    # Narrow only the mutable parent scope; the fixed artifact is never rewritten.
    with Session(work.admin) as session, session.begin():
        artifact_row = session.get(Artifact, UUID(source["id"]))
        original = (artifact_row.visibility, artifact_row.content_hash, artifact_row.revision)
        session.get(Product, work.product).visibility = "private"
    with tenant_session(
        work.engine,
        work.tenant,
        actor_id=work.peer,
        category_id=work.category,
    ) as session:
        assert session.get(Artifact, UUID(source["id"])) is None
    with Session(work.admin) as session:
        artifact_row = session.get(Artifact, UUID(source["id"]))
        assert (
            artifact_row.visibility,
            artifact_row.content_hash,
            artifact_row.revision,
        ) == original
    assert read(work, identity, work.peer).status_code == 200
    assert_redacted(
        successful(work, identity, actor=work.peer),
        entry,
        "SYNTHETIC_NOW_PRIVATE_VOICE_LABEL",
        "SYNTHETIC_NOW_PRIVATE_VOICE_QUOTE",
    )


def test_http_voices_private_proposal_other_tenant_and_other_category_are_denied(work):
    [source] = source_refs(work, "SYNTHETIC_PRIVATE_PROPOSAL_VOICE_QUOTE")
    entry = add_voice(work, "SYNTHETIC_PRIVATE_PROPOSAL_VOICE_LABEL", [source])
    identity = context_proposal(work, entry)
    before = counts(work)
    for actor, category, status in (
        (work.peer, work.category, 404),
        (work.other_human, work.category, 403),
    ):
        response = voices(work, identity, actor=actor, category=category)
        assert response.status_code == status, response.text
        assert "SYNTHETIC_PRIVATE_PROPOSAL_VOICE" not in response.text
    assert counts(work) == before
    cross_category = voices(work, identity, category=other_category(work))
    assert cross_category.status_code == 404, cross_category.text
    assert "SYNTHETIC_PRIVATE_PROPOSAL_VOICE" not in cross_category.text


def test_http_voices_withdrawn_knowledge_is_unavailable_without_leaking_fixed_body(work):
    [source] = source_refs(work, "SYNTHETIC_WITHDRAWN_KNOWLEDGE_QUOTE")
    entry = add_voice(work, "SYNTHETIC_WITHDRAWN_KNOWLEDGE_LABEL", [source])
    identity = context_proposal(work, entry)
    assert successful(work, identity)["entries"]
    save(
        work,
        request(
            work,
            "category.knowledge.withdraw",
            {
                "lineage_id": entry["lineage_id"],
                "expected_version": 1,
                "reason": "合成声音原有归纳应撤回",
            },
        ),
    )
    assert_redacted(
        successful(work, identity),
        entry,
        "SYNTHETIC_WITHDRAWN_KNOWLEDGE_LABEL",
        "SYNTHETIC_WITHDRAWN_KNOWLEDGE_QUOTE",
    )
