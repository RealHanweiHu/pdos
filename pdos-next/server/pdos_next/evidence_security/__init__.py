"""Bounded original scanning and fail-closed gates, separate from parsing and authorization."""

from .adapter import ObjectStoreScannerAdapter
from .preflight import check_content
from .rules import bind_request, parsing_gate
from .types import (
    ScanBinding,
    ScanConfiguration,
    ScanGuardPort,
    ScanLimits,
    ScannerIdentity,
    ScannerPort,
    ScannerReply,
    ScanPolicy,
    ScanReceipt,
    ScanReceiptStorePort,
    ScanRequest,
    ScanStatus,
    ScanTransportPort,
    SecurityDecision,
    SecurityFailure,
    SecurityState,
)

__all__ = [
    "ObjectStoreScannerAdapter",
    "ScannerIdentity",
    "ScannerPort",
    "ScannerReply",
    "ScanBinding",
    "ScanConfiguration",
    "ScanGuardPort",
    "ScanLimits",
    "ScanPolicy",
    "ScanReceipt",
    "ScanReceiptStorePort",
    "ScanRequest",
    "ScanStatus",
    "ScanTransportPort",
    "SecurityDecision",
    "SecurityFailure",
    "SecurityState",
    "bind_request",
    "check_content",
    "parsing_gate",
]
