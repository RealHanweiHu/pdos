import cProfile,json,pstats,sys,time
from pathlib import Path
from uuid import UUID
from sqlalchemy import event
ROOT=Path.cwd()
sys.path.insert(0,str(ROOT/'pdos-next/tools'))
from local_environment import verified,read_state
from pdos_next.database import engine_for,tenant_session
from pdos_next.service import Context
from pdos_next.domain.sample_handoff.service import inspect_sample
from pdos_next.domain.sample_handoff.schemas import SampleRef
s=verified(read_state()); seed=json.loads((ROOT/'pdos-next/.local/wave12-seed.json').read_text()); engine=engine_for(s['app_url'])
from pdos_next.domain.professional_authority.service import configure_local_synthetic
from pdos_next.operational_bootstrap import configure_local_profile
from pdos_next.domain.verification_handoff.service import list_verification_handoff
configure_local_synthetic(engine,tenant_id=UUID(s['preview_tenant_id']),product_id=UUID(s['preview_product_id']),enabled=True)
configure_local_profile(engine,json.loads((ROOT/'pdos-next/.local/operational-synthetic-profile.json').read_text()))
queries=[]
@event.listens_for(engine,'before_cursor_execute')
def begin(conn,cursor,stmt,params,context,executemany): context._start=time.monotonic()
@event.listens_for(engine,'after_cursor_execute')
def end(conn,cursor,stmt,params,context,executemany): queries.append((stmt.split('\n')[0][:100],time.monotonic()-context._start))
from pdos_next.contracts import Command
from pdos_next.service import preview_command
from pdos_next.models import now
from pdos_next.domain.configurations.schemas import DefinitionReference
from pdos_next.domain.verification_handoff.service import event_source
from uuid import uuid4
data=json.loads((ROOT/'docs/reports/evidence/pdos-next-wave12-20261002/actual-offer.json').read_text())
pointer=data['current_by_request'][seed['request_id']]
row=next(v for v in data['requests'] if v['id']==pointer['request_version_id'])
samples=sorted([v for v in data['reference_samples'] if v['request_id']==seed['request_id']],key=lambda v:v['label'])
reads={v['artifact_id']:v for v in row['required_source_read_set']}
for sample in samples:reads.update({v['artifact_id']:v for v in sample['required_source_read_set']})
for method in data['actual_methods']:
 if method['request_id']==seed['request_id']: reads.update({v['artifact_id']:v for v in method['required_source_read_set']})
reads[seed['reference']['artifact_id']]={'artifact_id':seed['reference']['artifact_id'],'expected_revision':1}
covers=[{'sample_id':v['id'],'item_id':'dimension'} for v in samples]
command=Command(command_id=uuid4(),idempotency_key=str(uuid4()),operation='verification.handoff.accept',product_id=UUID(s['preview_product_id']),expected_revision=1,source_read_set=list(reads.values()),payload={'request_id':seed['request_id'],'expected_request_revision':row['revision'],'reason':'Synthetic preview profile, no execution','sources':[seed['reference']],'at':{'occurred_at':now().isoformat(),'original_timezone':'UTC','source':event_source(DefinitionReference.model_validate(seed['reference'])).model_dump(mode='json')},'coverage':covers[:1],'returned_coverage':covers[1:],'next_owner_id':seed['actor_id']})
p=cProfile.Profile(); p.enable()
with tenant_session(engine,UUID(s['preview_tenant_id'])) as db:
 ctx=Context(UUID(s['preview_tenant_id']),UUID(seed['actor_id']),UUID(seed['actor_id']))
 value=preview_command(db,ctx,command)
 print('Preview allowed, transaction rolled back')
 db.rollback()
p.disable(); pstats.Stats(p).sort_stats('cumtime').print_stats(45)
print(json.dumps({'query_count':len(queries),'query_seconds':sum(v for _,v in queries),'largest_queries':sorted(queries,key=lambda v:v[1],reverse=True)[:8]}))
