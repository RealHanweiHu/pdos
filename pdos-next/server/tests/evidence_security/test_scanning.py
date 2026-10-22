import asyncio
import hashlib
import io
import struct
import threading
import zipfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from pdos_next.evidence_security import (
    ObjectStoreScannerAdapter,
    ScanBinding,
    ScanConfiguration,
    ScanLimits,
    ScannerIdentity,
    ScannerReply,
    ScanPolicy,
    ScanReceipt,
    ScanRequest,
    ScanStatus,
    SecurityFailure,
    SecurityState,
    bind_request,
    check_content,
    parsing_gate,
)
from pdos_next.evidence_security.preflight import XLSX
from pdos_next.object_storage import LocalPrivateObjectStore, ObjectRef, StorageFailure

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)
IDENTITY = ScannerIdentity("fake-local-unit-check", "engine-v1", "rules-v1")


def reference(content=b"harmless synthetic text", media="text/plain"):
    identity, digest = uuid4(), hashlib.sha256(content).hexdigest()
    return ObjectRef(
        identity, 1, digest, len(content), media, f"originals/{identity.hex}/v1/{digest}"
    )


def request(content=b"harmless synthetic text", media="text/plain", limits=None):
    binding = ScanBinding(
        reference(content, media), uuid4(), uuid4(), uuid4(), 1, "acl-v1", "audience-v1", True
    )
    return ScanRequest(uuid4(), binding, IDENTITY, ScanPolicy(limits=limits or ScanLimits()), NOW)


class MemoryReader:
    def __init__(self, content):
        self.content, self.calls = content, 0

    def read_original(self, ref):
        self.calls += 1
        return self.content


class FakeScanner:
    def __init__(self, status=ScanStatus.CLEAN, *, delay=0):
        self.status, self.delay, self.calls = status, delay, 0

    async def inspect(self, req, content):
        self.calls += 1
        await asyncio.sleep(self.delay)
        return ScannerReply(req.request_id, req.binding.object_ref, req.scanner, self.status)


class Guard:
    def __init__(self, binding):
        self.binding, self.current = binding, True
        self.configuration = ScanConfiguration(IDENTITY, ScanPolicy())

    def current_configuration(self):
        return self.configuration

    def bind_for_scan(self, ref):
        return self.binding

    def is_current(self, binding):
        return self.current and binding == self.binding


def receipt(req, status=ScanStatus.CLEAN):
    return ScanReceipt(
        req.request_id,
        req.binding,
        req.scanner,
        req.policy.digest,
        status,
        NOW,
        NOW + timedelta(seconds=1),
    )


def archive(entries=None, *, compression=zipfile.ZIP_STORED):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=compression) as output:
        for name, content in (
            entries
            or {
                "[Content_Types].xml": b"<Types/>",
                "xl/workbook.xml": b"<workbook/>",
            }
        ).items():
            output.writestr(name, content)
    return stream.getvalue()


def test_missing_scanner_is_unavailable_and_never_clean():
    req = request()
    result = asyncio.run(
        ObjectStoreScannerAdapter(MemoryReader(b"harmless synthetic text"), clock=lambda: NOW).scan(
            req
        )
    )
    assert result.status == ScanStatus.UNAVAILABLE
    assert result.error_code == "SCANNER_UNAVAILABLE"
    gate = parsing_gate(req, result, Guard(req.binding), now=NOW)
    assert gate.state == SecurityState.SCAN_FAILED
    assert not gate.allow_parse and gate.quarantine_required


@pytest.mark.parametrize("status", list(ScanStatus)[:-1])
def test_all_scanner_results_preserve_status_and_only_clean_allows_parse(status):
    req = request()
    transport = FakeScanner(status)
    result = asyncio.run(
        ObjectStoreScannerAdapter(
            MemoryReader(b"harmless synthetic text"), transport, clock=lambda: NOW
        ).scan(req)
    )
    assert result.status == status
    assert transport.calls == 1
    gate = parsing_gate(req, result, Guard(req.binding), now=NOW)
    assert gate.allow_parse == (status == ScanStatus.CLEAN)


def test_real_local_store_adapter_reads_only_owned_temporary_synthetic_original(tmp_path):
    store = LocalPrivateObjectStore(tmp_path / "owned-synthetic-scan-store")
    content = b"synthetic adapter check"
    ref = store.put_new(content, media_type="text/plain")
    req = request(content)
    req = replace(req, binding=replace(req.binding, object_ref=ref))
    result = asyncio.run(
        ObjectStoreScannerAdapter(store, FakeScanner(), clock=lambda: NOW).scan(req)
    )
    assert result.status == ScanStatus.CLEAN
    assert result.binding.object_ref == ref


