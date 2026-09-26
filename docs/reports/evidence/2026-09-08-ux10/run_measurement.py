import json,sys,subprocess
from pathlib import Path
root=Path('/Users/huhanwei/Documents/ai-native-R&D-platform')
evidence=root/'docs/reports/evidence/2026-09-08-ux10'
data=json.loads((evidence/'dataset.json').read_text()); main=data['projects'][0]
phase,kind,cache=sys.argv[1:4]
port=3312 if phase=='baseline' else 3314
suffix={'my-work':'/my-work','project':f"/projects?project={main['id']}&tab=overview",'review':f"/ai-review?finding={main['finding_id']}"}[kind]
config={'phase':phase,'kind':kind,'cache':cache,'url':f'http://127.0.0.1:{port}{suffix}','projectId':main['id'],'projectIds':[p['id'] for p in data['projects']]}
code=(evidence/'measure.template.js').read_text().replace('__CONFIG__',json.dumps(config))
file=Path(f'/private/tmp/pdos-ux10-{phase}-{kind}-{cache}.js');file.write_text(code)
proc=subprocess.run(['/Users/huhanwei/.npm/_npx/31e32ef8478fbf80/node_modules/.bin/playwright-cli','-s=pdos-ux10','run-code','--filename',str(file)],capture_output=True,text=True,cwd=root)
log=root/f'output/playwright/ux10-2026-09-08/{phase}-{kind}-{cache}.log';log.write_text(proc.stdout+'\n'+proc.stderr)
try:
    raw=proc.stdout.split('### Result\n',1)[1].split('\n###',1)[0]
    result=json.loads(raw)
    (evidence/f'{phase}-{kind}-{cache}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('p50','p95','max','success')},ensure_ascii=False))
except Exception:
    print(proc.stdout[-2000:]);print(proc.stderr[-500:]);raise
