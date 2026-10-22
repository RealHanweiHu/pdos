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
p=cProfile.Profile(); p.enable()
with tenant_session(engine,UUID(s['preview_tenant_id'])) as db:
 ctx=Context(UUID(s['preview_tenant_id']),UUID(seed['actor_id']),UUID(seed['actor_id']))
 value=list_verification_handoff(db,ctx,UUID(s['preview_product_id']))
 print('Requests:',len(value['requests']))
p.disable(); pstats.Stats(p).sort_stats('cumtime').print_stats(45)
print(json.dumps({'query_count':len(queries),'query_seconds':sum(v for _,v in queries),'largest_queries':sorted(queries,key=lambda v:v[1],reverse=True)[:8]}))