@pytest.mark.parametrize(
    "content,media,code",
    [
        (b"%PDF-1.7\n%%EOF", "text/plain", "TYPE_MISMATCH"),
        (b"MZ harmless marker", "text/plain", "TYPE_MISMATCH"),
        (b"abc\x00def", "text/plain", "TYPE_MISMATCH"),
        (b"\xff", "text/plain", "TYPE_MISMATCH"),
        (b"not a pdf", "application/pdf", "TYPE_MISMATCH"),
        (b"%PDF-1.7 no ending", "application/pdf", "TYPE_MISMATCH"),
        (b"not a zip", XLSX, "TYPE_MISMATCH"),
        (b"text", "application/octet-stream", "UNSUPPORTED_MEDIA_TYPE"),
    ],
)
def test_type_budget_checks_are_not_malware_certification(content, media, code):
    req = request(content, media)
    with pytest.raises(SecurityFailure, match=code):
        check_content(req, content)


@pytest.mark.parametrize(
    "content,media",
    [
        (b"harmless UTF-8 \xe4\xb8\xad", "text/plain"),
        (b"# harmless markdown", "text/markdown"),
        (b"%PDF-1.7\nsynthetic nonparseable body\n%%EOF", "application/pdf"),
        (archive(), XLSX),
    ],
)
def test_preflight_accepts_supported_envelopes_without_claiming_clean(content, media):
    assert check_content(request(content, media), content) is None


@pytest.mark.parametrize(
    "mutation",
    [
        lambda req: replace(
            req, binding=replace(req.binding, object_ref=reference(b"same-size other content"))
        ),
        lambda req: replace(req, policy=replace(req.policy, limits=ScanLimits(max_input_bytes=5))),
    ],
)
def test_integrity_and_size_reject_before_transport(mutation):
    req = mutation(request())
    scanner = FakeScanner()
    result = asyncio.run(
        ObjectStoreScannerAdapter(
            MemoryReader(b"harmless synthetic text"), scanner, clock=lambda: NOW
        ).scan(req)
    )
    assert result.status == ScanStatus.REJECTED
    assert scanner.calls == 0


@pytest.mark.parametrize(
    "name,code",
    [
        ("../outside.xml", "UNSAFE_ARCHIVE_ENTRY"),
        ("/absolute.xml", "UNSAFE_ARCHIVE_ENTRY"),
        ("xl\\bad.xml", "UNSAFE_ARCHIVE_ENTRY"),
        ("xl/vbaProject.bin", "ACTIVE_CONTENT_REJECTED"),
        ("xl/activeX/a.xml", "ACTIVE_CONTENT_REJECTED"),
        ("xl/embeddings/object.bin", "ACTIVE_CONTENT_REJECTED"),
    ],
)
def test_archive_entry_rejections(name, code):
    content = archive({"[Content_Types].xml": b"x", "xl/workbook.xml": b"x", name: b"x"})
    with pytest.raises(SecurityFailure, match=code):
        check_content(request(content, XLSX), content)


@pytest.mark.parametrize(
    "limits,code",
    [
        (ScanLimits(max_zip_entries=1), "ARCHIVE_ENTRY_LIMIT"),
        (ScanLimits(max_zip_entry_bytes=2), "ARCHIVE_ENTRY_BYTES_LIMIT"),
        (ScanLimits(max_zip_expanded_bytes=10), "ARCHIVE_EXPANDED_LIMIT"),
    ],
)
def test_archive_budgets(limits, code):
    content = archive()
    with pytest.raises(SecurityFailure, match=code):
        check_content(request(content, XLSX, limits), content)


def test_compression_ratio_rejected_without_decompressing_large_payload():
    content = archive(
        {"[Content_Types].xml": b"x", "xl/workbook.xml": b"a" * 20_000},
        compression=zipfile.ZIP_DEFLATED,
    )
    with pytest.raises(SecurityFailure, match="ARCHIVE_RATIO_LIMIT"):
        check_content(request(content, XLSX), content)


def test_central_directory_cannot_lie_to_bypass_entry_allocation_budget():
    content = bytearray(archive())
    end = content.rfind(b"PK\x05\x06")
    struct.pack_into("<2H", content, end + 8, 1, 1)
    content = bytes(content)
    with pytest.raises(SecurityFailure, match="ARCHIVE_ENTRY_LIMIT"):
        check_content(request(content, XLSX, ScanLimits(max_zip_entries=1)), content)


