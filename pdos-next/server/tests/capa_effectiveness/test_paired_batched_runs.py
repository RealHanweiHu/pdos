"""Pure paired material for per-Run clocks and append-only batched acceptance.

These saved DTO shapes prove structure only; the separate API/PG chain proves
the actual owner ports and original bytes. No database or live grant is used.
"""

from copy import deepcopy

import pytest
from capa_effectiveness.test_live_paired_owner import structural, without_artifact_read

from pdos_next.domain.capa_effectiveness import paired
from pdos_next.errors import DomainError
from pdos_next.schemas.verification.contracts import ReturnedScope


def reseal(material):
    reads = paired._merged_reads([paired._artifact_refs(material.model_dump(mode="json"))])
    return material.model_copy(
        update={
            name: getattr(material, name).model_copy(update={"reads": reads})
            for name in (
                "origin_request",
                "request_before",
                "request_after",
                "run_before",
                "run_after",
                "fact",
                "projection",
                "projection_run",
            )
            if getattr(material, name) is not None
        }
    )


def snapshot_row(row, snapshot, **updates):
    return row.model_copy(
        update={
            "snapshot": snapshot,
            "snapshot_sha256": paired.digest(snapshot.model_dump(mode="json")),
            **updates,
        }
    )


def sibling_clocks(operation):
    binding, material = structural.saved(operation)
    first = {
        "promised_start": structural.tf(
            structural.ev("sibling-promise", 112), structural.OWNER, 112
        ),
        "actual_start": structural.tf(structural.ev("sibling-start", 113), structural.OWNER, 113),
        "preliminary_result": structural.tf(
            structural.ev("sibling-preliminary", 119), structural.OWNER, 119
        ),
    }
    before_revision = material.request_before.ref.revision + 4
    before_ref = paired.FixedRef(
        id=structural.uid(f"multi-before-{operation}"), revision=before_revision
    )
    after_ref = paired.FixedRef(
        id=structural.uid(f"multi-after-{operation}"), revision=before_revision + 1
    )
    before = snapshot_row(
        material.request_before,
        material.request_before.snapshot.model_copy(
            update={
                "revision": before_ref.revision,
                "status": "executing",
                "timeline": material.request_before.snapshot.timeline.model_copy(update=first),
            }
        ),
        ref=before_ref,
        previous=paired.FixedRef(
            id=structural.uid("earlier-sibling-version"), revision=before_revision - 1
        ),
    )
    after = snapshot_row(
        material.request_after,
        material.request_after.snapshot.model_copy(
            update={
                "revision": after_ref.revision,
                "status": "reported" if operation == "test.results.import" else "executing",
                "timeline": material.request_after.snapshot.timeline.model_copy(update=first),
            }
        ),
        ref=after_ref,
        previous=before_ref,
    )
    raw = deepcopy(material.fact.input_snapshot)
    raw["expected_request_revision"] = before_ref.revision
    domain = structural.intent(operation, material.fact.actor_id, raw)
    after = after.model_copy(update={"domain_intent": domain})
    fact_updates = {
        "request_before": before_ref,
        "next_request": after_ref,
        "input_snapshot": raw,
        "domain_intent": domain,
    }
    if material.fact.kind == "launch":
        event = material.fact.kernel_event
        if operation == "verification.schedule.promise":
            event = event.model_copy(update={"revision": after_ref.revision})
        fact_updates.update(
            kernel_event=event, snapshot_sha256=paired.digest(event.model_dump(mode="json"))
        )
    common = material.common_material.model_copy(update={"payload": raw})
    target = after if operation == "verification.schedule.promise" else material.run_after
    receipt = material.receipt.model_copy(
        update={
            "subject": target.ref,
            "result": material.receipt.result.model_copy(
                update={
                    "id": target.ref.id,
                    "revision": target.ref.revision,
                    "status": target.snapshot.status,
                }
            ),
            "common_intent": paired.digest(common.model_dump(mode="json", exclude={"handler"})),
        }
    )
    updates = {
        "request_before": before,
        "request_after": after,
        "request_current": after_ref,
        "fact": material.fact.model_copy(update=fact_updates),
        "common_material": common,
        "receipt": receipt,
        "outbox": tuple(
            value.model_copy(update={"subject": target.ref}) for value in material.outbox
        ),
    }
    if operation != "verification.schedule.promise":
        updates["run_after"] = material.run_after.model_copy(update={"domain_intent": domain})
        if material.projection_run and material.projection_run.ref == material.run_after.ref:
            updates["projection_run"] = updates["run_after"]
    material = reseal(material.model_copy(update=updates))
    binding = binding.model_copy(update={"output_ref": paired.FormalRef(**after_ref.model_dump())})
    return binding, material, first


