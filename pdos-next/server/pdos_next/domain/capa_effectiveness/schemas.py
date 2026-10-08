"""Actual candidate command aliases; scope and proof are server-owned material."""

from .candidate_commands import CandidateRecordPayload
from .candidate_write import CandidateReceiptHashes

__all__ = ["CandidateRecordPayload", "CandidateReceiptHashes"]