def test_truncated_archive_fails_closed():
    content = archive()[:-3]
    with pytest.raises(SecurityFailure):
        check_content(request(content, XLSX), content)


def test_transport_timeout_is_not_clean():
    req = request(limits=ScanLimits(timeout_seconds=0.05))
    result = asyncio.run(
        ObjectStoreScannerAdapter(
            MemoryReader(b"harmless synthetic text"), FakeScanner(delay=0.2), clock=lambda: NOW
        ).scan(req)
    )
    assert result.status == ScanStatus.TIMEOUT


def test_timed_out_reads_hold_capacity_until_the_underlying_read_finishes():
    release = threading.Event()

    class SlowReader(MemoryReader):
        def read_original(self, ref):
            self.calls += 1
            release.wait(1)
            return self.content

    async def scenario():
        reader = SlowReader(b"harmless synthetic text")
        adapter = ObjectStoreScannerAdapter(
            reader, FakeScanner(), max_inflight_reads=1, clock=lambda: NOW
        )
        req = request(limits=ScanLimits(timeout_seconds=0.03))
        try:
            first = await adapter.scan(req)
            second = await adapter.scan(req)
            assert first.status == second.status == ScanStatus.TIMEOUT
            assert reader.calls == 1
        finally:
            release.set()

    asyncio.run(scenario())


@pytest.mark.parametrize("field", ["request_id", "object_ref", "scanner"])
def test_mismatched_scanner_response_fails_closed(field):
    class BadScanner:
        async def inspect(self, req, content):
            reply = ScannerReply(
                req.request_id, req.binding.object_ref, req.scanner, ScanStatus.CLEAN
            )
            change = {
                "request_id": uuid4(),
                "object_ref": reference(),
                "scanner": replace(IDENTITY, rules_version="other-rules"),
            }[field]
            return replace(reply, **{field: change})

    req = request()
    result = asyncio.run(
        ObjectStoreScannerAdapter(
            MemoryReader(b"harmless synthetic text"), BadScanner(), clock=lambda: NOW
        ).scan(req)
    )
    assert result.status == ScanStatus.UNKNOWN and result.error_code == "SCAN_PROTOCOL_ERROR"


def test_storage_failure_does_not_call_scanner_or_leak_diagnostics():
    class MissingReader:
        def read_original(self, ref):
            raise StorageFailure("OBJECT_NOT_FOUND", "private text must not leak")

    scanner = FakeScanner()
    result = asyncio.run(
        ObjectStoreScannerAdapter(MissingReader(), scanner, clock=lambda: NOW).scan(request())
    )
    assert result.status == ScanStatus.UNAVAILABLE
    assert result.error_code == "OBJECT_NOT_FOUND" and scanner.calls == 0


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: replace(r, request_id=uuid4()),
        lambda r: replace(r, binding=replace(r.binding, original_revision=2)),
        lambda r: replace(r, binding=replace(r.binding, access_revision="acl-v2")),
        lambda r: replace(r, binding=replace(r.binding, audience_revision="audience-v2")),
        lambda r: replace(r, binding=replace(r.binding, tenant_id=uuid4())),
        lambda r: replace(r, scanner=replace(r.scanner, rules_version="rules-v2")),
        lambda r: replace(r, scanner=replace(r.scanner, engine_version="engine-v2")),
        lambda r: replace(r, policy_digest="0" * 64),
    ],
)
def test_receipt_binding_drift_requires_rescan(mutation):
    req = request()
    gate = parsing_gate(
        req, mutation(receipt(req)), Guard(req.binding), now=NOW + timedelta(seconds=2)
    )
    assert gate.state == SecurityState.STALE and not gate.allow_parse


@pytest.mark.parametrize("hours", [-1, 25])
def test_receipt_future_time_and_expiry_fail_closed(hours):
    req = request()
    gate = parsing_gate(req, receipt(req), Guard(req.binding), now=NOW + timedelta(hours=hours))
    assert not gate.allow_parse and gate.state == SecurityState.STALE


def test_no_receipt_permission_revocation_source_withdrawal_and_guard_outage():
    req = request()
    guard = Guard(req.binding)
    assert parsing_gate(req, None, guard, now=NOW).state == SecurityState.NOT_SCANNED
    guard.current = False
    assert not parsing_gate(req, receipt(req), guard, now=NOW).allow_parse
    with pytest.raises(SecurityFailure):
        bind_request(
            guard,
            req.binding.object_ref,
            request_id=uuid4(),
            scanner=IDENTITY,
            policy=req.policy,
            now=NOW,
        )
    withdrawn = replace(req, binding=replace(req.binding, source_active=False))
    assert not parsing_gate(withdrawn, None, Guard(withdrawn.binding), now=NOW).allow_parse

    def outage(binding):
        raise RuntimeError("private context")

    guard.is_current = outage
    assert not parsing_gate(req, receipt(req), guard, now=NOW).allow_parse


