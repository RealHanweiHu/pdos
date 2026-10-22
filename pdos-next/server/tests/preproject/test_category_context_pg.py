"""Material references remain private, current in drafts, and fixed at G0."""

from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.database import tenant_session
from pdos_next.domain.preproject import category_reads
from pdos_next.models import Category, Grant, now
from tests.preproject.test_g0 import (
    create,
    decide_request,
    payload,
    post,
    read,
    request,
    save,
    submit,
)
from tests.preproject.test_g0 import work as work
from tests.preproject.test_material_commands_pg import knowledge, parameter


def publish(work, **changes):
    receipt, _ = save(work, request(work, "category.parameter.publish", parameter(**changes)))
    return receipt["result"]


def add_knowledge(work, **changes):
    receipt, _ = save(work, request(work, "category.knowledge.add", knowledge(**changes)))
    return receipt["result"]


def reference(kind, identity, version=1):
    return {"type": kind, "id": identity, "version": version}


def metric(identity, **changes):
    return {
        "parameter_id": identity,
        "parameter_version": 1,
        "unit": "dB",
        "value": "42.125",
        "nature": "measured",
        "condition_note": "室内一米",
        **changes,
    }


def competitor(model, metrics, **changes):
    return {"brand": "合成品牌", "model": model, "metrics": metrics, **changes}


def test_other_members_private_draft_resolves_updates_and_manual_references_clear_hint(work):
    with Session(work.admin) as s, s.begin():
        maintainer = s.scalar(
            select(Grant).where(Grant.principal_id == work.peer, Grant.category_id == work.category)
        )
        maintainer.can_write = True
    registered = publish(work)
    entry = add_knowledge(work)
    body = payload(work)
    body["groups"]["items"][3]["content"].update(
        parameter_id=registered["parameter_id"], parameter_version=1, unit="dB"
    )
    body["groups"]["items"][0]["source_refs"] = [reference("knowledge", entry["entry_id"])]
    proposal_id, _ = create(work, body)
    unrelated_id, _ = create(work)
    assert read(work, proposal_id, work.peer).status_code == 404
    original = read(work, proposal_id).json()
    assert original["context_hint"] is False and original["context_changes"] == []

    save(
        work,
        request(
            work,
            "category.parameter.publish",
            parameter(parameter_id=registered["parameter_id"], expected_current_version=1),
        ),
        actor=work.peer,
    )
    updated, _ = save(
        work,
        request(
            work,
            "category.knowledge.add",
            knowledge(
                content={"definition": "按新用途划分"},
                supersedes={"lineage_id": entry["lineage_id"], "expected_version": 1},
            ),
        ),
        actor=work.peer,
    )
    assert read(work, proposal_id, work.peer).status_code == 404
    changed = read(work, proposal_id).json()
    assert changed["context_hint"] is True
    assert changed["revision"] == original["revision"] == 1
    assert changed["items"] == original["items"]
    assert changed["context_changes"] == [
        {**reference("parameter", registered["parameter_id"]), "current_version": 2},
        {**reference("knowledge", entry["entry_id"]), "current_version": 2, "status": "active"},
    ]
    unrelated = read(work, unrelated_id).json()
    assert unrelated["context_hint"] is False and unrelated["context_changes"] == []

    spec = next(item for item in changed["items"] if item["content"].get("key") == "noise")
    section = next(item for item in changed["items"] if item["kind"] == "section")
    save(
        work,
        request(
            work,
            "proposal.item.patch",
            {
                "proposal_id": proposal_id,
                "ops": [
                    {
                        "item_id": spec["item_id"],
                        "base_version": spec["version"],
                        "kind": "spec",
                        "content": {**spec["content"], "parameter_version": 2},
                    },
                    {
                        "item_id": section["item_id"],
                        "base_version": section["version"],
                        "kind": "section",
                        "content": section["content"],
                        "source_refs": [reference("knowledge", updated["result"]["entry_id"], 2)],
                    },
                ],
            },
        ),
    )
    refreshed = read(work, proposal_id).json()
    assert refreshed["revision"] == 2
    assert refreshed["context_hint"] is False and refreshed["context_changes"] == []
    assert read(work, proposal_id, work.peer).status_code == 404


