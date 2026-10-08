"""Located document derivation, distinct from original storage and malware scanning."""

from .isolation import parse_original
from .types import ParseFailure, ParseLimits, ParseResult, SourceLocation, TextSegment

__all__ = [
    "ParseFailure",
    "ParseLimits",
    "ParseResult",
    "SourceLocation",
    "TextSegment",
    "parse_original",
]