@pytest.mark.parametrize(
    "limits",
    [
        {"max_input_bytes": 0},
        {"max_input_bytes": 50_000_001},
        {"max_zip_entries": 2001},
        {"timeout_seconds": float("nan")},
        {"timeout_seconds": float("inf")},
        {"timeout_seconds": 61},
        {"max_zip_ratio": True},
    ],
)
def test_invalid_or_unbounded_limits(limits):
    with pytest.raises(ValueError):
        ScanLimits(**limits)


def test_error_result_and_raw_diagnostic_text_cannot_certify_clean():
    req = request()
    with pytest.raises(ValueError):
        replace(receipt(req), error_code="ERROR")
    with pytest.raises(ValueError):
        ScannerReply(
            req.request_id,
            req.binding.object_ref,
            req.scanner,
            ScanStatus.UNKNOWN,
            "private original snippets",
        )


def test_original_versions_are_not_invented_by_scanner_package():
    with pytest.raises(ValueError):
        replace(reference(), version=2)


def test_receipt_schema_rejects_unaware_times_and_untyped_status():
    req = request()
    with pytest.raises(ValueError):
        replace(receipt(req), started_at=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError):
        replace(receipt(req), status="clean")


def test_cross_object_guard_cannot_bind_another_source():
    req = request()
    with pytest.raises(SecurityFailure):
        bind_request(
            Guard(req.binding),
            reference(b"another source"),
            request_id=uuid4(),
            scanner=IDENTITY,
            policy=req.policy,
            now=NOW,
        )


@pytest.mark.parametrize("answer", ["unknown", 1, None, object()])
def test_non_boolean_authority_answers_never_allow_clean(answer):
    req = request()
    guard = Guard(req.binding)
    guard.is_current = lambda binding: answer
    assert not parsing_gate(req, receipt(req), guard, now=NOW + timedelta(seconds=2)).allow_parse
    with pytest.raises(SecurityFailure):
        bind_request(
            guard,
            req.binding.object_ref,
            request_id=uuid4(),
            scanner=req.scanner,
            policy=req.policy,
            now=NOW,
        )


@pytest.mark.parametrize(
    "configuration",
    [
        ScanConfiguration(replace(IDENTITY, rules_version="new-rules"), ScanPolicy()),
        ScanConfiguration(IDENTITY, ScanPolicy(version="new-policy")),
        "unknown",
    ],
)
def test_current_configuration_upgrade_invalidates_old_request_and_receipt(configuration):
    req = request()
    guard = Guard(req.binding)
    guard.configuration = configuration
    gate = parsing_gate(req, receipt(req), guard, now=NOW + timedelta(seconds=2))
    assert not gate.allow_parse and "SCANNER_CONFIGURATION_CHANGED" in gate.reasons
    with pytest.raises(SecurityFailure):
        bind_request(
            guard,
            req.binding.object_ref,
            request_id=uuid4(),
            scanner=req.scanner,
            policy=req.policy,
            now=NOW,
        )


@pytest.mark.parametrize("code", ["private diagnostic text", [], {}])
def test_storage_raw_error_code_is_normalized_to_unavailable_receipt(code):
    class BadReader:
        def read_original(self, ref):
            raise StorageFailure(code, "private original must not leak")

    result = asyncio.run(
        ObjectStoreScannerAdapter(BadReader(), FakeScanner(), clock=lambda: NOW).scan(request())
    )
    assert result.status == ScanStatus.UNAVAILABLE and result.error_code == "STORAGE_UNAVAILABLE"


def test_archive_null_truncated_names_cannot_hide_active_content():
    name = "safe.xmlQxl/vbaProject.bin"
    content = archive({"[Content_Types].xml": b"x", "xl/workbook.xml": b"x", name: b"x"})
    content = content.replace(name.encode(), name.replace("Q", "\x00").encode())
    with pytest.raises(SecurityFailure, match="UNSAFE_ARCHIVE_ENTRY"):
        check_content(request(content, XLSX), content)


def test_duplicate_archive_entry_is_rejected():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as output:
        output.writestr("[Content_Types].xml", b"x")
        output.writestr("xl/workbook.xml", b"x")
        with pytest.warns(UserWarning):
            output.writestr("xl/workbook.xml", b"other")
    content = stream.getvalue()
    with pytest.raises(SecurityFailure, match="UNSAFE_ARCHIVE_ENTRY"):
        check_content(request(content, XLSX), content)


