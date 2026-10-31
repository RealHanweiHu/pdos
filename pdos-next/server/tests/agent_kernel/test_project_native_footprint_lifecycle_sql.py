"""Exact predecessor bodies and actual composite-column checks, without a DB."""

import ast
import re
from pathlib import Path

from migrations.candidates import project_native_footprint_lifecycle as candidate
from migrations.schema_s0_0761 import GATE
from pdos_next.agent_kernel.models import AgentRun
from pdos_next.models import Artifact, LifecycleObject


def test_native_candidate_pins_exact_existing_kernel_bodies_and_restore_is_replacing():
    path = Path(__file__).parents[2] / "migrations" / "versions"
    path = path / "s0_0718_kernel_sources_and_dispatch.py"
    tree = ast.parse(path.read_text())
    sql = next(ast.literal_eval(node.value) for node in tree.body
               if isinstance(node, ast.Assign)
               and any(isinstance(name, ast.Name) and name.id == "SQL" for name in node.targets))
    for signature, body in candidate.PREVIOUS_PROSRC.items():
        if signature == "kernel_source_reference_gate()":
            assert body == GATE.split("$function$")[1]
        else:
            name = signature.split("(")[0]
            actual = re.search(r"CREATE FUNCTION " + name + r"\(.*?END \$\$;", sql, re.S)
            assert actual and actual.group(0).split("$$")[1] == body
    assert all(sql.startswith("CREATE OR REPLACE FUNCTION public.")
               for sql in candidate.RESTORE_SQL)


def test_native_gate_composite_fields_exist_and_runtime_privileges_do_not_change():
    gate = candidate.NATIVE_FUNCTIONS["kernel_source_reference_gate()"]
    for alias, model in (("r", AgentRun), ("prior", AgentRun), ("a", Artifact),
                         ("o", LifecycleObject)):
        fields = set(re.findall(r"\b" + alias + r"\.([a-z_]+)", gate))
        assert fields and fields <= set(model.__table__.columns.keys())
    all_sql = "\n".join(candidate.SCHEMA_SQL)
    assert not re.search(r"\b(?:GRANT|CREATE ROLE|ALTER ROLE|ALTER OWNER|DISABLE|NO FORCE)\b",
                         all_sql, re.I)
    assert set(candidate.NATIVE_FUNCTIONS) == {
        "kernel_lifecycle_links(text,jsonb)", "kernel_source_reference_gate()",
        "kernel_source_reference_clock()",
    }
    assert "project_current_context,source_proof" in all_sql
    assert "prior.versions->'project_current_context'" in gate
    assert "kernel_read_set_visible(r.tenant_id,r.category_id,reads)" in gate
    assert "NOT EXISTS(SELECT 1 FROM jsonb_array_elements(r.read_sources)" in (
        candidate.DOWN_HISTORY_GUARD
    )
