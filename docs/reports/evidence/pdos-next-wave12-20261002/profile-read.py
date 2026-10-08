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
queries=[]
@event.listens_for(engine,'before_cursor_execute')
def begin(conn,cursor,stmt,params,context,executemany): context._start=time.monotonic()
@event.listens_for(engine,'after_cursor_execute')
def end(conn,cursor,stmt,params,context,executemany): queries.append((stmt.split('\n')[0][:100],time.monotonic()-context._start))
p=cProfile.Profile(); p.enable()
with tenant_session(engine,UUID(s['preview_tenant_id'])) as db:
 ctx=Context(UUID(s['preview_tenant_id']),UUID(seed['actor_id']),UUID(seed['actor_id']))
 inspect_sample(db,ctx,UUID(s['preview_product_id']),SampleRef(id=seed['samples'][0]['id'],revision=1),seed['purpose'])
p.disable(); pstats.Stats(p).sort_stats('cumtime').print_stats(45)
print(json.dumps({'query_count':len(queries),'query_seconds':sum(v for _,v in queries),'largest_queries':sorted(queries,key=lambda v:v[1],reverse=True)[:8]}))
