"""Operation identities; declaring these does not register a public command."""

AUTHORIZE = "integration.handoff.authorize"
RECEIPT_RECORD = "integration.receipt.record"
SCHEMA_VERSION = "pdos-external-handoff-v1"
RECEIPT_SCHEMA_VERSION = "pdos-external-receipt-v1"
OPERATIONS = {
    AUTHORIZE: ("T2", "external_handoff.authorized"),
    RECEIPT_RECORD: ("T0", "external_receipt.recorded"),
}
