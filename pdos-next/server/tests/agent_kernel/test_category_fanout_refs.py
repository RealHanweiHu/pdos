"""Synthetic research results acquire refs only from the server callback, never the model."""

from copy import deepcopy
from uuid import UUID, uuid4

import pytest

from pdos_next.agent_kernel.research_adapter import ResearchReadAdapter
from pdos_next.errors import DomainError
from tests.agent_kernel.test_research_adapter_restore import (
    fixture,
    replay,
    result,
    write_artifact,
)


class ReadLedger:
    def __init__(self):
        self.records = {}
        self.seen = []
        self.deleted = False

    def __call__(self, scope, value):
        self.seen.append(deepcopy(value))
        if self.deleted:
            raise DomainError("SOURCE_UNAVAILABLE", "Synthetic revoked actual read")
        if "snapshot_read_refs" in value:
            # Recheck the saved call identities; newer calls do not replace them.
            wanted = [ref["call_id"] for ref in value["snapshot_read_refs"]]
            if any(identity not in self.records for identity in wanted):
                raise DomainError("SOURCE_UNAVAILABLE", "Synthetic missing actual read")
            return [deepcopy(self.records[identity]) for identity in wanted]
        hashes = {ref["id"]: ref["content_hash"] for ref in value["snapshots"]}
        for coverage in value["coverage"]:
            for read in coverage["reads"]:
                if read["error"] is None:
                    identity = str(uuid4())
                    self.records[identity] = {
                        "call_id": identity, "snapshot_id": read["snapshot_id"],
                        "content_hash": hashes[read["snapshot_id"]], "locator": read["locator"],
                    }
        return list(self.records.values())


def configured(tmp_path):
    f = fixture(tmp_path)
    ledger = ReadLedger()
    f.adapter = ResearchReadAdapter(
        f.adapter.tool_host, f.artifacts, user_messages=lambda _: (), read_refs=ledger,
    )
    return f, ledger


def test_fresh_fanout_persists_only_server_read_refs_before_return(tmp_path):
    f, ledger = configured(tmp_path)
    prior = result(f)
    assert "snapshot_read_refs" not in ledger.seen[0]
    refs = prior["snapshot_read_refs"]
    assert refs == sorted(ledger.records.values(), key=lambda ref: ref["call_id"])
    assert all(set(ref) == {"call_id", "snapshot_id", "content_hash", "locator"} for ref in refs)
    assert f.artifacts.get(f.scope, UUID(prior["job_id"]))["value"] == prior
    assert f.runs == ["a"]


def test_restore_rechecks_saved_refs_without_research_network_or_replacement(tmp_path):
    f, ledger = configured(tmp_path)
    prior = result(f)
    existing = deepcopy(prior)
    later = {**prior["snapshot_read_refs"][0], "call_id": str(uuid4())}
    ledger.records[later["call_id"]] = later
    adapter, runtime = replay(f)
    adapter.read_refs = ledger
    restored = adapter.restore_fanout(f.scope, f.arguments, prior)
    assert restored is prior and prior == existing
    assert ledger.seen[-1]["snapshot_read_refs"] == existing["snapshot_read_refs"]
    assert runtime.search_adapter.queries == [] and runtime.transport.requests == []
    assert f.runs == ["a"]


@pytest.mark.parametrize("change", ["missing", "hash", "snapshot", "locator", "withdrawn"])
def test_restore_requires_every_saved_call_still_matches_actual_ledger(tmp_path, change):
    f, ledger = configured(tmp_path)
    prior = result(f)
    ref = ledger.records[prior["snapshot_read_refs"][0]["call_id"]]
    if change == "missing":
        ledger.records.clear()
    elif change == "hash":
        ref["content_hash"] = "f" * 64
    elif change == "snapshot":
        ref["snapshot_id"] = str(uuid4())
    elif change == "locator":
        ref["locator"] = "chars:0:9999"
    else:
        ledger.deleted = True
    adapter, runtime = replay(f)
    adapter.read_refs = ledger
    with pytest.raises(DomainError):
        adapter.restore_fanout(f.scope, f.arguments, prior)
    assert runtime._snapshots == {} and runtime._allowlists == {}
    assert not runtime.transport.requests and not runtime.search_adapter.queries


def test_restore_without_verifier_does_not_trust_saved_ref_field(tmp_path):
    f, _ = configured(tmp_path)
    prior = result(f)
    adapter, runtime = replay(f)
    with pytest.raises(DomainError):
        adapter.restore_fanout(f.scope, f.arguments, prior)
    assert runtime._allowlists == {}


