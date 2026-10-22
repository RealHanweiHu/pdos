"""Pure synthetic read ledger: whole locator coverage and current provenance."""

from copy import deepcopy
from hashlib import sha256
from uuid import uuid4

import pytest
from test_snapshot_read_ledger import ledger as ledger

from pdos_next.agent_kernel.snapshot_locator import validate_snapshot_locator
from pdos_next.agent_kernel.snapshot_read_ledger import page_result
from pdos_next.errors import DomainError
from pdos_next.models import Grant, Principal
from pdos_next.service import digest


def validate(f, locator, **overrides):
    arguments = dict(
        snapshot_id=f.snapshot.id, version=1, locator=locator, call_id=f.call.id,
    )
    arguments.update(overrides)
    return validate_snapshot_locator(f.session, f.scope, **arguments)


def set_page(f, *, body=None, cursor=0, end=None):
    if body is not None:
        f.snapshot.markdown = body
        f.snapshot.content_hash = sha256(body.encode()).hexdigest()
        f.receipt.result["content_hash"] = f.snapshot.content_hash
    end = len(f.snapshot.markdown) if end is None else end
    f.args["cursor"] = cursor
    f.call.input_digest = digest([f.call.tool, f.args])
    f.call.execution_binding["page_chars"] = end - cursor
    f.call.result = page_result(f.snapshot, cursor=cursor, page_chars=end - cursor)


def test_whole_line_and_character_page_reuse_actual_cross_run_proof(ledger):
    f = ledger
    before = deepcopy((f.call.result, f.call.execution_binding, f.args))
    assert f.snapshot.registered_by_run_id != f.run.id
    line = validate(f, "line:2")
    chars = validate(f, f.call.result["locator"])
    assert line.call_id == chars.call_id == f.call.id
    assert line.snapshot_id == f.snapshot.id
    assert line.registration_receipt_id == f.receipt.id
    assert line.content_hash == f.snapshot.content_hash
    assert line.start == chars.start == f.call.result["cursor"]
    assert line.end == chars.end - 1  # Line-ending excluded from line:N.
    assert before == (f.call.result, f.call.execution_binding, f.args)


@pytest.mark.parametrize("locator", [
    None, True, 1, {}, {"line": 2}, [], "", " ", "line:0", "line:-1", "line:True",
    "line:02", "line:2.0", "line:+2", "line:٢", "line:2 ", " line:2", "line:2\n",
    "line:2:3", "chars:-1:2", "chars:2:-3", "chars:01:2", "chars:1:02",
    "chars:True:2", "chars:1.0:2", "chars:1:1", "chars:3:2", "chars:0:0",
    "chars:1:2:3", "chars:1:2 ", "chars:1:2\n", "chars:0:99999", "line:9999",
])
def test_invalid_noncanonical_empty_or_out_of_body_locator_rejected(ledger, locator):
    with pytest.raises(DomainError):
        validate(ledger, locator)


@pytest.mark.parametrize("direction", ["before", "after", "spanning_both", "line1", "line3"])
def test_locator_must_be_wholly_covered_by_one_page(ledger, direction):
    start, end = ledger.call.result["cursor"], ledger.call.result["end"]
    locator = {
        "before": f"chars:{start - 1}:{start + 2}",
        "after": f"chars:{end - 2}:{end + 1}",
        "spanning_both": f"chars:{start - 1}:{end + 1}",
        "line1": "line:1", "line3": "line:3",
    }[direction]
    with pytest.raises(DomainError) as error:
        validate(ledger, locator)
    assert error.value.detail["reason"] == "snapshot_locator_not_read"


@pytest.mark.parametrize("cursor,end", [(1, 5), (0, 4), (2, 3)])
def test_single_verified_character_never_grants_unread_rest_of_line(ledger, cursor, end):
    set_page(ledger, body="abcde\n", cursor=cursor, end=end)
    assert validate(ledger, f"chars:{cursor}:{end}")
    with pytest.raises(DomainError):
        validate(ledger, "line:1")
    with pytest.raises(DomainError):
        validate(ledger, "chars:0:5")


def test_line_needs_entire_text_but_not_its_newline(ledger):
    set_page(ledger, body="abcde\r\nnext", cursor=0, end=5)
    proof = validate(ledger, "line:1")
    assert (proof.start, proof.end) == (0, 5)
    with pytest.raises(DomainError):
        validate(ledger, "chars:0:7")


def test_unicode_codepoint_offsets_and_full_crlf_range(ledger):
    body = "首行\r\n💡成本：二元\r\n末行"
    start, end = 4, len(body) - 2
    set_page(ledger, body=body, cursor=start, end=end)
    line = validate(ledger, "line:2")
    assert (line.start, line.end) == (4, 10)
    chars = validate(ledger, f"chars:{start}:{end}")
    assert body[chars.start:chars.end] == "💡成本：二元\r\n"
    assert validate(ledger, "chars:4:5").end == 5  # One emoji, one character.
    with pytest.raises(DomainError):
        validate(ledger, f"chars:{start}:{len(body.encode())}")


