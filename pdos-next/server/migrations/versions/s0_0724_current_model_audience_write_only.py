"""Read eight Current/map scopes once; retain their complete write audience.

At reviewed s0_0723 each category_scope USING includes, as exact top-level AND
conjuncts, both original model_audience predicates: current category_access and
an exact tenant/category/product EXISTS under Product RLS. Seven also retain the
complete exact Fact/Issue EXISTS; quality_failure_maps has precisely those two.
Thus C AND M equals C for SELECT, including SQL's NULL truth semantics. Runtime
roles cannot take the ordinary owner's permissive branch. No Fact, source,
upstream, function, trigger, ACL or business row is changed.
"""

from alembic import op
from sqlalchemy import text

revision = "s0_0724"
down_revision = "s0_0723"
branch_labels = None
depends_on = None

# Exact reviewed pg_policies/material, not a dependency on an evidence file.
TABLES = (
    "build_current_authorizations",
    "build_operational_current",
    "quality_current_issues",
    "quality_failure_maps",
    "sample_current_readiness",
    "test_resource_current",
    "verification_current_actual_methods",
    "verification_current_formal_requests",
)
EXPECTED_POLICIES = [
    {
        "schemaname": "public",
        "tablename": "build_current_authorizations",
        "policyname": "category_scope",
        "permissive": "PERMISSIVE",
        "roles": ["public"],
        "cmd": "ALL",
        "qual": "(category_access(tenant_id, category_id) AND (EXISTS ( SELECT 1\n"
        "   FROM products p\n"
        "  WHERE ((p.tenant_id = build_current_authorizations.tenant_id) AND (p.category_id "
        "= build_current_authorizations.category_id) AND (p.id = "
        "build_current_authorizations.product_id)))) AND (EXISTS ( SELECT 1\n"
        "   FROM build_authorization_decisions p\n"
        "  WHERE ((p.tenant_id = build_current_authorizations.tenant_id) AND (p.product_id = "
        "build_current_authorizations.product_id) AND (p.project_id = "
        "build_current_authorizations.project_id) AND (p.build_id = "
        "build_current_authorizations.build_id) AND ((p.role)::text = "
        "(build_current_authorizations.role)::text) AND (p.id = "
        "build_current_authorizations.decision_id) AND (p.revision = "
        "build_current_authorizations.decision_revision)))))",
        "with_check": "(category_access(tenant_id, category_id, true) AND (EXISTS ( SELECT 1\n"
        "   FROM products p\n"
        "  WHERE ((p.tenant_id = build_current_authorizations.tenant_id) AND "
        "(p.category_id = build_current_authorizations.category_id) AND (p.id = "
        "build_current_authorizations.product_id)))) AND (EXISTS ( SELECT 1\n"
        "   FROM build_authorization_decisions p\n"
        "  WHERE ((p.tenant_id = build_current_authorizations.tenant_id) AND "
        "(p.product_id = build_current_authorizations.product_id) AND (p.project_id = "
        "build_current_authorizations.project_id) AND (p.build_id = "
        "build_current_authorizations.build_id) AND ((p.role)::text = "
        "(build_current_authorizations.role)::text) AND (p.id = "
        "build_current_authorizations.decision_id) AND (p.revision = "
        "build_current_authorizations.decision_revision)))))",
    },
    {
        "schemaname": "public",
        "tablename": "build_current_authorizations",
        "policyname": "model_audience",
        "permissive": "RESTRICTIVE",
        "roles": ["pdos_agent", "pdos_next_app", "pdos_next_auth", "pdos_next_dispatch"],
        "cmd": "ALL",
        "qual": "(category_access(tenant_id, category_id) AND (EXISTS ( SELECT 1\n"
        "   FROM products p\n"
        "  WHERE ((p.tenant_id = build_current_authorizations.tenant_id) AND (p.category_id "
        "= build_current_authorizations.category_id) AND (p.id = "
        "build_current_authorizations.product_id)))))",
        "with_check": "(category_access(tenant_id, category_id) AND (EXISTS ( SELECT 1\n"
        "   FROM products p\n"
        "  WHERE ((p.tenant_id = build_current_authorizations.tenant_id) AND "
        "(p.category_id = build_current_authorizations.category_id) AND (p.id = "
        "build_current_authorizations.product_id)))))",
    },
    {
        "schemaname": "public",
        "tablename": "build_current_authorizations",
        "policyname": "owner_internal",
        "permissive": "PERMISSIVE",
        "roles": ["pdos_next_owner"],
        "cmd": "ALL",
        "qual": "true",
        "with_check": "true",
    },
    {
        "schemaname": "public",
        "tablename": "build_operational_current",
        "policyname": "category_scope",
        "permissive": "PERMISSIVE",
        "roles": ["public"],
        "cmd": "ALL",
        "qual": "(category_access(tenant_id, category_id) AND (EXISTS ( SELECT 1\n"
        "   FROM products p\n"
        "  WHERE ((p.tenant_id = build_operational_current.tenant_id) AND (p.category_id = "
        "build_operational_current.category_id) AND (p.id = "
        "build_operational_current.product_id)))) AND (EXISTS ( SELECT 1\n"
        "   FROM build_operational_facts p\n"
        "  WHERE ((p.tenant_id = build_operational_current.tenant_id) AND (p.product_id = "
        "build_operational_current.product_id) AND (p.project_id = "
        "build_operational_current.project_id) AND (p.build_id = "
        "build_operational_current.build_id) AND (p.id = build_operational_current.fact_id) "
        "AND (p.revision = build_operational_current.fact_revision)))))",
        "with_check": "(category_access(tenant_id, category_id, true) AND (EXISTS ( SELECT 1\n"
        "   FROM products p\n"
        "  WHERE ((p.tenant_id = build_operational_current.tenant_id) AND "
        "(p.category_id = build_operational_current.category_id) AND (p.id = "
        "build_operational_current.product_id)))) AND (EXISTS ( SELECT 1\n"
        "   FROM build_operational_facts p\n"
        "  WHERE ((p.tenant_id = build_operational_current.tenant_id) AND "
        "(p.product_id = build_operational_current.product_id) AND (p.project_id = "
        "build_operational_current.project_id) AND (p.build_id = "
        "build_operational_current.build_id) AND (p.id = "
        "build_operational_current.fact_id) AND (p.revision = "
        "build_operational_current.fact_revision)))))",
    },
    {
        "schemaname": "public",
        "tablename": "build_operational_current",
        "policyname": "model_audience",
        "permissive": "RESTRICTIVE",
        "roles": ["pdos_agent", "pdos_next_app", "pdos_next_auth", "pdos_next_dispatch"],
        "cmd": "ALL",
        "qual": "(category_access(tenant_id, category_id) AND (EXISTS ( SELECT 1\n"
        "   FROM products p\n"
        "  WHERE ((p.tenant_id = build_operational_current.tenant_id) AND (p.category_id = "
        "build_operational_current.category_id) AND (p.id = "
        "build_operational_current.product_id)))))",
        "with_check": "(category_access(tenant_id, category_id) AND (EXISTS ( SELECT 1\n"
        "   FROM products p\n"
        "  WHERE ((p.tenant_id = build_operational_current.tenant_id) AND "
        "(p.category_id = build_operational_current.category_id) AND (p.id = "
        "build_operational_current.product_id)))))",
    },
    {
        "schemaname": "public",
        "tablename": "build_operational_current",
        "policyname": "owner_internal",
        "permissive": "PERMISSIVE",
        "roles": ["pdos_next_owner"],
        "cmd": "ALL",
        "qual": "true",
        "with_check": "true",
    },
    {
        "schemaname": "public",
        "tablename": "quality_current_issues",
        "policyname": "category_scope",
        "permissive": "PERMISSIVE",
        "roles": ["public"],
        "cmd": "ALL",
        "qual": "(category_access(tenant_id, category_id) AND (EXISTS ( SELECT 1\n"
        "   FROM products p\n"
        "  WHERE ((p.tenant_id = quality_current_issues.tenant_id) AND (p.category_id = "
        "quality_current_issues.category_id) AND (p.id = "
        "quality_current_issues.product_id)))) AND (EXISTS ( SELECT 1\n"
        "   FROM quality_issue_versions p\n"
        "  WHERE ((p.tenant_id = quality_current_issues.tenant_id) AND (p.product_id = "
        "quality_current_issues.product_id) AND (p.project_id = "
        "quality_current_issues.project_id) AND (p.issue_id = "
        "quality_current_issues.issue_id) AND (p.id = "
        "quality_current_issues.issue_version_id) AND (p.revision = "
        "quality_current_issues.issue_revision)))))",
        "with_check": "(category_access(tenant_id, category_id, true) AND (EXISTS ( SELECT 1\n"
        "   FROM products p\n"
        "  WHERE ((p.tenant_id = quality_current_issues.tenant_id) AND (p.category_id "
        "= quality_current_issues.category_id) AND (p.id = "
        "quality_current_issues.product_id)))) AND (EXISTS ( SELECT 1\n"
        "   FROM quality_issue_versions p\n"
        "  WHERE ((p.tenant_id = quality_current_issues.tenant_id) AND (p.product_id = "
        "quality_current_issues.product_id) AND (p.project_id = "
        "quality_current_issues.project_id) AND (p.issue_id = "
        "quality_current_issues.issue_id) AND (p.id = "
        "quality_current_issues.issue_version_id) AND (p.revision = "
        "quality_current_issues.issue_revision)))))",
    },
    {
        "schemaname": "public",
        "tablename": "quality_current_issues",
        "policyname": "model_audience",
        "permissive": "RESTRICTIVE",
        "roles": ["pdos_agent", "pdos_next_app", "pdos_next_auth", "pdos_next_dispatch"],
        "cmd": "ALL",
        "qual": "(category_access(tenant_id, category_id) AND (EXISTS ( SELECT 1\n"
        "   FROM products p\n"
        "  WHERE ((p.tenant_id = quality_current_issues.tenant_id) AND (p.category_id = "
        "quality_current_issues.category_id) AND (p.id = "
        "quality_current_issues.product_id)))))",
        "with_check": "(category_access(tenant_id, category_id) AND (EXISTS ( SELECT 1\n"
        "   FROM products p\n"
        "  WHERE ((p.tenant_id = quality_current_issues.tenant_id) AND (p.category_id "
        "= quality_current_issues.category_id) AND (p.id = "
        "quality_current_issues.product_id)))))",
    },
    {
        "schemaname": "public",
        "tablename": "quality_current_issues",
        "policyname": "owner_internal",
        "permissive": "PERMISSIVE",
        "roles": ["pdos_next_owner"],
        "cmd": "ALL",
        "qual": "true",
        "with_check": "true",
    },
    {
        "schemaname": "public",
        "tablename": "quality_failure_maps",
        "policyname": "category_scope",
        "permissive": "PERMISSIVE",
        "roles": ["public"],
        "cmd": "ALL",
        "qual": "(category_access(tenant_id, category_id) AND (EXISTS ( SELECT 1\n"
        "   FROM products p\n"
        "  WHERE ((p.tenant_id = quality_failure_maps.tenant_id) AND (p.category_id = "
        "quality_failure_maps.category_id) AND (p.id = quality_failure_maps.product_id)))))",
        "with_check": "(category_access(tenant_id, category_id, true) AND (EXISTS ( SELECT 1\n"
        "   FROM products p\n"
        "  WHERE ((p.tenant_id = quality_failure_maps.tenant_id) AND (p.category_id = "
        "quality_failure_maps.category_id) AND (p.id = "
        "quality_failure_maps.product_id)))))",
    },
    {
        "schemaname": "public",
        "tablename": "quality_failure_maps",
        "policyname": "model_audience",
        "permissive": "RESTRICTIVE",
        "roles": ["pdos_agent", "pdos_next_app", "pdos_next_auth", "pdos_next_dispatch"],
        "cmd": "ALL",
        "qual": "(category_access(tenant_id, category_id) AND (EXISTS ( SELECT 1\n"
        "   FROM products p\n"
        "  WHERE ((p.tenant_id = quality_failure_maps.tenant_id) AND (p.category_id = "
        "quality_failure_maps.category_id) AND (p.id = quality_failure_maps.product_id)))))",
        "with_check": "(category_access(tenant_id, category_id) AND (EXISTS ( SELECT 1\n"
        "   FROM products p\n"
        "  WHERE ((p.tenant_id = quality_failure_maps.tenant_id) AND (p.category_id = "
        "quality_failure_maps.category_id) AND (p.id = "
        "quality_failure_maps.product_id)))))",
    },
    {
        "schemaname": "public",
        "tablename": "quality_failure_maps",
        "policyname": "owner_internal",
        "permissive": "PERMISSIVE",
        "roles": ["pdos_next_owner"],
        "cmd": "ALL",
        "qual": "true",
        "with_check": "true",
    },
    {
        "schemaname": "public",
        "tablename": "sample_current_readiness",
        "policyname": "category_scope",
        "permissive": "PERMISSIVE",
        "roles": ["public"],
        "cmd": "ALL",
        "qual": "(category_access(tenant_id, category_id) AND (EXISTS ( SELECT 1\n"
        "   FROM products p\n"
        "  WHERE ((p.tenant_id = sample_current_readiness.tenant_id) AND (p.category_id = "
        "sample_current_readiness.category_id) AND (p.id = "
        "sample_current_readiness.product_id)))) AND (EXISTS ( SELECT 1\n"
        "   FROM sample_readiness_facts p\n"
        "  WHERE ((p.tenant_id = sample_current_readiness.tenant_id) AND (p.product_id = "
        "sample_current_readiness.product_id) AND (p.project_id = "
        "sample_current_readiness.project_id) AND (p.build_id = "
        "sample_current_readiness.build_id) AND (p.sample_id = "
        "sample_current_readiness.sample_id) AND (p.id = "
        "sample_current_readiness.readiness_id) AND (p.revision = "
        "sample_current_readiness.readiness_revision)))))",
        "with_check": "(category_access(tenant_id, category_id, true) AND (EXISTS ( SELECT 1\n"
        "   FROM products p\n"
        "  WHERE ((p.tenant_id = sample_current_readiness.tenant_id) AND "
        "(p.category_id = sample_current_readiness.category_id) AND (p.id = "
        "sample_current_readiness.product_id)))) AND (EXISTS ( SELECT 1\n"
        "   FROM sample_readiness_facts p\n"
        "  WHERE ((p.tenant_id = sample_current_readiness.tenant_id) AND (p.product_id "
        "= sample_current_readiness.product_id) AND (p.project_id = "
        "sample_current_readiness.project_id) AND (p.build_id = "
        "sample_current_readiness.build_id) AND (p.sample_id = "
        "sample_current_readiness.sample_id) AND (p.id = "
        "sample_current_readiness.readiness_id) AND (p.revision = "
        "sample_current_readiness.readiness_revision)))))",
    },
    {
        "schemaname": "public",
        "tablename": "sample_current_readiness",
        "policyname": "model_audience",
        "permissive": "RESTRICTIVE",
        "roles": ["pdos_agent", "pdos_next_app", "pdos_next_auth", "pdos_next_dispatch"],
        "cmd": "ALL",
        "qual": "(category_access(tenant_id, category_id) AND (EXISTS ( SELECT 1\n"
        "   FROM products p\n"
        "  WHERE ((p.tenant_id = sample_current_readiness.tenant_id) AND (p.category_id = "
        "sample_current_readiness.category_id) AND (p.id = "
        "sample_current_readiness.product_id)))))",
        "with_check": "(category_access(tenant_id, category_id) AND (EXISTS ( SELECT 1\n"
        "   FROM products p\n"
        "  WHERE ((p.tenant_id = sample_current_readiness.tenant_id) AND "
        "(p.category_id = sample_current_readiness.category_id) AND (p.id = "
        "sample_current_readiness.product_id)))))",
    },
    {
        "schemaname": "public",
        "tablename": "sample_current_readiness",
        "policyname": "owner_internal",
        "permissive": "PERMISSIVE",
        "roles": ["pdos_next_owner"],
        "cmd": "ALL",
        "qual": "true",
        "with_check": "true",
    },
    {
        "schemaname": "public",
        "tablename": "test_resource_current",
        "policyname": "category_scope",
        "permissive": "PERMISSIVE",
        "roles": ["public"],
        "cmd": "ALL",
        "qual": "(category_access(tenant_id, category_id) AND (EXISTS ( SELECT 1\n"
        "   FROM test_resource_facts p\n"
        "  WHERE ((p.tenant_id = test_resource_current.tenant_id) AND (p.product_id = "
        "test_resource_current.product_id) AND (p.project_id = "
        "test_resource_current.project_id) AND (p.build_id = test_resource_current.build_id) "
        "AND (p.run_id = test_resource_current.run_id) AND (p.request_id = "
        "test_resource_current.request_id) AND (p.id = test_resource_current.fact_id) AND "
        "(p.revision = test_resource_current.fact_revision)))) AND (EXISTS ( SELECT 1\n"
        "   FROM products p\n"
        "  WHERE ((p.tenant_id = test_resource_current.tenant_id) AND (p.category_id = "
        "test_resource_current.category_id) AND (p.id = "
        "test_resource_current.product_id)))))",
        "with_check": "(category_access(tenant_id, category_id, true) AND (EXISTS ( SELECT 1\n"
        "   FROM test_resource_facts p\n"
        "  WHERE ((p.tenant_id = test_resource_current.tenant_id) AND (p.product_id = "
        "test_resource_current.product_id) AND (p.project_id = "
        "test_resource_current.project_id) AND (p.build_id = "
        "test_resource_current.build_id) AND (p.run_id = test_resource_current.run_id) "
        "AND (p.request_id = test_resource_current.request_id) AND (p.id = "
        "test_resource_current.fact_id) AND (p.revision = "
        "test_resource_current.fact_revision)))) AND (EXISTS ( SELECT 1\n"
        "   FROM products p\n"
        "  WHERE ((p.tenant_id = test_resource_current.tenant_id) AND (p.category_id = "
        "test_resource_current.category_id) AND (p.id = "
        "test_resource_current.product_id)))))",
    },
    {
        "schemaname": "public",
        "tablename": "test_resource_current",
        "policyname": "model_audience",
        "permissive": "RESTRICTIVE",
        "roles": ["pdos_agent", "pdos_next_app", "pdos_next_auth", "pdos_next_dispatch"],
        "cmd": "ALL",
        "qual": "(category_access(tenant_id, category_id) AND (EXISTS ( SELECT 1\n"
        "   FROM products p\n"
        "  WHERE ((p.tenant_id = test_resource_current.tenant_id) AND (p.category_id = "
        "test_resource_current.category_id) AND (p.id = "
        "test_resource_current.product_id)))))",
        "with_check": "(category_access(tenant_id, category_id) AND (EXISTS ( SELECT 1\n"
        "   FROM products p\n"
        "  WHERE ((p.tenant_id = test_resource_current.tenant_id) AND (p.category_id = "
        "test_resource_current.category_id) AND (p.id = "
        "test_resource_current.product_id)))))",
    },
    {
        "schemaname": "public",
        "tablename": "test_resource_current",
        "policyname": "owner_internal",
        "permissive": "PERMISSIVE",
        "roles": ["pdos_next_owner"],
        "cmd": "ALL",
        "qual": "true",
        "with_check": "true",
    },
    {
        "schemaname": "public",
        "tablename": "verification_current_actual_methods",
        "policyname": "category_scope",
        "permissive": "PERMISSIVE",
        "roles": ["public"],
        "cmd": "ALL",
        "qual": "(category_access(tenant_id, category_id) AND (EXISTS ( SELECT 1\n"
        "   FROM products p\n"
        "  WHERE ((p.tenant_id = verification_current_actual_methods.tenant_id) AND "
        "(p.category_id = verification_current_actual_methods.category_id) AND (p.id = "
        "verification_current_actual_methods.product_id)))) AND (EXISTS ( SELECT 1\n"
        "   FROM verification_actual_method_applicabilities p\n"
        "  WHERE ((p.tenant_id = verification_current_actual_methods.tenant_id) AND "
        "(p.product_id = verification_current_actual_methods.product_id) AND (p.request_id = "
        "verification_current_actual_methods.request_id) AND (p.sample_id = "
        "verification_current_actual_methods.sample_id) AND ((p.item_id)::text = "
        "(verification_current_actual_methods.item_id)::text) AND (p.id = "
        "verification_current_actual_methods.assessment_id) AND (p.revision = "
        "verification_current_actual_methods.assessment_revision)))))",
        "with_check": "(category_access(tenant_id, category_id, true) AND (EXISTS ( SELECT 1\n"
        "   FROM products p\n"
        "  WHERE ((p.tenant_id = verification_current_actual_methods.tenant_id) AND "
        "(p.category_id = verification_current_actual_methods.category_id) AND (p.id = "
        "verification_current_actual_methods.product_id)))) AND (EXISTS ( SELECT 1\n"
        "   FROM verification_actual_method_applicabilities p\n"
        "  WHERE ((p.tenant_id = verification_current_actual_methods.tenant_id) AND "
        "(p.product_id = verification_current_actual_methods.product_id) AND "
        "(p.request_id = verification_current_actual_methods.request_id) AND "
        "(p.sample_id = verification_current_actual_methods.sample_id) AND "
        "((p.item_id)::text = (verification_current_actual_methods.item_id)::text) AND "
        "(p.id = verification_current_actual_methods.assessment_id) AND (p.revision = "
        "verification_current_actual_methods.assessment_revision)))))",
    },
    {
        "schemaname": "public",
        "tablename": "verification_current_actual_methods",
        "policyname": "model_audience",
        "permissive": "RESTRICTIVE",
        "roles": ["pdos_agent", "pdos_next_app", "pdos_next_auth", "pdos_next_dispatch"],
        "cmd": "ALL",
        "qual": "(category_access(tenant_id, category_id) AND (EXISTS ( SELECT 1\n"
        "   FROM products p\n"
        "  WHERE ((p.tenant_id = verification_current_actual_methods.tenant_id) AND "
        "(p.category_id = verification_current_actual_methods.category_id) AND (p.id = "
        "verification_current_actual_methods.product_id)))))",
        "with_check": "(category_access(tenant_id, category_id) AND (EXISTS ( SELECT 1\n"
        "   FROM products p\n"
        "  WHERE ((p.tenant_id = verification_current_actual_methods.tenant_id) AND "
        "(p.category_id = verification_current_actual_methods.category_id) AND (p.id = "
        "verification_current_actual_methods.product_id)))))",
    },
    {
        "schemaname": "public",
        "tablename": "verification_current_actual_methods",
        "policyname": "owner_internal",
        "permissive": "PERMISSIVE",
        "roles": ["pdos_next_owner"],
        "cmd": "ALL",
        "qual": "true",
        "with_check": "true",
    },
    {
        "schemaname": "public",
        "tablename": "verification_current_formal_requests",
        "policyname": "category_scope",
        "permissive": "PERMISSIVE",
        "roles": ["public"],
        "cmd": "ALL",
        "qual": "(category_access(tenant_id, category_id) AND (EXISTS ( SELECT 1\n"
        "   FROM products p\n"
        "  WHERE ((p.tenant_id = verification_current_formal_requests.tenant_id) AND "
        "(p.category_id = verification_current_formal_requests.category_id) AND (p.id = "
        "verification_current_formal_requests.product_id)))) AND (EXISTS ( SELECT 1\n"
        "   FROM verification_formal_requests p\n"
        "  WHERE ((p.tenant_id = verification_current_formal_requests.tenant_id) AND "
        "(p.product_id = verification_current_formal_requests.product_id) AND (p.request_id "
        "= verification_current_formal_requests.request_id) AND (p.id = "
        "verification_current_formal_requests.request_version_id) AND (p.revision = "
        "verification_current_formal_requests.request_revision)))))",
        "with_check": "(category_access(tenant_id, category_id, true) AND (EXISTS ( SELECT 1\n"
        "   FROM products p\n"
        "  WHERE ((p.tenant_id = verification_current_formal_requests.tenant_id) AND "
        "(p.category_id = verification_current_formal_requests.category_id) AND (p.id "
        "= verification_current_formal_requests.product_id)))) AND (EXISTS ( SELECT 1\n"
        "   FROM verification_formal_requests p\n"
        "  WHERE ((p.tenant_id = verification_current_formal_requests.tenant_id) AND "
        "(p.product_id = verification_current_formal_requests.product_id) AND "
        "(p.request_id = verification_current_formal_requests.request_id) AND (p.id = "
        "verification_current_formal_requests.request_version_id) AND (p.revision = "
        "verification_current_formal_requests.request_revision)))))",
    },
    {
        "schemaname": "public",
        "tablename": "verification_current_formal_requests",
        "policyname": "model_audience",
        "permissive": "RESTRICTIVE",
        "roles": ["pdos_agent", "pdos_next_app", "pdos_next_auth", "pdos_next_dispatch"],
        "cmd": "ALL",
        "qual": "(category_access(tenant_id, category_id) AND (EXISTS ( SELECT 1\n"
        "   FROM products p\n"
        "  WHERE ((p.tenant_id = verification_current_formal_requests.tenant_id) AND "
        "(p.category_id = verification_current_formal_requests.category_id) AND (p.id = "
        "verification_current_formal_requests.product_id)))))",
        "with_check": "(category_access(tenant_id, category_id) AND (EXISTS ( SELECT 1\n"
        "   FROM products p\n"
        "  WHERE ((p.tenant_id = verification_current_formal_requests.tenant_id) AND "
        "(p.category_id = verification_current_formal_requests.category_id) AND (p.id "
        "= verification_current_formal_requests.product_id)))))",
    },
    {
        "schemaname": "public",
        "tablename": "verification_current_formal_requests",
        "policyname": "owner_internal",
        "permissive": "PERMISSIVE",
        "roles": ["pdos_next_owner"],
        "cmd": "ALL",
        "qual": "true",
        "with_check": "true",
    },
]
EXPECTED_RELATIONS = [
    {
        "relname": "build_current_authorizations",
        "relkind": "r",
        "owner": "pdos_next_owner",
        "relrowsecurity": True,
        "relforcerowsecurity": True,
        "acl": ["pdos_next_app=arw/pdos_next_owner", "pdos_next_owner=arwdDxt/pdos_next_owner"],
    },
    {
        "relname": "build_operational_current",
        "relkind": "r",
        "owner": "pdos_next_owner",
        "relrowsecurity": True,
        "relforcerowsecurity": True,
        "acl": ["pdos_next_app=arw/pdos_next_owner", "pdos_next_owner=arwdDxt/pdos_next_owner"],
    },
    {
        "relname": "quality_current_issues",
        "relkind": "r",
        "owner": "pdos_next_owner",
        "relrowsecurity": True,
        "relforcerowsecurity": True,
        "acl": ["pdos_next_app=arw/pdos_next_owner", "pdos_next_owner=arwdDxt/pdos_next_owner"],
    },
    {
        "relname": "quality_failure_maps",
        "relkind": "r",
        "owner": "pdos_next_owner",
        "relrowsecurity": True,
        "relforcerowsecurity": True,
        "acl": ["pdos_next_app=arw/pdos_next_owner", "pdos_next_owner=arwdDxt/pdos_next_owner"],
    },
    {
        "relname": "sample_current_readiness",
        "relkind": "r",
        "owner": "pdos_next_owner",
        "relrowsecurity": True,
        "relforcerowsecurity": True,
        "acl": ["pdos_next_app=arw/pdos_next_owner", "pdos_next_owner=arwdDxt/pdos_next_owner"],
    },
    {
        "relname": "test_resource_current",
        "relkind": "r",
        "owner": "pdos_next_owner",
        "relrowsecurity": True,
        "relforcerowsecurity": True,
        "acl": ["pdos_next_app=arw/pdos_next_owner", "pdos_next_owner=arwdDxt/pdos_next_owner"],
    },
    {
        "relname": "verification_current_actual_methods",
        "relkind": "r",
        "owner": "pdos_next_owner",
        "relrowsecurity": True,
        "relforcerowsecurity": True,
        "acl": ["pdos_next_app=arw/pdos_next_owner", "pdos_next_owner=arwdDxt/pdos_next_owner"],
    },
    {
        "relname": "verification_current_formal_requests",
        "relkind": "r",
        "owner": "pdos_next_owner",
        "relrowsecurity": True,
        "relforcerowsecurity": True,
        "acl": ["pdos_next_app=arw/pdos_next_owner", "pdos_next_owner=arwdDxt/pdos_next_owner"],
    },
]
EXPECTED_ROLES = [
    {
        "rolname": "pdos_agent",
        "rolsuper": False,
        "rolbypassrls": False,
        "rolcreaterole": False,
        "rolcreatedb": False,
        "owner_member": False,
    },
    {
        "rolname": "pdos_next_app",
        "rolsuper": False,
        "rolbypassrls": False,
        "rolcreaterole": False,
        "rolcreatedb": False,
        "owner_member": False,
    },
    {
        "rolname": "pdos_next_auth",
        "rolsuper": False,
        "rolbypassrls": False,
        "rolcreaterole": False,
        "rolcreatedb": False,
        "owner_member": False,
    },
    {
        "rolname": "pdos_next_dispatch",
        "rolsuper": False,
        "rolbypassrls": False,
        "rolcreaterole": False,
        "rolcreatedb": False,
        "owner_member": False,
    },
    {
        "rolname": "pdos_next_owner",
        "rolsuper": False,
        "rolbypassrls": False,
        "rolcreaterole": False,
        "rolcreatedb": False,
        "owner_member": True,
    },
]
WRITE_POLICIES = (
    ("model_audience_insert", "INSERT"),
    ("model_audience_update", "UPDATE"),
    ("model_audience_delete", "DELETE"),
)


