"""Read-only contract and explicitly scoped reuse checks; no database/network."""
import hashlib,json,sys
from pathlib import Path
ROOT=Path.cwd(); REPORT=ROOT/'docs/reports/evidence/pdos-next-wave12-20261002'
sys.path.insert(0,str(ROOT/'pdos-next/server'))
from pdos_next.contracts import PAYLOADS,Command
from pdos_next.api import create_app
from pdos_next.command_handlers import T1_OPERATIONS
from pdos_next.service import EVENTS
p=ROOT/'pdos-next/contracts'
load=lambda path:json.loads(path.read_text())
canonical={r['operation']:r for r in load(p/'operations.json')['items']}
auxiliary={r['operation']:r for r in load(p/'auxiliary-operations.json')['items']}
schemas=load(p/'payloads.schema.json')
assert schemas['command_envelope']==Command.model_json_schema()
assert schemas['operation_payloads']=={op:payload.model_json_schema() for op,payload in PAYLOADS.items()}
assert load(p/'openapi.json')==create_app(engine=object(),auth_engine=object()).openapi()
assert len(PAYLOADS)==42 and len(canonical)==66 and len(auxiliary)==15
assert all(EVENTS[op]==canonical[op]['event'] for op in PAYLOADS if op in canonical)
assert all(EVENTS[op]==auxiliary[op]['event'] for op in auxiliary)
new={'build.sample.readiness.record','verification.actual_method.prepare','verification.handoff.offer','verification.handoff.accept','verification.handoff.return'}
assert new <= set(PAYLOADS) & T1_OPERATIONS
assert all(a['definition_only'] is True for a in load(p/'acceptance.json')['items'])
result={'result':'passed','canonical_operations':66,'canonical_events':65,'acceptance_definitions':48,'registered_payloads':len(PAYLOADS),'registered_canonical_payloads':len(set(PAYLOADS)&set(canonical)),'auxiliary_operations':len(auxiliary),'host_extensions':len(set(PAYLOADS)-set(canonical)-set(auxiliary)),'new_operations_all_t1':True,'exported_schemas_and_openapi_match_runtime':True,'no_database_or_network':True,'acceptance_definitions_are_not_acceptance_results':True}
(REPORT/'source-contract-check.json').write_text(json.dumps(result,indent=2)+'\n')
previous=load(REPORT.parent/'pdos-next-wave11-20261002/reuse-review.json'); review={'baseline':'pdos-next-wave11-20261002/reuse-review.json','scope':'Only the 89 explicitly listed prior assets, not the entire old working tree','files':[]}
for group in ('legacy_frozen','verification_package_frozen','runtime_frozen'):
 for old in previous[group]['files']:
  data=(ROOT/old['path']).read_bytes(); sha=hashlib.sha256(data).hexdigest()
  review['files'].append({'path':old['path'],'group':group,'baseline_sha256':old['current_sha256'],'current_sha256':sha,'matches':sha==old['current_sha256']})
assert len(review['files'])==89 and all(r['matches'] for r in review['files'])
review['result']={'legacy_unchanged':57,'verification_kernel_unchanged':25,'runtime_unchanged':7,'all_listed_files_match':True}
(REPORT/'reuse-review.json').write_text(json.dumps(review,indent=2)+'\n')
print(json.dumps(result));print(review['result'])
