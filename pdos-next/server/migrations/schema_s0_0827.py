"""Restore omitted source-reference triggers on already registered consuming tables."""

TABLES = (
    "external_wait_versions",
    "external_wait_currents",
    "project_risk_followups",
    "project_risk_followup_currents",
    "knowledge_candidate_versions",
    "knowledge_candidate_currents",
    "knowledge_rule_versions",
    "knowledge_rule_currents",
    "knowledge_applicability_assessments",
    "field_feedback_versions",
    "field_feedback_currents",
    "field_response_records",
)

SCHEMA_SQL = tuple(
    statement
    for table in TABLES
    for statement in (
        f"CREATE TRIGGER lifecycle_reference BEFORE INSERT OR UPDATE OR DELETE ON public.{table} "
        "FOR EACH ROW EXECUTE FUNCTION public.lifecycle_reference_gate()",
        "CREATE TRIGGER category_lifecycle_clock AFTER INSERT OR UPDATE OR DELETE "
        f"ON public.{table} "
        "FOR EACH ROW EXECUTE FUNCTION public.category_lifecycle_clock()",
    )
)
DOWNGRADE_SQL = tuple(
    statement
    for table in reversed(TABLES)
    for statement in (
        f"DROP TRIGGER category_lifecycle_clock ON public.{table}",
        f"DROP TRIGGER lifecycle_reference ON public.{table}",
    )
)
