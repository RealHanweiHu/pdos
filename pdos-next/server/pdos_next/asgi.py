import json
import os

from pdos_next.api import create_app
from pdos_next.original_store import OriginalStore
from pdos_next.security_bootstrap import local_runtime

root = os.environ.get("PDOS_OBJECT_ROOT")
store = OriginalStore(root) if root else None
app = create_app(
    object_store=store,
    workflow_enabled=os.environ.get("PDOS_WORKFLOWS_ENABLED", "1") == "1",
    security_runtime_factory=lambda: local_runtime(store),
    lifecycle_enabled=True,
    professional_synthetic_profiles=json.loads(
        os.environ.get("PDOS_PROFESSIONAL_SYNTHETIC_PROFILES", "null")
    ),
    operational_synthetic_profiles=json.loads(
        os.environ.get("PDOS_OPERATIONAL_SYNTHETIC_PROFILES", "null")
    ),
    test_resource_synthetic_profiles=json.loads(
        os.environ.get("PDOS_TEST_RESOURCE_SYNTHETIC_PROFILES", "null")
    ),
    quality_synthetic_profiles=json.loads(
        os.environ.get("PDOS_QUALITY_SYNTHETIC_PROFILES", "null")
    ),
    quality_followup_synthetic_profiles=json.loads(
        os.environ.get("PDOS_QUALITY_FOLLOWUP_SYNTHETIC_PROFILES", "null")
    ),
    capa_facts_synthetic_profiles=json.loads(
        os.environ.get("PDOS_CAPA_FACTS_SYNTHETIC_PROFILES", "null")
    ),
    operational_synthetic_profile=json.loads(
        os.environ.get("PDOS_OPERATIONAL_SYNTHETIC_PROFILE", "null")
    ),
    professional_synthetic_scope=json.loads(
        os.environ.get("PDOS_PROFESSIONAL_SYNTHETIC_SCOPE", "null")
    ),
    quality_synthetic_profile=json.loads(os.environ.get("PDOS_QUALITY_SYNTHETIC_PROFILE", "null")),
    quality_followup_synthetic_profile=json.loads(
        os.environ.get("PDOS_QUALITY_FOLLOWUP_SYNTHETIC_PROFILE", "null")
    ),
    capa_facts_synthetic_profile=json.loads(
        os.environ.get("PDOS_CAPA_FACTS_SYNTHETIC_PROFILE", "null")
    ),
    test_resource_synthetic_profile=json.loads(
        os.environ.get("PDOS_TEST_RESOURCE_SYNTHETIC_PROFILE", "null")
    ),
)
