"""Compare immutable history and actual handoff on the verified synthetic instance."""
import json
import sys
from pathlib import Path
from uuid import UUID

import httpx
from sqlalchemy import func, select, text

ROOT = Path(__file__).resolve().parents[4]
REPORT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'pdos-next/tools'))
from local_environment import read_state, verified
from pdos_next.database import engine_for, tenant_session
from pdos_next.models import Audit, Outbox, Receipt

state = verified(read_state())
seed = json.loads((ROOT / 'pdos-next/.local/wave12-seed.json').read_text())
assert seed['phase'] == 'returned'
prior = json.loads((REPORT / 'prior-business.json').read_text())
with httpx.Client(base_url='http://127.0.0.1:8898', trust_env=False, timeout=180,
                 headers={'Authorization': 'Bearer ' + state['preview_token']}) as client:
    def read(path):
        response = client.get(f"/v1/products/{state['preview_product_id']}/{path}")
        response.raise_for_status()
        return response.json()
    builds, execution, preparation = read('builds'), read('build-execution'), read('verification')
    professional, handoff = read('verification-professional'), read('verification-handoff')
    readiness = read(f"sample-handoff?build_id={seed['build_id']}")
    start = read('build-start')
    assert read('model-calls')['items'] == []
    for old in prior['builds']['items']:
        new = next(row for row in builds['items'] if row['id'] == old['id'])
        for key in ('id','revision','status','project_id','engineering_configuration','manufacturing_configuration','planned_quantity','purpose','created_at'):
            assert new[key] == old[key], key
    for key in ('samples','lots','actual_configurations','allocations'):
        for old in prior['build-execution'][key]:
            new = next(row for row in execution[key] if row['id'] == old['id'])
            assert new == old, (key,old['id'])
    for expired in seed.get('expired_rounds', []):
        for old in expired['samples']:
            new = next(row for row in execution['samples'] if row['id'] == old['id'])
            assert new == old, ('expired_sample_history', old['id'])
        old_request = next(row for row in professional['requests'] if row['id'] == expired['current_version_id'])
        assert old_request['revision'] == expired['revision']
        assert old_request['request_id'] == expired['request_id']
    for old in prior['verification']['preparations']:
        new = next(row for row in preparation['preparations'] if row['id'] == old['id'])
        for key in ('id','revision','sha256','input_snapshot','request_snapshot'):
            assert new[key] == old[key], key
    for old in prior['verification-professional']['requests']:
        new = next(row for row in professional['requests'] if row['id'] == old['id'])
        for key in ('id','revision','sha256','request_snapshot','preparation_sha256','first_requested_at'):
            assert new[key] == old[key], key
    active_id = handoff['current_by_request'][seed['request_id']]['request_version_id']
    current = next(row for row in handoff['requests'] if row['id'] == active_id)
    versions = sorted([r for r in handoff['requests'] if r['request_id'] == seed['request_id']],key=lambda r:r['revision'])
    assert [r['revision'] for r in versions] == [1,2,3,4,5]
    assert [r['status'] for r in versions] == ['draft','draft','offered','accepted','accepted']
    assert all(r['zero_occupancy'] for r in versions)
    assert len(current['accepted_coverage']) == 1 and len(current['returns']) == 2
    accepted_id = current['accepted_coverage'][0]['sample_id']
    assert next(s for s in seed['samples'] if s['id']==accepted_id)['label'].endswith('A')
    assert len(current['offered_coverage']) == 2 and current['coverage_gaps']
    assert all(current['timeline'][key] is None for key in ('promised_start','actual_start','preliminary_result','final_result','disposed'))
    assert not handoff['runs'] and not preparation['runs']
    assert {v['availability'] for v in readiness['availability_by_sample'].values()} == {'ready','hold'}
    sample_ids = {s['id'] for s in seed['samples']}
    actual_samples = [s for s in execution['samples'] if s['id'] in sample_ids]
    assert all(s['availability']=='unknown' and s['revision']==1 for s in actual_samples)
    methods = [r for r in handoff['actual_methods'] if r['request_id']==seed['request_id']]
    assert {r['status'] for r in methods} == {'applicable','unknown'}
    caps = start['capabilities_by_build'][seed['build_id']]
    assert caps['execution_qualification']=='limited_current' and caps['stop_required'] is False
    oldcap = start['capabilities_by_build'][seed['interrupted_round']['build_id']]
    assert oldcap['stop_required'] and oldcap['execution_qualification']=='needs_recheck'
    for expired in seed.get('expired_rounds', []):
        assert start['capabilities_by_build'][expired['build_id']]['stop_required']
    for old in prior['build-start']['starts']:
        new=next(row for row in start['starts'] if row['id']==old['id'])
        for key in ('id','snapshot_sha256','occurred_at','execution_scope','authority_snapshot','reservations'):
            assert old[key] == new[key], key

receipt_ids = [UUID(r['id']) for r in seed['readiness_receipts']+seed['handoff_receipts']]
assert len(receipt_ids)==6
with tenant_session(engine_for(state['app_url']), UUID(state['preview_tenant_id'])) as session:
    assert len(session.scalars(select(Receipt).where(Receipt.id.in_(receipt_ids))).all())==6
    for receipt_id in receipt_ids:
        for model in (Audit,Outbox):
            assert session.scalar(select(func.count()).select_from(model).where(model.receipt_id==receipt_id))==1
with engine_for(state['admin_url']).connect() as connection:
    assert connection.scalar(text('SELECT version_num FROM alembic_version')) == 'next_0015'
    tables = connection.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename NOT IN ('alembic_version','environment_guard')")).all()
    assert len(tables)==82
    assert all(not connection.scalar(text("SELECT has_table_privilege('pdos_agent', :name, 'INSERT,UPDATE,DELETE')"),{'name':name}) for name in tables)
    names=['sample_readiness_facts','sample_current_readiness','verification_actual_method_batches','verification_actual_method_applicabilities','verification_current_actual_methods','verification_handoff_facts']
    forced={name:list(connection.execute(text('SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=to_regclass(:name)'),{'name':name}).one()) for name in names}
    assert all(all(v) for v in forced.values())
result={'schema_head':'next_0015','business_tables':82,'agent_direct_writes':0,'new_tables_forced_rls':forced,
    'model_calls':0,'nature':'synthetic','request_id':seed['request_id'],'build_id':seed['build_id'],
    'formal_versions':5,'status':'accepted','offered_pairs':2,'accepted_pairs':1,'returned_scopes':2,
    'remaining_gaps':current['coverage_gaps'],'readiness_states':['ready','hold'],'immutable_sample_states':['unknown','unknown'],
    'actual_method_states':['applicable','unknown'],'test_runs':0,'test_occupancy':0,'receipt_audit_outbox_each':6,
    'old_request_versions_unchanged':len(prior['verification-professional']['requests']),
    'old_build_sample_and_preparation_history_unchanged':True,'old_start_fixed_record_unchanged':True,
    'old_start_current_qualification':'needs_recheck_after_added_authority_facts',
    'successor_build_current_qualification':'limited_current','real_qualification':False,'formal_exit':False}
result['expired_synthetic_rounds_preserved'] = len(seed.get('expired_rounds', []))
for name,data in [('actual-preview.json',result),('actual-handoff-final.json',handoff),('actual-readiness-final.json',readiness)]:
    (REPORT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False))