def _canonical(row):
    value = dict(row)
    value["roles"] = tuple(sorted(value["roles"]))
    for key in ("qual", "with_check"):
        if value[key] is not None:
            value[key] = " ".join(value[key].split())
    return value


def _model_policies():
    return {
        row["tablename"]: row for row in EXPECTED_POLICIES if row["policyname"] == "model_audience"
    }


def _policies_after():
    result = [row for row in EXPECTED_POLICIES if row["policyname"] != "model_audience"]
    for original in _model_policies().values():
        for name, command in WRITE_POLICIES:
            result.append(
                {
                    **original,
                    "policyname": name,
                    "cmd": command,
                    "qual": None if command == "INSERT" else original["qual"],
                    "with_check": None if command == "DELETE" else original["with_check"],
                }
            )
    return sorted(result, key=lambda row: (row["tablename"], row["policyname"]))


def _require_reviewed_scope(connection, expected):
    names = ",".join(f"'{table}'" for table in TABLES)
    policies = (
        connection.execute(
            text(
                "SELECT schemaname,tablename,policyname,permissive,roles,cmd,qual,with_check "
                "FROM pg_policies WHERE schemaname='public' AND tablename IN (" + names + ") "
                "ORDER BY tablename,policyname"
            )
        )
        .mappings()
        .all()
    )
    if [_canonical(row) for row in policies] != [_canonical(row) for row in expected]:
        raise RuntimeError("Unreviewed Current/map policy drift")
    roles = (
        connection.execute(
            text(
                "SELECT rolname,rolsuper,rolbypassrls,rolcreaterole,rolcreatedb,"
                "pg_has_role(rolname,'pdos_next_owner','MEMBER') AS owner_member "
                "FROM pg_roles WHERE rolname IN "
                "('pdos_agent','pdos_next_app','pdos_next_auth',"
                "'pdos_next_dispatch','pdos_next_owner') "
                "ORDER BY rolname"
            )
        )
        .mappings()
        .all()
    )
    if [dict(row) for row in roles] != EXPECTED_ROLES:
        raise RuntimeError("Ordinary owner and isolated runtime roles must remain unchanged")
    relations = (
        connection.execute(
            text(
                "SELECT relname,relkind,pg_get_userbyid(relowner) AS owner,"
                "relrowsecurity,relforcerowsecurity,"
                "ARRAY(SELECT unnest(relacl)::text ORDER BY 1) AS acl "
                "FROM pg_class WHERE relnamespace='public'::regnamespace AND relname IN ("
                + names
                + ") ORDER BY relname"
            )
        )
        .mappings()
        .all()
    )
    if [dict(row) for row in relations] != EXPECTED_RELATIONS:
        raise RuntimeError("Current/map owner, forced RLS and table ACL must remain unchanged")


