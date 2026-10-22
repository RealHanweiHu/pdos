from dataclasses import asdict, dataclass
from typing import Literal


class ParseFailure(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code, self.message, self.retryable = code, message, retryable

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "retryable": self.retryable}


@dataclass(frozen=True, slots=True)
class ParseLimits:
    max_input_bytes: int = 10_000_000
    max_text_chars: int = 200_000
    max_segments: int = 20_000
    max_pdf_pages: int = 100
    max_sheets: int = 30
    max_rows_per_sheet: int = 10_000
    max_columns_per_sheet: int = 200
    max_zip_entries: int = 1_000
    max_zip_expanded_bytes: int = 50_000_000
    max_zip_ratio: int = 100
    timeout_seconds: float = 15
    cpu_seconds: int = 10
    memory_bytes: int = 536_870_912

    def __post_init__(self):
        if any(value <= 0 for value in asdict(self).values()):
            raise ValueError("Parser limits must be positive")
        if self.timeout_seconds > 60 or self.cpu_seconds > 30:
            raise ValueError("Parser time budgets must be bounded")
        if self.max_input_bytes > 50_000_000 or self.max_text_chars > 1_000_000:
            raise ValueError("Parser input/output budgets must be bounded")
        ceilings = {
            "max_segments": 100_000,
            "max_pdf_pages": 1_000,
            "max_sheets": 100,
            "max_rows_per_sheet": 100_000,
            "max_columns_per_sheet": 1_000,
            "max_zip_entries": 2_000,
            "max_zip_expanded_bytes": 100_000_000,
            "max_zip_ratio": 200,
            "memory_bytes": 1_073_741_824,
        }
        if any(getattr(self, name) > ceiling for name, ceiling in ceilings.items()):
            raise ValueError("Parser resource budgets must be bounded")


@dataclass(frozen=True, slots=True)
class SourceLocation:
    kind: Literal["line", "page", "cell"]
    line: int | None = None
    page: int | None = None
    sheet: str | None = None
    row: int | None = None
    column: int | None = None
    cell: str | None = None


@dataclass(frozen=True, slots=True)
class TextSegment:
    text: str
    location: SourceLocation
    value_kind: str = "text"


@dataclass(frozen=True, slots=True)
class ParseResult:
    source_sha256: str
    media_type: str
    text: str
    segments: tuple[TextSegment, ...]
    status: Literal["parsed", "needs_ocr"] = "parsed"
    parser_version: str = "pdos-evidence-v1"
    scan_status: Literal["not_scanned"] = "not_scanned"
    warnings: tuple[str, ...] = ()
    # Parser-declared inventory of every location it examined, including ones
    # that produced no text; never a model completeness declaration.
    expected_locations: tuple[SourceLocation, ...] = ()

    def as_dict(self) -> dict:
        return asdict(self)
