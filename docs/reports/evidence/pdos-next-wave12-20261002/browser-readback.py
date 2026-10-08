import json,sys,shutil
from pathlib import Path
from uuid import UUID
import httpx
from sqlalchemy import select,func
ROOT=Path.cwd();REPORT=ROOT/'docs/reports/evidence/pdos-next-wave12-20261002'
sys.path.insert(0,str(ROOT/'pdos-next/tools'))
from local_environment import read_state,verified
from pdos_next.database import engine_for,tenant_session
from pdos_next.models import Receipt,Audit,Outbox
from pdos_next.domain.verification_handoff.models import ActualMethodApplicability
state=verified(read_state());seed=json.loads((ROOT/'pdos-next/.local/wave12-seed.json').read_text())
old=json.loads((REPORT/'actual-handoff-final.json').read_text());old_pointer=old['current_by_request'][seed['request_id']]
with httpx.Client(base_url='http://127.0.0.1:8898',trust_env=False,timeout=120,headers={'Authorization':'Bearer '+state['preview_token']}) as c:
 response=c.get(f"/v1/products/{state['preview_product_id']}/verification-handoff",params={'build_id':seed['build_id']});response.raise_for_status();data=response.json()
assert data['current_by_request'][seed['request_id']]==old_pointer
row=next(v for v in data['requests'] if v['id']==old_pointer['request_version_id']);assert row['revision']==5 and len(row['accepted_coverage'])==1
b=next(v for v in seed['samples'] if v['label'].endswith('B'));a=next(v for v in seed['samples'] if v['label'].endswith('A'))
methods=[v for v in data['actual_methods'] if v['request_id']==seed['request_id']]
b_new=next(v for v in methods if v['sample']['id']==b['id'] and v['revision']==2)
assert b_new['status']=='unknown' and b_new['current']
assert len([v for v in methods if v['sample']['id']==a['id']])==1
assert next(v for v in methods if v['sample']['id']==a['id'])['revision']==1
with tenant_session(engine_for(state['app_url']),UUID(state['preview_tenant_id'])) as s:
 method=s.get(ActualMethodApplicability,UUID(b_new['id']))
 receipts=s.scalars(select(Receipt).where(Receipt.subject_id==method.batch_id,Receipt.operation=='verification.actual_method.prepare')).all();assert len(receipts)==1
 receipt=receipts[0]
 for model in (Audit,Outbox):assert s.scalar(select(func.count()).select_from(model).where(model.receipt_id==receipt.id))==1
 receipt_id=str(receipt.id)
actions=json.loads((REPORT/'browser-actions.json').read_text());actions.update(backend_readback_passed=True,additional_receipt_id=receipt_id,audit_count=1,outbox_count=1,formal_pointer_unchanged=True,accepted_a_method_unchanged=True)
(REPORT/'browser-actions.json').write_text(json.dumps(actions,ensure_ascii=False,indent=2)+'\n')
(REPORT/'actual-handoff-after-browser.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
actual=json.loads((REPORT/'actual-preview.json').read_text());actual['browser_method_renewal']={'sample':'B','revision':2,'status':'unknown','one_additional_receipt_audit_outbox':True,'formal_version_unchanged':5,'accepted_a_unchanged':True}
(REPORT/'actual-preview.json').write_text(json.dumps(actual,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'result':'passed','b_method_revision':2,'formal_revision':5,'accepted_a_unchanged':True,'additional_receipt_audit_outbox_each':1}))
