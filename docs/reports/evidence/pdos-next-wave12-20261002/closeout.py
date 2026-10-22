"""Finalize only this verified local candidate after its complete checks pass."""
import hashlib,json,subprocess,sys
from datetime import UTC,datetime
from pathlib import Path
REPORT=Path(__file__).resolve().parent; ROOT=REPORT.parents[3]
sys.path.insert(0,str(ROOT/'pdos-next/tools'))
from local_environment import environment,read_state,verified
load=lambda name:json.loads((REPORT/name).read_text())
def save(name,data): (REPORT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
joint=load('joint-resolved-result.json'); assert joint['result']=='passed_after_test_only_repair'
initial=load('joint-result.json'); assert [k for k,v in initial['groups'].items() if v['exit_code']!=0]==['verification_handoff-3']
candidate=load('candidate.json'); assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==sha for p,sha in candidate.items())
backend=load('candidate-backend-joint.json'); repair=load('test-only-repair.json')
assert repair['exit_code']==0 and repair['runtime_source_changed'] is False
assert repair['path'].startswith('pdos-next/server/tests/')
changed=[p for p,sha in candidate.items() if '/server/' in p and backend[p]!=sha]
assert changed==[repair['path']]
assert backend[repair['path']]==repair['before_sha256'] and candidate[repair['path']]==repair['after_sha256']
assert '1 passed' in (REPORT/repair['log']).read_text()
assert load('lifecycle-isolated-recheck.json')['exit_code']==0
assert load('browser-layouts.json')['no_horizontal_overflow'] is True
actual=load('actual-preview.json'); assert actual['formal_versions']==5 and actual['accepted_pairs']==1
state=verified(read_state())
with (REPORT/'schema-match.log').open('x') as log:
 subprocess.run([sys.executable,'-m','alembic','check'],cwd=ROOT/'pdos-next/server',env=environment(state),stdout=log,stderr=subprocess.STDOUT,check=True)
backup=ROOT/'pdos-next/.local/wave12-business.dump'
state=verified(read_state())
with backup.open('xb') as output:
 backup.chmod(0o600);subprocess.run(['docker','exec',state['container'],'pg_dump','-U','postgres','-d','pdos_test','-Fc'],stdout=output,stderr=subprocess.PIPE,check=True)
with backup.open('rb') as source:
 catalog=subprocess.run(['docker','exec','-i',state['container'],'pg_restore','--list'],stdin=source,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True).stdout.decode()
assert all(name in catalog for name in ('sample_readiness_facts','verification_actual_method_batches','verification_handoff_facts'))
save('backup.json',{'verified_marker':state['marker'],'verified_port':state['port'],'before_migration':'pdos-next/.local/pre-wave12-next_0014.dump','after_business':str(backup.relative_to(ROOT)),'mode':oct(backup.stat().st_mode&0o777),'sha256':hashlib.sha256(backup.read_bytes()).hexdigest(),'bytes':backup.stat().st_size,'catalog_checked':True,'restore_performed':False,'migration_roundtrip_before_business':'next_0014 → next_0015 → next_0014 → next_0015'})
save('final-check.json',{'recorded_at':datetime.now(UTC).isoformat(),'result':'passed_with_recorded_scope','candidate_files':len(candidate),'candidate_sha256':hashlib.sha256((REPORT/'candidate.json').read_bytes()).hexdigest(),'source_hashes_stable_at_closeout':True,'runtime_unchanged_during_joint':True,'test_only_repair':'test-only-repair.json','initial_joint_result':'joint-initial-result.json','validation_mode':'initial joint plus test-only affected-node recheck and isolated structural recheck','joint_passed':joint['total_passed'],'initial_joint_seconds':joint['elapsed_seconds'],'parallel_process_limit':6,'structural_tests_isolated':joint['structural_tests_isolated'],'frontend_verification':'ui-helpers-final.log','final_production_build':'web-build-final.log','schema_check':'passed','python_lint':'passed','frontend_lint_errors':0,'frontend_existing_warnings':2,'browser_layouts':4,'browser_actions':'browser-actions.json','schema_head':actual['schema_head'],'business_tables':actual['business_tables'],'agent_direct_writes':actual['agent_direct_writes'],'model_calls':actual['model_calls'],'business_readback':'actual-preview.json','reuse':'reuse-review.json','contracts':'source-contract-check.json','backup':'backup.json','nature':'synthetic','real_factory_qualification':False,'formal_exit':False})
print(json.dumps({'passed':joint['total_passed'],'seconds':joint['elapsed_seconds'],'schema':'next_0015','candidate_files':len(candidate),'backup_catalog_checked':True}))