def test_multi_line_range_including_line_endings_is_fully_bounded(ledger):
    body = "unseen\n一行\r\nsecond line\ntrailer"
    start, end = len("unseen\n"), len(body) - len("trailer")
    set_page(ledger, body=body, cursor=start, end=end)
    proof = validate(ledger, f"chars:{start}:{end}")
    assert body[proof.start:proof.end] == "一行\r\nsecond line\n"
    with pytest.raises(DomainError):
        validate(ledger, f"chars:{start}:{end + 1}")


def test_repeated_quote_cannot_authorize_outside_page_occurrence(ledger):
    set_page(ledger, body="same same same", cursor=5, end=9)
    assert validate(ledger, "chars:5:9")
    for locator in ("chars:0:4", "chars:10:14", "line:1"):
        with pytest.raises(DomainError):
            validate(ledger, locator)


@pytest.mark.parametrize("body,locator", [
    ("\r\n\r\n", "chars:0:4"), ("\n", "chars:0:1"),
    (" \t \r\n", "chars:0:5"), (" \t \r\n", "line:1"),
    ("abc\r\ndef", "chars:3:5"), ("abc\n\ndef", "line:2"),
])
def test_newline_or_whitespace_only_region_cannot_supply_quote_witness(ledger, body, locator):
    set_page(ledger, body=body)
    with pytest.raises(DomainError) as error:
        validate(ledger, locator)
    assert error.value.detail["reason"] == "snapshot_locator_invalid"


def test_leading_newline_in_region_can_use_later_real_nonblank_fragment(ledger):
    set_page(ledger, body="first\r\n第二行\r\n", cursor=5)
    proof = validate(ledger, "chars:5:10")
    assert (proof.start, proof.end) == (5, 10)


@pytest.mark.parametrize("change", ["extra_field", "body", "page_hash", "end", "cursor",
                                    "locator", "content_hash", "receipt", "snapshot"])
def test_complete_page_is_revalidated_after_fragment_witness(ledger, change):
    f = ledger
    if change == "extra_field":
        f.call.result["qualified"] = True
    elif change == "body":
        f.call.result["markdown"] += "model-added text"
    elif change in {"page_hash", "content_hash"}:
        f.call.result[change] = "f" * 64
    elif change == "end":
        f.call.result["end"] += 2
    elif change == "cursor":
        f.call.result["cursor"] -= 1
    elif change == "locator":
        f.call.result["locator"] = "chars:0:999"
    elif change == "receipt":
        f.call.result["registration_receipt_id"] = str(uuid4())
    else:
        f.call.result["snapshot_id"] = str(uuid4())
    with pytest.raises(DomainError):
        validate(f, "line:2")


@pytest.mark.parametrize("marker", [None, False, True, "1", 0, 2])
def test_cross_run_registration_requires_strict_proof_version_one(ledger, marker):
    if marker is None:
        del ledger.receipt.result["proof_version"]
    else:
        ledger.receipt.result["proof_version"] = marker
    with pytest.raises(DomainError) as error:
        validate(ledger, "line:2")
    assert error.value.detail["reason"] == "snapshot_registration_mismatch"


@pytest.mark.parametrize("change", ["call_run", "call_started", "ordinary_binding",
    "extra_binding", "no_call", "private", "withdrawn", "changed_source", "cancelled",
    "inactive_writer", "lost_requester_grant"])
def test_current_authority_and_actual_registered_call_remain_required(ledger, change):
    f = ledger
    if change == "call_run":
        f.call.run_id = uuid4()
    elif change == "call_started":
        f.call.state = "started"
    elif change == "ordinary_binding":
        f.call.execution_binding["read_kind"] = "ordinary/v1"
    elif change == "extra_binding":
        f.call.execution_binding["approved"] = True
    elif change == "no_call":
        with pytest.raises(DomainError):
            validate(f, "line:2", call_id=uuid4())
        return
    elif change == "private":
        f.snapshot.visibility = "private"
    elif change == "withdrawn":
        f.snapshot.status = "withdrawn"
    elif change == "changed_source":
        f.snapshot.markdown += "changed"
    elif change == "cancelled":
        f.run.state = "cancelled"
    elif change == "inactive_writer":
        f.session.get(Principal, f.run.writer_id).active = False
    else:
        for key, row in list(f.session.rows.items()):
            if key[0] is Grant and row.principal_id == f.run.requester_id:
                del f.session.rows[key]
    with pytest.raises(DomainError):
        validate(f, "line:2")


@pytest.mark.parametrize("version", [True, False, "1", 0, 2])
def test_snapshot_version_is_strict_current_version(ledger, version):
    with pytest.raises(DomainError):
        validate(ledger, "line:2", version=version)


def test_completed_run_does_not_need_reopening_for_consumption(ledger):
    ledger.run.state = "completed"
    assert validate(ledger, "line:2")
    assert ledger.run.state == "completed"