def test_symlink_archive_entries_are_rejected():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as output:
        output.writestr("[Content_Types].xml", b"x")
        output.writestr("xl/workbook.xml", b"x")
        link = zipfile.ZipInfo("xl/synthetic-link.xml")
        link.create_system = 3
        link.external_attr = 0o120777 << 16
        output.writestr(link, b"synthetic-target")
    content = stream.getvalue()
    with pytest.raises(SecurityFailure, match="UNSAFE_ARCHIVE_ENTRY"):
        check_content(request(content, XLSX), content)


def test_encrypted_and_corrupted_archives_are_rejected():
    content = bytearray(archive())
    central = content.find(b"PK\x01\x02")
    struct.pack_into("<H", content, central + 8, 1)
    content = bytes(content)
    with pytest.raises(SecurityFailure, match="UNSAFE_ARCHIVE_ENTRY"):
        check_content(request(content, XLSX), content)
    content = archive().replace(b"<Types/>", b"<BadCRC>")
    with pytest.raises(SecurityFailure, match="MALFORMED_ARCHIVE"):
        check_content(request(content, XLSX), content)


def test_whole_scan_over_budget_and_clock_regression_never_certify_clean():
    req = request()
    late = replace(receipt(req), completed_at=NOW + timedelta(seconds=16))
    assert not parsing_gate(
        req, late, Guard(req.binding), now=NOW + timedelta(seconds=20)
    ).allow_parse
    ticks = iter((NOW, NOW - timedelta(seconds=1)))
    result = asyncio.run(
        ObjectStoreScannerAdapter(
            MemoryReader(b"harmless synthetic text"), FakeScanner(), clock=lambda: next(ticks)
        ).scan(req)
    )
    assert result.status == ScanStatus.UNKNOWN and result.error_code == "CLOCK_MOVED_BACKWARD"


def test_late_clean_from_transport_suppressing_cancellation_is_timeout():
    class LateScanner:
        async def inspect(self, req, content):
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                return ScannerReply(
                    req.request_id, req.binding.object_ref, req.scanner, ScanStatus.CLEAN
                )

    req = request(limits=ScanLimits(timeout_seconds=0.03))
    result = asyncio.run(
        ObjectStoreScannerAdapter(
            MemoryReader(b"harmless synthetic text"), LateScanner(), clock=lambda: NOW
        ).scan(req)
    )
    assert result.status == ScanStatus.TIMEOUT


def test_bool_object_version_and_size_are_rejected_at_consumption_boundary():
    req = request(b"x")
    with pytest.raises(ValueError):
        replace(req.binding, object_ref=replace(req.binding.object_ref, version=True))
    with pytest.raises(ValueError):
        replace(req.binding, object_ref=replace(req.binding.object_ref, size_bytes=True))


def test_uncancellable_transport_returns_timeout_and_holds_bounded_capacity():
    async def scenario():
        release = asyncio.Event()

        class HoldingScanner:
            calls = 0

            async def inspect(self, req, content):
                self.calls += 1
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    await release.wait()
                return ScannerReply(
                    req.request_id, req.binding.object_ref, req.scanner, ScanStatus.CLEAN
                )

        scanner = HoldingScanner()
        adapter = ObjectStoreScannerAdapter(
            MemoryReader(b"harmless synthetic text"),
            scanner,
            max_inflight_reads=1,
            clock=lambda: NOW,
        )
        req = request(limits=ScanLimits(timeout_seconds=0.03))
        try:
            assert (await adapter.scan(req)).status == ScanStatus.TIMEOUT
            assert (await adapter.scan(req)).status == ScanStatus.TIMEOUT
            assert scanner.calls == 1
        finally:
            release.set()
            await asyncio.sleep(0)

    asyncio.run(scenario())


def test_malformed_sync_transport_and_self_cancelled_scanner_return_unavailable():
    class SyncScanner:
        def inspect(self, req, content):
            return ScannerReply(
                req.request_id, req.binding.object_ref, req.scanner, ScanStatus.CLEAN
            )

    class SelfCancellingScanner:
        async def inspect(self, req, content):
            raise asyncio.CancelledError

    async def scenario():
        for scanner in (SyncScanner(), SelfCancellingScanner()):
            adapter = ObjectStoreScannerAdapter(
                MemoryReader(b"harmless synthetic text"),
                scanner,
                max_inflight_reads=1,
                clock=lambda: NOW,
            )
            for _ in range(2):
                assert (await adapter.scan(request())).status == ScanStatus.UNAVAILABLE

    asyncio.run(scenario())