def test_g0_freezes_all_background_and_item_references_before_material_updates(work):
    parameters = [publish(work, key=key) for key in ("noise", "pressure", "weight")]
    entries = [add_knowledge(work, content={"definition": f"合成边界 {i}"}) for i in range(3)]
    body = payload(work)
    body["context_refs"] = [
        reference("parameter", parameters[1]["parameter_id"]),
        reference("knowledge", entries[0]["entry_id"]),
    ]
    body["source_refs"] = [
        reference("parameter", parameters[2]["parameter_id"]),
        reference("knowledge", entries[1]["entry_id"]),
    ]
    body["groups"]["items"][0]["source_refs"] = [reference("knowledge", entries[2]["entry_id"])]
    body["groups"]["items"][3]["content"].update(
        parameter_id=parameters[0]["parameter_id"], parameter_version=1, unit="dB"
    )
    proposal_id, _ = create(work, body)
    submit(work, proposal_id)
    frozen = deepcopy(read(work, proposal_id, work.peer).json()["submission"])
    expected = {
        *(("parameter", row["parameter_id"], 1) for row in parameters),
        *(("knowledge", row["entry_id"], 1) for row in entries),
    }
    assert {(r["type"], r["id"], r["version"]) for r in frozen["context_refs"]} == expected
    assert frozen["frozen_document"]["context_refs"] == frozen["context_refs"]
    for row, key in zip(parameters, ("noise", "pressure", "weight"), strict=True):
        publish(work, parameter_id=row["parameter_id"], expected_current_version=1, key=key)
    for row in entries:
        add_knowledge(
            work,
            supersedes={"lineage_id": row["lineage_id"], "expected_version": 1},
            content={"definition": "已修订的共享边界"},
        )
    assert read(work, proposal_id, work.peer).json()["submission"] == frozen
    approved, _ = save(work, decide_request(work, proposal_id), actor=work.peer)
    assert approved["result"]["status"] == "approved"
    assert read(work, proposal_id, work.peer).json()["submission"] == frozen


