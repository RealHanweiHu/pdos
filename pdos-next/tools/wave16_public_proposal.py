"""Prepare an unapplied, hash-bound public wiring patch without touching Wave15."""

import ast
import difflib
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "pdos-next/server"
REPORT = ROOT / "docs/reports/evidence/pdos-next-wave16-20261002"
sys.path.insert(0, str(SERVER))
from pdos_next.domain.capa_verification.models import (  # noqa: E402
    CapaVerificationEvidence,
    RemediationLinkRecord,
)

changes = {}


def alter(path, old, new):
    source = changes.get(path, (ROOT / path).read_text())
    assert source.count(old) == 1, (path, old)
    changes[path] = source.replace(old, new, 1)


prefix = "pdos-next/server/pdos_next/"
alter(prefix + "command_handlers.py", '        "test.disposition.decide",\n    }\n)',
      '        "test.disposition.decide",\n        "quality.issue.root_cause.decide",\n    }\n)')
alter(prefix + "command_handlers.py", '        "quality.issue.containment.record",\n    }',
      '        "quality.issue.containment.record",\n        "quality.capa.actions.complete",\n'
      '        "quality.capa.followup.link",\n    }')
alter(prefix + "command_handlers.py", "def handler(operation):\n", "def handler(operation):\n"
      '    if operation in {"quality.issue.root_cause.decide", "quality.capa.actions.complete"}:\n'
      "        from pdos_next.domain.quality_followup import service\n\n        return service\n"
      '    if operation == "quality.capa.followup.link":\n'
      "        from pdos_next.domain.capa_verification import commands\n\n        return commands\n")
contracts = prefix + "contracts.py"
changes[contracts] = (ROOT / contracts).read_text() + '''

from pdos_next.domain.quality_followup.schemas import (  # noqa: E402
    ActionsCompletePayload,
    RootCausePayload,
)
from pdos_next.domain.capa_verification.schemas import FollowupLinkPayload  # noqa: E402

PAYLOADS.update(
    {
        "quality.issue.root_cause.decide": RootCausePayload,
        "quality.capa.actions.complete": ActionsCompletePayload,
        "quality.capa.followup.link": FollowupLinkPayload,
    }
)
'''
alter(prefix + "service.py", '    "quality.capa.draft": "capa.drafted",',
      '    "quality.capa.draft": "capa.drafted",\n'
      '    "quality.issue.root_cause.decide": "issue.root_cause_decided",\n'
      '    "quality.capa.actions.complete": "capa.actions_completed",\n'
      '    "quality.capa.followup.link": "capa.followup_linked",')
alter(prefix + "service.py", "    confirmation.consumed = True\n", "    confirmation.consumed = True\n"
      '    if command.operation in {\n        "quality.issue.root_cause.decide",\n'
      '        "quality.capa.actions.complete",\n        "quality.capa.followup.link",\n    }:\n'
      "        from pdos_next.quality_followup_host import record_consumed_confirmation\n\n"
      "        record_consumed_confirmation(s, ctx, command, payload, module, confirmation)\n")
alter(prefix + "domain/professional_authority/service.py", '    "quality.capa.draft": frozenset({"quality", "engineering", "test"}),',
      '    "quality.capa.draft": frozenset({"quality", "engineering", "test"}),\n'
      '    "quality.issue.root_cause.decide": frozenset({"quality"}),\n'
      '    "quality.capa.actions.complete": frozenset({"quality", "engineering", "test"}),\n'
      '    "quality.capa.followup.link": frozenset({"quality", "engineering", "test"}),')
alter(prefix + "api.py", "    quality_synthetic_profile=None,\n", "    quality_synthetic_profile=None,\n"
      "    quality_followup_synthetic_profile=None,\n")
alter(prefix + "api.py", "    @asynccontextmanager\n    async def lifespan", 
      "    from pdos_next.quality_followup_integration import configure_integration\n\n"
      "    configure_integration(\n        engine, synthetic_completion_profile=quality_followup_synthetic_profile\n    )\n\n"
      "    @asynccontextmanager\n    async def lifespan")