def _lock_tables(connection):
    connection.execute(
        text(
            "LOCK TABLE "
            + ",".join(f'public."{table}"' for table in TABLES)
            + " IN ACCESS EXCLUSIVE MODE"
        )
    )


def _create_policy(table, name, command, original):
    roles = ",".join(f'"{role}"' for role in original["roles"])
    ddl = f'CREATE POLICY "{name}" ON public."{table}" AS RESTRICTIVE FOR {command} TO {roles}'
    if command != "INSERT":
        ddl += " USING " + original["qual"]
    if command != "DELETE":
        ddl += " WITH CHECK " + original["with_check"]
    op.execute(ddl)


def upgrade():
    connection = op.get_bind()
    _lock_tables(connection)
    _require_reviewed_scope(connection, EXPECTED_POLICIES)
    for table, original in _model_policies().items():
        op.execute(f'DROP POLICY model_audience ON public."{table}"')
        for name, command in WRITE_POLICIES:
            _create_policy(table, name, command, original)


def downgrade():
    connection = op.get_bind()
    _lock_tables(connection)
    _require_reviewed_scope(connection, _policies_after())
    for table, original in _model_policies().items():
        for name, _ in WRITE_POLICIES:
            op.execute(f'DROP POLICY "{name}" ON public."{table}"')
        _create_policy(table, "model_audience", "ALL", original)