@pytest.mark.parametrize("invalid", ["other_category", "missing_version", "wrong_unit"])
@pytest.mark.parametrize("field", ["metrics", "features"])
def test_competitor_promotion_rejects_invalid_parameter_reference(work, invalid, field):
    target = work
    if invalid == "other_category":
        other_category = uuid4()
        with Session(work.admin) as s, s.begin():
            s.add(
                Category(
                    id=other_category,
                    tenant_id=work.tenant,
                    name="合成其他品类",
                    purpose="拒绝跨品类参数引用",
                    owner_id=work.human,
                )
            )
            s.flush()
            s.add(
                Grant(
                    tenant_id=work.tenant,
                    category_id=other_category,
                    principal_id=work.human,
                    can_write=True,
                    expires_at=now() + timedelta(hours=1),
                )
            )
        target = SimpleNamespace(**{**vars(work), "category": other_category})
    registered = publish(target)
    proposal_id, _ = create(work)
    observation = metric(registered["parameter_id"])
    if invalid == "missing_version":
        observation["parameter_version"] = 99
    elif invalid == "wrong_unit":
        observation["unit"] = "Pa"
    response = post(
        work,
        request(
            work,
            "category.knowledge.promote",
            {
                "source_proposal_id": proposal_id,
                "source_proposal_revision": 1,
                "kind": "competitor",
                "content": {"brand": "合成品牌", "model": "拒绝样例", field: [observation]},
                "deidentified_confirmed": True,
            },
        ),
        preview=True,
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["reason"] == (
        "parameter_unit_mismatch" if invalid == "wrong_unit" else "parameter_unreadable"
    )
    with tenant_session(
        work.engine, work.tenant, actor_id=work.human, category_id=work.category
    ) as s:
        assert category_reads.knowledge(s, work.ctx, kind="competitor")["items"] == []


def test_competitor_filters_apply_to_same_observation_before_pagination(work):
    selected = publish(work)["parameter_id"]
    other = publish(work, key="other_noise")["parameter_id"]
    rows = [
        add_knowledge(work, kind="competitor", content=competitor(str(i), [metric(selected)]))
        for i in range(4)
    ]
    rows.sort(key=lambda row: row["lineage_id"])
    for i, row in enumerate(rows[:2]):
        add_knowledge(
            work,
            kind="competitor",
            supersedes={"lineage_id": row["lineage_id"], "expected_version": 1},
            content=competitor(
                f"排除 {i}",
                [metric(selected, nature="claimed")] if i == 0 else [],
                features=[metric(other)],
            ),
        )
    # Both rejected rows sort ahead of every match: filtering a pre-limited page fails.
    with tenant_session(
        work.engine, work.tenant, actor_id=work.human, category_id=work.category
    ) as s:
        first = category_reads.competitors(
            s, work.ctx, parameter_ids=[UUID(selected)], nature="measured", page_size=1
        )
        assert [row["lineage_id"] for row in first["items"]] == [rows[2]["lineage_id"]]
        assert first["next_cursor"] is not None
        second = category_reads.competitors(
            s,
            work.ctx,
            parameter_ids=[UUID(selected)],
            nature="measured",
            page_size=1,
            cursor=first["next_cursor"],
        )
        assert [row["lineage_id"] for row in second["items"]] == [rows[3]["lineage_id"]]
        assert second["next_cursor"] is None
        for page in (first, second):
            for row in page["items"]:
                assert row["content"]["features"] == []
                assert all(
                    item["parameter_id"] == selected and item["nature"] == "measured"
                    for item in row["content"]["metrics"]
                )
        assert category_reads.competitors(s, work.ctx, parameter_ids=[])["items"] == []


def test_competitor_prices_preserve_decimal_and_comparison_contexts(work):
    identity = publish(work)["parameter_id"]
    publish(work, parameter_id=identity, expected_current_version=1, unit="dB(A)")
    prices = [
        {
            "amount": "12345678901234567890.123456789",
            "currency": "CNY",
            "observed_on": "2026-10-01",
            "price_type": "retail",
            "includes_tax": True,
            "includes_shipping": False,
            "channel": "合成直营渠道",
            "region": "CN",
            "source_ref": None,
        },
        {
            "amount": "9.990000000000000001",
            "currency": "USD",
            "observed_on": "2026-10-02",
            "price_type": "promo",
            "includes_tax": False,
            "includes_shipping": True,
            "channel": "合成代理渠道",
            "region": "US",
            "source_ref": None,
        },
    ]
    add_knowledge(
        work,
        kind="competitor",
        content=competitor(
            "多口径样例",
            [
                metric(identity),
                metric(identity, condition_note="室外三米"),
                metric(identity, parameter_version=2, unit="dB(A)"),
            ],
            features=[metric(identity, nature="claimed")],
            prices=prices,
        ),
    )
    with tenant_session(
        work.engine, work.tenant, actor_id=work.human, category_id=work.category
    ) as s:
        result = category_reads.competitors(s, work.ctx)["items"]
    assert len(result) == 1
    assert result[0]["content"]["prices"] == prices
    assert [Decimal(row["amount"]) for row in result[0]["content"]["prices"]] == [
        Decimal(row["amount"]) for row in prices
    ]
    groups = {
        (row["parameter_id"], row["parameter_version"], row["unit"], row["condition_note"]): row
        for row in result[0]["comparison_groups"]
    }
    assert set(groups) == {
        (identity, 1, "dB", "室内一米"),
        (identity, 1, "dB", "室外三米"),
        (identity, 2, "dB(A)", "室内一米"),
    }
    shared = groups[(identity, 1, "dB", "室内一米")]
    assert len(shared["metrics"]) == len(shared["features"]) == 1
    assert shared["metrics"][0]["nature"] == "measured"
    assert shared["features"][0]["nature"] == "claimed"
