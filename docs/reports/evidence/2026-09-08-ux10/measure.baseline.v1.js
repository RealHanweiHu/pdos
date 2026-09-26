async (page) => {
  const config = __CONFIG__;
  const browser = page.context().browser();
  const storageState = await page.context().storageState();
  const viewport = {width:1440,height:900};
  const newContext = () => browser.newContext({storageState,viewport,locale:'zh-CN',timezoneId:'America/Los_Angeles',deviceScaleFactor:1});
  const warmContext = config.cache === 'warm' ? await newContext() : null;
  const warmPage = warmContext ? await warmContext.newPage() : null;
  const samples=[];
  for (let i=config.cache==='warm' ? -2 : 0;i<30;i++) {
    const context = warmContext || await newContext();
    const target = warmPage || await context.newPage();
    const apis=[]; const errors=[];
    const onResponse = response => { const path=response.url().replace(/^https?:\/\/[^/]+/, '').split('?')[0]; if(path.startsWith('/api/')) apis.push({path,status:response.status()}); };
    const onError = error => errors.push(error.message);
    target.on('response',onResponse); target.on('pageerror',onError);
    let result;
    try {
      await target.goto('about:blank');
      await target.goto(config.url,{waitUntil:'commit',timeout:10000});
      await target.waitForFunction(kind => {
        if(kind==='my-work') return document.querySelector('section[aria-label="任务"] a') && document.querySelector('section[aria-label="站内通知"]')?.textContent.includes('200');
        if(kind==='project') return document.querySelector('#project-tab-overview')?.getAttribute('aria-selected')==='true' && document.querySelector('[data-metric="task"]')?.textContent==='400' && document.querySelector('[data-metric="issue"]')?.textContent==='20' && document.querySelector('[data-metric="risk"]')?.textContent==='5' && [...document.querySelectorAll('button')].some(b=>b.textContent==='编辑项目'&&!b.disabled);
        return document.querySelector('article[aria-label="Finding 详情"] h2')?.textContent==='UX10 待审建议 01-01' && [...document.querySelectorAll('button')].some(b=>b.textContent.includes('接受建议')&&!b.disabled) && document.querySelector('[aria-label="待办摘要"]')?.textContent.includes('75');
      },config.kind,{timeout:10000});
      await target.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
      result=await target.evaluate(kind=>{
        const selectors=kind==='my-work'?['section[aria-label="任务"] a']:kind==='project'?['[data-metric="task"]','button']:['article[aria-label="Finding 详情"] h2','button'];
        const boxes=selectors.map(selector=>{
          const element=selector==='button'?[...document.querySelectorAll('button')].find(b=>kind==='project'?b.textContent==='编辑项目':b.textContent.includes('接受建议')):document.querySelector(selector);
          const r=element.getBoundingClientRect(); return {selector,text:element.textContent,top:r.top,bottom:r.bottom,left:r.left,right:r.right,inViewport:r.top>=0&&r.left>=0&&r.bottom<=innerHeight&&r.right<=innerWidth};
        });
        return {ms:performance.now(),boxes,overflow:document.documentElement.scrollWidth>innerWidth,resources:performance.getEntriesByType('resource').filter(x=>new URL(x.name).pathname.startsWith('/api/')).map(x=>({path:new URL(x.name).pathname,start:Math.round(x.startTime),duration:Math.round(x.duration),bytes:x.transferSize})),userAgent:navigator.userAgent};
      },config.kind);
      const required=config.kind==='my-work'?['/api/session/me','/api/me/work','/api/me/notifications']:config.kind==='project'?['/api/session/me','/api/projects',`/api/projects/${config.projectId}/tasks`,`/api/projects/${config.projectId}/issues`,`/api/projects/${config.projectId}/risks`,`/api/projects/${config.projectId}/activity`,`/api/ai/projects/${config.projectId}/runs`]:['/api/session/me','/api/projects','/api/ai/findings','/api/ai/review-inbox'];
      if(config.kind==='review') required.push(...(config.phase==='baseline'?config.projectIds.map(id=>`/api/projects/${id}/risk-candidates`):['/api/ai/risk-candidates']));
      const missing=required.filter(path=>!apis.some(a=>a.path===path&&a.status===200));
      if(missing.length||apis.some(a=>a.status>=400)||errors.length) throw new Error(JSON.stringify({missing,apis,errors}));
      result={...result,ok:true,apis,errors,index:i};
      if(i===0) await target.screenshot({path:`output/playwright/ux10-2026-09-08/${config.phase}-${config.kind}-${config.cache}-1440.png`});
    } catch(error) { result={ok:false,ms:10000,error:String(error),apis,errors,index:i}; }
    target.off('response',onResponse); target.off('pageerror',onError);
    if(!warmContext) await context.close();
    if(i>=0) samples.push(result);
  }
  if(warmContext) await warmContext.close();
  const sorted=samples.map(s=>s.ms).sort((a,b)=>a-b);
  return {config,viewport,browser:browser.version(),samples,p50:sorted[14],p95:sorted[28],max:sorted[29],success:samples.filter(s=>s.ok).length};
}
