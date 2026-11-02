"""Dispatch and final IO guards, with actual database/qualified READY owners substituted."""

from copy import deepcopy

import pytest


@pytest.fixture
def running(staging, monkeypatch):
    state = staging
    state.start([])
    row = state.h.existing
    loaded = (*state.current[:6], row)
    state.seen = []

    def read(*args, **kwargs):
        state.seen.append(kwargs)
        assert kwargs["_fingerprint_version"] == state.new._FINGERPRINT_V2
        kwargs["_fingerprint_collector"].append(deepcopy(state.record))
        return loaded

    monkeypatch.setattr(state.new, "_load", read)
    occupancies = [r for r in state.added if isinstance(r, state.new.ResourceOccupancy)]
    usages = [r for r in state.added if isinstance(r, state.new.SampleRunUsage)]

    def scalars(statement):
        entity = statement.column_descriptions[0]["entity"]
        return occupancies if entity is state.new.ResourceOccupancy else usages

    state.session.scalars = scalars
    state.recheck = lambda: state.new.recheck_running(
        state.session,
        state.h.ctx,
        state.h.pid,
        state.h.binding,
        state.h.fact.id,
        state.h.fact.revision,
        intent_digest="a" * 64,
        at=state.h.clock,
    )
    state.row = row
    state.usages = usages
    state.occupancies = occupancies
    return state


def test_recheck_reads_actual_saved_version_and_never_reserves_again(running):
    state = running
    before = (
        state.flushes,
        len(state.added),
        [a.occupancy_epoch for a in state.h.assets.values()],
        [s.epoch for s in state.h.sentinels.values()],
    )
    value = state.recheck()
    assert value.facts_revision == state.row.facts_revision
    assert len(state.seen) == 1
    assert before == (
        state.flushes,
        len(state.added),
        [a.occupancy_epoch for a in state.h.assets.values()],
        [s.epoch for s in state.h.sentinels.values()],
    )


@pytest.mark.parametrize(
    "change", ["own-occupancy", "own-sample", "source", "runtime", "expiry", "saved-proof"]
)
def test_saved_v2_cannot_skip_current_own_effects_sources_runtime_and_final_clock(
    running, monkeypatch, change
):
    state = running
    if change == "own-occupancy":
        state.occupancies[0].units += 1
    elif change == "own-sample":
        state.usages[0].sample_revision += 1
    elif change == "source":

        def source(*args):
            raise state.new.DomainError("SOURCE_STALE", "withdrawn current source")

        monkeypatch.setattr(state.new, "_sources", source)
    elif change == "runtime":
        monkeypatch.setattr(
            state.new,
            "_sources",
            lambda *args: state.h.engine._pdos_test_resource_issuer_epochs.update(
                {"unrelated-other-scope": 200}
            ),
        )
    elif change == "expiry":
        monkeypatch.setattr(
            state.new,
            "_sources",
            lambda *args: setattr(state.h, "clock", state.current[0].valid_until),
        )
    else:
        monkeypatch.setattr(
            state.new,
            "_sources",
            lambda *args: state.row.dependency_proof.update({"facts_revision": "f" * 64}),
        )
    with pytest.raises(state.new.DomainError):
        state.recheck()
    assert state.flushes == 1 and len(state.added) == 4


def test_corrupt_saved_record_is_rejected_before_current_recheck_io(running):
    state = running
    state.row.dependency_proof = None
    with pytest.raises(state.new.DomainError):
        state.recheck()
    assert state.seen == []
