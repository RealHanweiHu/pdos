"use client";
/* Operate: inherit the approved flat lists, quiet orange controls and eight-pixel
   surfaces. Read actual records first; inspect a row and continue the original
   controlled operation. Filters stay above the table; editing remains optional. */
import { useEffect, useRef, useState } from "react";
import { ArrowClockwise, ArrowRight } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { SimilarHistory, SimilarHistoryLayout } from "@/components/similar-history";
import { buildRecordPanels, readProfessionalBuilds, readProfessionalRecords, type ProfessionalApi, type ProfessionalReading, type ProfessionalRecord, type ProfessionalTarget } from "@/lib/professional-records";
import styles from "./project-professional.module.css";

export function ProjectProfessionalRecords({api,productId,projectId,panel,readVersion,initialBuild="",onEdit}:{api:ProfessionalApi;productId:string;projectId:string;panel:string;readVersion:number;initialBuild?:string;onEdit:(target:ProfessionalTarget)=>void}) {
  const [builds,setBuilds]=useState<Awaited<ReturnType<typeof readProfessionalBuilds>>|null>(null);
  const [build,setBuild]=useState(initialBuild),[reading,setReading]=useState<ProfessionalReading|null>(null);
  const [error,setError]=useState(""),[attempt,setAttempt]=useState(0),[query,setQuery]=useState(""),[history,setHistory]=useState(false),[detail,setDetail]=useState<ProfessionalRecord|null>(null);
  const detailHeading=useRef<HTMLHeadingElement>(null),detailTrigger=useRef<HTMLButtonElement|null>(null);
  const needsBuild=buildRecordPanels.has(panel);
  const generation=useRef(0),[paging,setPaging]=useState(false),[pageError,setPageError]=useState("");
  const [routeBuild,setRouteBuild]=useState(initialBuild);
  if(routeBuild!==initialBuild){setRouteBuild(initialBuild);if(build!==initialBuild){setBuild(initialBuild);setReading(null);setDetail(null);}}
  async function moreHistory(){
    if(!reading?.nextCursor||paging)return;
    const version=generation.current,previous=reading;setPaging(true);setPageError("");
    try{const page=await readProfessionalRecords(api,productId,projectId,panel,build,previous.nextCursor);
      if(version!==generation.current)return;
      setReading({...page,rows:[...previous.rows,...page.rows.filter(row=>!previous.rows.some(old=>old.id===row.id))],unavailable:Math.max(previous.unavailable,page.unavailable)});
    }catch(e){if(version===generation.current){if([401,403].includes((e as {status?:number}).status??0)){setReading(null);setDetail(null);setError("当前访问不可用，已隐藏原记录。请恢复访问后重新读取。");}else setPageError(e instanceof Error?e.message:"历史记录暂不可读，请重试。");}}
    finally{if(version===generation.current)setPaging(false);}
  }
  useEffect(()=>{let active=true;const version=++generation.current;
    void Promise.resolve().then(async()=>{if(!active)return;setBuilds(null);setReading(null);setError("");setDetail(null);setPaging(false);setPageError("");try{
      if(needsBuild){const data=await readProfessionalBuilds(api,productId,projectId);if(!active)return;setBuilds(data);if(build&&!data.items.some(r=>r.id===build))throw new Error("指定轮次不在本项目当前可读范围，请明确选择其他轮次或重新读取。");const next=build&&data.items.some(r=>r.id===build)?build:!build&&data.items.length===1?data.items[0].id:"";if(next!==build){setBuild(next);return;}if(!next)return;}
      const data=await readProfessionalRecords(api,productId,projectId,panel,build);if(active)setReading(data);
    }catch(e){if(active){setReading(null);setError(e instanceof Error?e.message:"记录暂不可读。");}}});return()=>{active=false;generation.current=version+1;};
  },[api,productId,projectId,panel,build,needsBuild,readVersion,attempt]);
  const rows=reading?.rows.filter(r=>(history||!r.historical)&&`${r.title} ${r.kind} ${r.status}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()))??[];
  return <section className={styles.records} aria-label="专业记录">
    <div className={styles.recordToolbar}>
      {needsBuild&&<label>试制轮次<select aria-label="专业记录试制轮次" value={build} disabled={!builds} onChange={e=>setBuild(e.target.value)}><option value="">选择本项目轮次</option>{build&&!builds?.items.some(r=>r.id===build)&&<option value={build}>{builds?"指定轮次暂不可读":"正在核对指定轮次…"}</option>}{builds?.items.map(r=><option key={r.id} value={r.id}>{r.name}</option>)}</select></label>}
      <label className={styles.recordSearch}>查找记录<input type="search" aria-label="查找专业记录" placeholder="搜索名称、类型或状态" value={query} onChange={e=>setQuery(e.target.value)}/></label>
      <label className={styles.historyToggle}><input type="checkbox" checked={history} onChange={e=>setHistory(e.target.checked)}/>包含历史版本</label>
      <Button size="sm" variant="ghost" aria-label="刷新专业记录" onClick={()=>setAttempt(n=>n+1)}><ArrowClockwise size={14}/></Button>
    </div>
    {error?<div role="alert" className={styles.readNotice}><p>{error}</p><Button size="sm" variant="outline" onClick={()=>setAttempt(n=>n+1)}>重新读取</Button></div>:needsBuild&&!builds?<p role="status">正在读取本项目轮次…</p>:needsBuild&&!build?<p className={styles.readNotice}>{builds?.items.length?"选择轮次，查看本轮真实记录。":"本项目尚无可读轮次；可从工程配置与 BOM 准备新的试制计划。"}</p>:!reading?<p role="status">正在读取专业记录…</p>:<>
      {((reading.incomplete&&!reading.nextCursor)||reading.unavailable>0||builds?.incomplete||!!builds?.unavailable)&&<p className={styles.readNotice}>当前仅显示已读取范围。更多或暂不可读记录请在专业办理中核对，不能据此判断全部完成。</p>}
      <div className={styles.recordScroll}><table><thead><tr><th>记录</th><th>类型</th><th>状态</th><th>版本与依据</th><th>保存时间</th></tr></thead><tbody>{rows.map(row=><tr key={row.id}><td><button className={styles.recordLink} aria-expanded={detail?.id===row.id} aria-controls={`professional-record-detail-${panel}`} onClick={event=>{detailTrigger.current=event.currentTarget;setDetail(row);requestAnimationFrame(()=>{detailHeading.current?.scrollIntoView({block:"nearest"});detailHeading.current?.focus({preventScroll:true});});}}>{row.title}<ArrowRight size={12}/></button></td><td>{row.kind}</td><td>{row.status}</td><td>{row.revision?`v${row.revision} · `:""}{row.historical?"历史版本":row.source}</td><td>{row.at?new Date(row.at).toLocaleString("zh-CN"):"未登记"}</td></tr>)}</tbody></table></div>
      {pageError&&<p role="alert" className={styles.readNotice}>{pageError}</p>}
      {reading.nextCursor&&<Button size="sm" variant="outline" disabled={paging} onClick={()=>{setHistory(true);void moreHistory();}}>{paging?"正在读取历史…":"读取更早记录"}</Button>}
      {!rows.length&&<p className={styles.readNotice}>{query?"没有匹配的记录。":"当前范围尚无记录。可展开专业办理，创建或接续当前工作。"}</p>}
    </>}
    {detail&&<section id={`professional-record-detail-${panel}`} className={styles.recordDetail} aria-label="专业记录详情"><SimilarHistoryLayout history={(panel === "quality" || panel === "followup") && detail.target.issue ? <SimilarHistory api={api} productId={productId} issueId={detail.target.issue} versionId={detail.id}/> : panel === "changes" && detail.target.change ? <SimilarHistory api={api} productId={productId} changeId={detail.target.change} versionId={detail.id}/> : null}><header><h3 ref={detailHeading} tabIndex={-1}>{detail.title} · {detail.kind}</h3><Button size="sm" variant="ghost" onClick={()=>{setDetail(null);detailTrigger.current?.focus();}}>收起详情</Button></header><p>{detail.status} · {detail.source}{detail.historical?" · 历史固定版本":""}</p><dl>{detail.facts.map(([name,text])=><div key={name}><dt>{name}</dt><dd>{text}</dd></div>)}</dl><Button variant="outline" size="sm" onClick={()=>onEdit(detail.target)}>继续专业办理<ArrowRight size={12}/></Button><p className={styles.readNotice}>进入后按当前事实核对，原有确认、具名决定及历史记录保留。</p></SimilarHistoryLayout></section>}
  </section>;
}
