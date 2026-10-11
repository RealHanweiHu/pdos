import asyncio
import hashlib
from io import BytesIO
from uuid import uuid4

import pytest
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, StreamObject

from pdos_next.agent_kernel.types import RunScope
from pdos_next.evidence_processing.types import (
    ParseFailure,
    ParseResult,
    SourceLocation,
    TextSegment,
)
from pdos_next.research import ContainerPDFAdapter, HTTPResponse, ResearchError, ResearchTask

from .test_research import Transport, draft, run, scope, service


def synthetic_pdf():
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=200)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    stream = StreamObject()
    stream.set_data(b"BT /F1 12 Tf 30 90 Td (Pressure: 20 psi at 25 C.) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_actual_synthetic_public_pdf_uses_fixed_image_isolated_container():
    content = synthetic_pdf()
    document = run(
        ContainerPDFAdapter()(scope().child("research"), content, "https://maker.example/specs.pdf")
    )
    assert document.title == "specs.pdf"
    assert "Pressure: 20 psi at 25 C." in document.markdown
    assert "## Page 1" in document.markdown
    assert document.status == "ok"


def test_pdf_parser_original_isolation_failure_has_no_host_fallback():
    class Unavailable:
        async def parse_async(self, *_args, **_kwargs):
            raise ParseFailure("ISOLATION_UNAVAILABLE", "Verified image missing", retryable=True)

    adapter = ContainerPDFAdapter(runner=Unavailable())
    with pytest.raises(ResearchError) as error:
        run(adapter(scope().child("research"), synthetic_pdf(), "https://maker.example/p.pdf"))
    assert error.value.reason == "pdf_parse_failed"
    assert error.value.service_code == "ISOLATION_UNAVAILABLE"
    assert error.value.message == "Verified image missing"


def test_needs_ocr_partial_and_located_pdf_text_joins_research_snapshot():
    content = synthetic_pdf()

    class PartialParser:
        async def parse_async(self, body, **kwargs):
            assert body == content and kwargs["media_type"] == "application/pdf"
            return ParseResult(
                hashlib.sha256(content).hexdigest(),
                "application/pdf",
                "Pressure: 20 psi at 25 C.",
                (TextSegment("Pressure: 20 psi at 25 C.", SourceLocation("page", page=1)),),
                status="needs_ocr",
                warnings=("page 2 requires OCR",),
            )

    transport = Transport(
        {
            "https://maker.example/specs": HTTPResponse(
                200, (("Content-Type", "application/pdf"),), content
            )
        }
    )
    instance, bound = (
        service(transport=transport, pdf_parser=ContainerPDFAdapter(runner=PartialParser())),
        scope(),
    )

    async def researcher(task, child):
        page = await child.read((await child.search("pump"))[0].url)
        return [draft(page)]

    result = run(instance.fanout(bound, [ResearchTask("pdf", "pressure")], researcher))
    assert result.ledger[0].status == "ok"
    assert result.snapshots[0].status == "partial" and result.status == "partial"


def test_batched_concurrent_reads_reuse_one_snapshot_and_store_once():
    calls, stored, bound = [], [], scope()

    class Delayed(Transport):
        async def request(self, url, address, limits):
            calls.append(url)
            await asyncio.sleep(0.01)
            return await super().request(url, address, limits)

    instance = service(transport=Delayed(), snapshot_sink=lambda _, snap: stored.append(snap))

    async def both():
        await instance.search(bound, "pump")
        return await asyncio.gather(
            *(
                instance.read(bound.child("research"), "https://maker.example/specs")
                for _ in range(8)
            )
        )

    pages = run(both())
    assert len(calls) == len(stored) == 1
    assert len({page.snapshot.id for page in pages}) == 1


def test_coverage_lists_exact_unread_character_ranges_and_json_is_persistable():
    from pdos_next.research import ResourceLimits

    instance, bound = service(limits=ResourceLimits(page_chars=5)), scope()

    async def researcher(task, child):
        page = await child.read((await child.search("pump"))[0].url, cursor=5)
        return [draft(page, quote=page.markdown)]

    result = run(instance.fanout(bound, [ResearchTask("page", "pressure")], researcher))
    unread = result.coverage[0].unread_locations
    assert unread[0].locator == "chars:0:5"
    assert unread[1].locator.startswith("chars:10:")
    assert result.status == "partial"
    import json

    json.dumps(result.to_dict(), allow_nan=False)


def test_egress_denied_before_any_dns_lookup():
    from pdos_next.errors import DomainError

    looked_up, bound = [], scope()

    async def dns(host):
        looked_up.append(host)
        return ("8.8.8.8",)

    def deny(scope, provider, categories, text):
        raise DomainError("FORBIDDEN_SCOPE", "Denied outbound URL")

    instance = service(egress=deny)
    instance.resolver = dns
    instance.register_user_message(bound, "https://maker.example/specs")
    with pytest.raises(DomainError):
        run(instance.read(bound.child("research"), "https://maker.example/specs"))
    assert looked_up == []


def test_failed_user_read_and_real_run_cancellation_do_not_become_fake_completion():
    from pdos_next.errors import DomainError

    bound = RunScope(*(uuid4() for _ in range(6)))
    instance = service()

    async def canceled(task, child):
        raise DomainError("CANCELLED_RUN", "Canceled by requester")

    with pytest.raises(DomainError) as error:
        run(instance.fanout(bound, [ResearchTask("a", "pressure")], canceled))
    assert error.value.code == "CANCELLED_RUN"