def test_legacy_fanout_recovers_old_scope_without_minting_category_refs(tmp_path):
    f = fixture(tmp_path)
    prior = result(f)
    adapter, runtime = replay(f)

    def forbidden(*args):
        pytest.fail("Legacy read must not be silently upgraded with new ledger refs")

    adapter.read_refs = forbidden
    assert adapter.restore_fanout(f.scope, f.arguments, prior) is prior
    assert "snapshot_read_refs" not in prior
    assert runtime._allowlists and f.runs == ["a"]


@pytest.mark.parametrize("change", ["tuple", "empty", "duplicate", "call", "upper_uuid", "raw",
                                    "hash", "snapshot", "locator", "missing_field"])
def test_bad_callback_shape_or_uncovered_pages_are_never_saved(tmp_path, change):
    f, ledger = configured(tmp_path)

    def malformed(scope, value):
        refs = ledger(scope, value)
        if change == "tuple":
            return tuple(refs)
        if change == "empty":
            return []
        if change == "duplicate":
            return refs * 2
        ref = refs[0]
        if change == "call":
            ref["call_id"] = "not-a-uuid"
        elif change == "upper_uuid":
            ref["call_id"] = "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"
        elif change == "raw":
            ref["markdown"] = "Must never reach the main graph"
        elif change == "hash":
            ref["content_hash"] = "f" * 64
        elif change == "snapshot":
            ref["snapshot_id"] = str(uuid4())
        elif change == "locator":
            ref["locator"] = "chars:0:1"
        else:
            del ref["locator"]
        return refs

    f.adapter.read_refs = malformed
    with pytest.raises(DomainError):
        result(f)
    # Snapshots can exist from completed isolated reads; no authoritative fanout receipt is saved.
    stored = [f.artifacts.get(f.scope, UUID(path.stem)) for path in tmp_path.rglob("*.json")]
    assert stored and all(value["kind"] != "research_ledger" for value in stored)


def test_untrusted_producer_cannot_supply_refs_even_when_callback_absent(tmp_path):
    f = fixture(tmp_path)
    original = f.adapter.tool_host.call

    async def forged(*args):
        value = await original(*args)
        return {**value, "snapshot_read_refs": []}

    f.adapter.tool_host.call = forged
    with pytest.raises(DomainError):
        result(f)


def test_callback_cannot_mutate_job_content_or_inject_raw_text(tmp_path):
    f, ledger = configured(tmp_path)

    def mutating(scope, value):
        refs = ledger(scope, value)
        value["markdown"] = "Raw text injection"
        value["ledger"][0]["quote"] = "Changed ledger quote"
        return refs

    f.adapter.read_refs = mutating
    prior = result(f)
    assert "markdown" not in prior
    assert prior["ledger"][0]["quote"] != "Changed ledger quote"
    assert f.artifacts.get(f.scope, UUID(prior["job_id"]))["value"] == prior


def test_consistently_rewritten_job_refs_still_require_original_actual_call(tmp_path):
    f, ledger = configured(tmp_path)
    prior = result(f)
    prior["snapshot_read_refs"][0]["call_id"] = str(uuid4())
    write_artifact(f, prior["job_id"], {"kind": "research_ledger", "value": prior})
    adapter, runtime = replay(f)
    adapter.read_refs = ledger
    with pytest.raises(DomainError):
        adapter.restore_fanout(f.scope, f.arguments, prior)
    assert runtime._allowlists == {}


def test_fresh_refs_are_sorted_and_restore_cannot_replace_call_with_later_read(tmp_path):
    f, ledger = configured(tmp_path)

    def many(scope, value):
        refs = ledger(scope, value)
        second = {**refs[0], "call_id": str(uuid4())}
        return sorted([*refs, second], key=lambda ref: ref["call_id"], reverse=True)

    f.adapter.read_refs = many
    prior = result(f)
    assert prior["snapshot_read_refs"] == sorted(
        prior["snapshot_read_refs"], key=lambda r: r["call_id"],
    )
    adapter, runtime = replay(f)
    # A live valid-looking page is insufficient: restore must preserve original call IDs.
    adapter.read_refs = lambda _, value: [
        {**value["snapshot_read_refs"][0], "call_id": str(uuid4())},
    ]
    with pytest.raises(DomainError):
        adapter.restore_fanout(f.scope, f.arguments, prior)
    assert runtime._allowlists == {}


def test_current_authority_is_rechecked_after_read_refs_before_restore_grants(tmp_path):
    f, ledger = configured(tmp_path)
    prior = result(f)
    adapter, runtime = replay(f)

    def revoked(scope):
        raise DomainError("FORBIDDEN_SCOPE", "Synthetic authority revoked")

    def check_then_revoke(scope, value):
        refs = ledger(scope, value)
        f.artifacts.current = revoked
        return refs

    adapter.read_refs = check_then_revoke
    with pytest.raises(DomainError):
        adapter.restore_fanout(f.scope, f.arguments, prior)
    assert runtime._allowlists == {} and runtime._snapshots == {}
