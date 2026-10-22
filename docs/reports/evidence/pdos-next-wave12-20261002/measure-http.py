import json,sys,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import httpx
ROOT=Path.cwd();REPORT=ROOT/'docs/reports/evidence/pdos-next-wave12-20261002'
sys.path.insert(0,str(ROOT/'pdos-next/tools'))
from local_environment import read_state,verified
state=verified(read_state());seed=json.loads((ROOT/'pdos-next/.local/wave12-seed.json').read_text())
def read(path):
 begin=time.monotonic()
 with httpx.Client(base_url='http://127.0.0.1:8898',trust_env=False,timeout=120,headers={'Authorization':'Bearer '+state['preview_token']}) as c:
  response=c.get(f"/v1/products/{state['preview_product_id']}/{path}")
  response.raise_for_status();data=response.json()
 return {'path':path,'status':response.status_code,'seconds':round(time.monotonic()-begin,3),'rows':len(data.get('requests',data.get('samples',[])))}
paths=[f"verification-handoff?build_id={seed['build_id']}",f"sample-handoff?build_id={seed['build_id']}&purpose=Verify%20preparation"]
mode=sys.argv[1]
if mode=='sequential': result=[read(p) for p in paths]
elif mode=='concurrent':
 with ThreadPoolExecutor(max_workers=2) as pool: result=list(pool.map(read,paths))
else:raise ValueError(mode)
(REPORT/f'http-read-{mode}.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