alter(prefix + "api.py", "    register_change_routes(app, engine, auth_dependency)\n",
      "    register_change_routes(app, engine, auth_dependency)\n"
      "    from pdos_next.quality_followup_api import register_routes as register_followup_routes\n\n"
      "    register_followup_routes(app, engine, auth_dependency)\n")
alter(prefix + "asgi.py", '    quality_synthetic_profile=json.loads(os.environ.get("PDOS_QUALITY_SYNTHETIC_PROFILE", "null")),',
      '    quality_synthetic_profile=json.loads(os.environ.get("PDOS_QUALITY_SYNTHETIC_PROFILE", "null")),\n'
      '    quality_followup_synthetic_profile=json.loads(\n'
      '        os.environ.get("PDOS_QUALITY_FOLLOWUP_SYNTHETIC_PROFILE", "null")\n    ),')
models = prefix + "models.py"
changes[models] = (ROOT / models).read_text() + '''

from pdos_next.domain.capa_verification.models import (  # noqa: E402,F401
    CapaVerificationEvidence,
    RemediationLinkRecord,
)
'''
quality_models = prefix + "domain/quality_execution/models.py"
alter(quality_models, "status IN ('open','triaged','actioning')", "status IN ('open','triaged','actioning','awaiting_verification')")
alter(quality_models, "            \"'quality.issue.containment.record','quality.capa.draft')\"",
      "            \"'quality.issue.containment.record','quality.capa.draft',\"\n"
      "            \"'quality.issue.root_cause.decide','quality.capa.actions.complete')\"")
catalog = prefix + "lifecycle_catalog.py"
catalog_source = (ROOT / catalog).read_text()
tree = ast.parse(catalog_source)
for assignment in tree.body:
    if isinstance(assignment, ast.Assign) and isinstance(assignment.targets[0], ast.Name):
        name = assignment.targets[0].id
        if name not in {"COVERED_COLUMNS", "GUARDED"}:
            continue
        value = ast.literal_eval(assignment.value)
        if name == "COVERED_COLUMNS":
            for model in (RemediationLinkRecord, CapaVerificationEvidence):
                assert model.__tablename__ not in value
                value[model.__tablename__] = tuple(model.__table__.columns.keys())
        else:
            value = tuple(sorted((*value, RemediationLinkRecord.__tablename__, CapaVerificationEvidence.__tablename__)))
        old = ast.get_source_segment(catalog_source, assignment)
        alter(catalog, old, name + " = " + repr(value))
alter("pdos-next/tools/local_environment.py", '            env["PDOS_QUALITY_SYNTHETIC_PROFILE"] = quality_profile.read_text()',
      '            env["PDOS_QUALITY_SYNTHETIC_PROFILE"] = quality_profile.read_text()\n'
      '        followup_profile = ROOT / ".local/quality-followup-synthetic-profile.json"\n'
      '        if followup_profile.exists():\n'
      '            env["PDOS_QUALITY_FOLLOWUP_SYNTHETIC_PROFILE"] = followup_profile.read_text()')

patch, files = [], []
for path, proposed in changes.items():
    original = (ROOT / path).read_text()
    compile(proposed, path, "exec")
    patch.extend(difflib.unified_diff(original.splitlines(True), proposed.splitlines(True),
                                    fromfile="a/" + path, tofile="b/" + path))
    files.append({"path": path, "base_sha256": hashlib.sha256(original.encode()).hexdigest(),
                  "proposed_sha256": hashlib.sha256(proposed.encode()).hexdigest()})
patch_text = "".join(patch)
with (REPORT / "root-public-integration-proposal.patch").open("x") as output:
    output.write(patch_text)
with (REPORT / "root-public-integration-proposal.json").open("x") as output:
    json.dump({"applied": False, "files": files, "syntax_checked": True,
               "patch_sha256": hashlib.sha256(patch_text.encode()).hexdigest(),
               "scope": "Unapplied public wiring only; migration and actual validation remain Root-owned."}, output, indent=2)
print(json.dumps({"files": len(files), "applied": False, "syntax_checked": True}))
