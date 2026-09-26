from pathlib import Path
import json,sys,subprocess
root=Path('/Users/huhanwei/Documents/ai-native-R&D-platform');out=root/'docs/reports/evidence/2026-09-08-ux10'
main=json.loads((out/'dataset.json').read_text())['projects'][0];phase=sys.argv[1];base='http://127.0.0.1:'+('3312' if phase=='baseline' else '3314')
config={'phase':phase,'pages':[{'kind':'my-work','url':base+'/my-work'},{'kind':'project','url':base+f"/projects?project={main['id']}&tab=overview"},{'kind':'review','url':base+f"/ai-review?finding={main['finding_id']}"}]}
p=Path(f'/private/tmp/pdos-ux10-visual-{phase}.js');p.write_text((out/'visual.template.js').read_text().replace('__CONFIG__',json.dumps(config)))
r=subprocess.run(['/Users/huhanwei/.npm/_npx/31e32ef8478fbf80/node_modules/.bin/playwright-cli','-s=pdos-ux10','run-code','--filename',str(p)],capture_output=True,text=True,cwd=root)
(root/f'output/playwright/ux10-2026-09-08/{phase}-mobile.log').write_text(r.stdout+'\n'+r.stderr)
raw=json.loads(r.stdout.split('### Result\n')[1].split('\n###')[0]);(out/f'{phase}-mobile.json').write_text(json.dumps(raw,ensure_ascii=False,indent=2)+'\n');print(json.dumps(raw,ensure_ascii=False))