@pytest.mark.parametrize(
    "operation", ["verification.schedule.promise", "test.run.start", "test.results.import"]
)
def test_later_run_owns_its_action_clock_and_retains_request_first_clocks(operation):
    binding, material, first = sibling_clocks(operation)
    proof = paired.verify_paired_material(binding, material, at=structural.AT).proof
    assert proof.structural_only is True
    for name, value in first.items():
        assert getattr(material.request_after.snapshot.timeline, name) == value
    if operation == "verification.schedule.promise":
        assert material.fact.kernel_event.at != first["promised_start"]
    else:
        assert material.run_after.snapshot.actual_start != first["actual_start"]


def accepted_subset_extension():
    binding, material, _ = sibling_clocks("test.run.start")
    coverage = material.origin_request.snapshot.offered_coverage
    first = material.origin_request.snapshot.acceptances[0].model_copy(
        update={"coverage": coverage[:1]}
    )
    second = first.model_copy(
        update={
            "coverage": coverage[1:],
            "at": structural.tf(structural.ev("later-accepted", 115), structural.OWNER, 115),
        }
    )
    origin = snapshot_row(
        material.origin_request,
        material.origin_request.snapshot.model_copy(update={"acceptances": (first,)}),
    )
    updates = {"origin_request": origin}
    for name in ("request_before", "request_after"):
        row = getattr(material, name)
        updates[name] = snapshot_row(
            row, row.snapshot.model_copy(update={"acceptances": (first, second)})
        )
    for name in ("run_before", "run_after"):
        row = getattr(material, name)
        updates[name] = snapshot_row(
            row,
            row.snapshot.model_copy(
                update={"coverage": coverage[:1], "samples": row.snapshot.samples[:1]}
            ),
        )
    event = material.fact.kernel_event.model_copy(update={"coverage": coverage[:1]})
    updates["fact"] = material.fact.model_copy(
        update={
            "kernel_event": event,
            "snapshot_sha256": paired.digest(event.model_dump(mode="json")),
        }
    )
    return binding, reseal(material.model_copy(update=updates))


def test_run_subset_remains_fixed_when_current_request_later_accepts_another_pair():
    binding, material = accepted_subset_extension()
    proof = paired.verify_paired_material(binding, material, at=structural.AT).proof
    assert proof.structural_only is True
    assert len(material.run_after.snapshot.coverage) == 1
    assert len(material.request_after.snapshot.acceptances) == 2


def test_run_may_use_strict_nonempty_subset_of_already_accepted_scope():
    binding, material, _ = sibling_clocks("test.run.start")
    _, scoped = accepted_subset_extension()
    material = reseal(
        material.model_copy(
            update={
                "run_before": scoped.run_before,
                "run_after": scoped.run_after,
                "fact": scoped.fact,
            }
        )
    )
    assert len(material.origin_request.snapshot.acceptances[0].coverage) == 2
    assert len(material.run_after.snapshot.coverage) == 1
    assert paired.verify_paired_material(binding, material, at=structural.AT).proof.structural_only


