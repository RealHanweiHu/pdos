"""Public PDF adapter for the existing fixed-image, credential-free parser container."""

from urllib.parse import unquote, urlsplit

from pdos_next.evidence_processing.types import ParseFailure, ParseLimits
from pdos_next.security_runtime.parser import DockerParserRunner

from .types import ParsedDocument
from .web import ResearchError, ResourceLimits


class ContainerPDFAdapter:
    def __init__(self, *, runner=None, limits=None):
        limits = limits or ResourceLimits()
        self.runner = runner or DockerParserRunner()
        self.limits = ParseLimits(
            max_input_bytes=min(limits.max_body_bytes, 50_000_000),
            max_text_chars=min(limits.max_markdown_chars, 1_000_000),
            max_pdf_pages=1000,
            max_segments=100_000,
            timeout_seconds=min(limits.timeout_seconds, 60),
        )

    async def __call__(self, scope, content: bytes, url: str) -> ParsedDocument:
        if scope.isolation != "research":
            raise ResearchError("isolated_subtask_only", "Public PDF requires a research child")
        try:
            result = await self.runner.parse_async(
                content, media_type="application/pdf", limits=self.limits
            )
        except ParseFailure as exc:
            raise ResearchError(
                "pdf_parse_failed",
                exc.message,
                provider="isolated-public-pdf",
                service_code=exc.code,
            ) from exc
        if result.segments:
            markdown = "\n\n".join(
                f"## Page {segment.location.page}\n\n{segment.text}" for segment in result.segments
            )
        else:
            markdown = result.text
        title = unquote(urlsplit(url).path.rsplit("/", 1)[-1]) or "Public PDF"
        return ParsedDocument(
            title, markdown, "partial" if result.status == "needs_ocr" or result.warnings else "ok"
        )
