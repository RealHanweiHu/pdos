"""Extend the existing action root walker with actual native parent columns."""

BASIS_TABLES = frozenset(
    {
        "project_status_updates",
        "manufacturing_preparation_versions",
        "manufacturing_baseline_publications",
        "verification_handoff_facts",
    }
)
PARENT_FIELDS = {
    "manufacturing_publication_documents": (
        ("publication_id", "manufacturing_baseline_publications"),
        ("document_id", "manufacturing_preparation_versions"),
    ),
    "verification_handoff_facts": (
        ("request_version_id", "verification_formal_requests"),
        ("next_request_version_id", "verification_formal_requests"),
    ),
}