@pytest.mark.parametrize("change", ["removed", "rewritten", "overlap", "unoffered"])
def test_later_acceptance_cannot_remove_rewrite_or_overlap_saved_scope(change):
    binding, material = accepted_subset_extension()
    current = material.request_before.snapshot
    first, second = current.acceptances
    if change == "removed":
        acceptances = (second,)
    elif change == "rewritten":
        acceptances = (first.model_copy(update={"actor_id": structural.uid("replacement")}), second)
    elif change == "overlap":
        acceptances = (first, second.model_copy(update={"coverage": first.coverage}))
    else:
        unoffered = second.coverage[0].model_copy(
            update={"sample_id": structural.uid("never-offered")}
        )
        acceptances = (first, second.model_copy(update={"coverage": (unoffered,)}))
    updates = {}
    for name in ("request_before", "request_after"):
        row = getattr(material, name)
        updates[name] = snapshot_row(
            row, row.snapshot.model_copy(update={"acceptances": acceptances})
        )
    with pytest.raises(DomainError) as failure:
        paired.verify_paired_material(
            binding, reseal(material.model_copy(update=updates)), at=structural.AT
        )
    assert failure.value.reason == "PAIR_FIXED_SCOPE_CHANGED"


@pytest.mark.parametrize("returned_origin", [False, True])
def test_equal_receive_clock_retains_return_then_accept_history_without_order_guess(
    returned_origin,
):
    binding, material = accepted_subset_extension()
    first, second = material.request_before.snapshot.acceptances
    returned = ReturnedScope(
        coverage=first.coverage if returned_origin else second.coverage,
        gaps=(),
        reason="Synthetic return observed before the later acceptance version",
        next_owner_id=structural.OWNER,
        actor_id=structural.OWNER,
        at=second.at,
    )
    updates = {}
    for name in ("request_before", "request_after"):
        row = getattr(material, name)
        updates[name] = snapshot_row(row, row.snapshot.model_copy(update={"returns": (returned,)}))
    changed = reseal(material.model_copy(update=updates))
    if returned_origin:
        with pytest.raises(DomainError) as failure:
            paired.verify_paired_material(binding, changed, at=structural.AT)
        assert failure.value.reason == "PAIR_FIXED_SCOPE_CHANGED"
    else:
        assert paired.verify_paired_material(
            binding, changed, at=structural.AT
        ).proof.structural_only


def historical_offer(material, source=None):
    clock = structural.tf(structural.ev("historical-offer", 105), structural.OWNER, 105)
    if source is not None:
        clock = clock.model_copy(update={"source": source})
    updates = {}
    for name in ("origin_request", "request_before", "request_after"):
        row = getattr(material, name)
        snapshot = row.snapshot.model_copy(
            update={"timeline": row.snapshot.timeline.model_copy(update={"offered": clock})}
        )
        updates[name] = snapshot_row(row, snapshot)
    return reseal(material.model_copy(update=updates)), clock


@pytest.mark.parametrize(
    "operation", ["verification.schedule.promise", "test.run.start", "test.results.import"]
)
def test_historical_offer_remains_fixed_without_consuming_its_original_again(operation):
    binding, material = structural.saved(operation)
    material, offered = historical_offer(material)
    narrowed = without_artifact_read(material, offered.source)
    proof = paired.verify_paired_material(binding, narrowed, at=structural.AT).proof
    assert proof.structural_only is True
    assert (offered.source.id, offered.source.revision) not in {
        (ref.artifact_id, ref.expected_revision) for ref in proof.required_source_read_set
    }
    for name in ("origin_request", "request_before", "request_after"):
        assert getattr(narrowed, name).snapshot.timeline.offered == offered


@pytest.mark.parametrize("current_use", ["fact", "run", "payload"])
def test_offer_artifact_reused_by_current_material_still_requires_evidence(current_use):
    binding, material = structural.saved("test.run.start")
    if current_use == "fact":
        current_source = material.fact.kernel_event.at.source
    elif current_use == "run":
        current_source = material.run_after.snapshot.execution.equipment
    else:
        current_source = paired._source(
            structural.DefinitionReference.model_validate(
                material.fact.input_snapshot["sources"][0]
            )
        )
    material, offered = historical_offer(material, current_source)
    narrowed = without_artifact_read(material, offered.source)
    with pytest.raises(DomainError) as failure:
        paired.verify_paired_material(binding, narrowed, at=structural.AT)
    assert failure.value.reason == "MISSING_REQUIRED_EVIDENCE"
