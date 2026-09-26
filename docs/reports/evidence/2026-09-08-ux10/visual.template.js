async (page) => {
  const config=__CONFIG__;
  const browser=page.context().browser();
  const storageState=await page.context().storageState();
  const results=[];
  for(const width of [390,320]) {
    const context=await browser.newContext({storageState,viewport:{width,height:width===390?844:568},locale:'zh-CN',timezoneId:'America/Los_Angeles',deviceScaleFactor:1});
    const target=await context.newPage();
    for(const item of config.pages) {
      await target.goto(item.url);
      await target.waitForFunction(kind=>{
        if(kind==='my-work') return document.querySelector('section[aria-label="任务"] a') && document.querySelector('section[aria-label="站内通知"]')?.textContent.includes('200');
        if(kind==='project') return document.querySelector('[data-metric="task"]')?.textContent==='400';
        return document.querySelector('article[aria-label="Finding 详情"] h2')?.textContent==='UX10 待审建议 01-01' && document.querySelector('[aria-label="待办摘要"]')?.textContent.includes('75');
      },item.kind,{timeout:10000});
      await target.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
      const measurements=await target.evaluate(kind=>{
        const selector=kind==='my-work'?'section[aria-label="任务"] a':kind==='project'?'section[aria-label="项目概览"]':'article[aria-label="Finding 详情"] h2';
        const r=document.querySelector(selector).getBoundingClientRect();
        return {width:innerWidth,height:innerHeight,overflow:document.documentElement.scrollWidth>innerWidth,primaryTop:r.top,primaryInViewport:r.top>=0&&r.top<innerHeight};
      },item.kind);
      await target.screenshot({path:`output/playwright/ux10-2026-09-08/${config.phase}-${item.kind}-${width}.png`});
      results.push({kind:item.kind,...measurements});
    }
    await context.close();
  }
  return results;
}
