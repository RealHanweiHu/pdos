"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { field, obj, rows, text, type Row } from "@/components/quality/fmea-sources";
import { noticeCall } from "@/components/projects/supplier-notice-applications";
import { CostAlternativeSnapshot } from "@/components/projects/cost-alternatives";
import { Statement } from "./change-work-package-proposal";

const labels: Record<string,string> = {scope:"方案范围",quality_impact:"质量／性能代价",schedule_impact:"时间代价",supplier_impact:"供方代价",nre_impact:"NRE代价",validation_requirements:"验证要求与完成条件",unknowns:"共同及本项缺项、处理办法与保留限制",correspondence_basis:"原费用与备选范围的对应依据",evidence_location:"原文件页码、表格或段落位置",reason:"登记此方案的具名依据"};
const originalLabels: Record<string,string> = {scope:"拟改变范围",expected_cost_effect:"预期费用影响",quality_impact:"质量／性能代价",schedule_impact:"时间代价",supplier_impact:"供方代价",nre_impact:"NRE影响",verification:"所需验证",correspondence_basis:"费用对应依据"};
const filled=(v:unknown,max=2048)=>typeof v==="string"&&!!v.trim()&&v.length<=max;
export function costReductionReady(payload: Row) {
  const review=obj(payload.review), choices=rows(review.choices), options=rows(obj(payload.assessment).options);
  return payload.details_confirmed===true&&filled(review.reason)&&filled(review.scope_and_limits)
    &&choices.length===options.length&&new Set(choices.map(c=>c.key)).size===options.length
    &&options.every(o=>choices.some(c=>c.key===o.key))&&choices.some(c=>c.disposition==="adopt")
    &&choices.every(c=>filled(c.reason)&&(c.disposition==="exclude"||c.disposition==="adopt"
      &&!!c.expected_digest&&filled(obj(c.draft).title,256)&&!!obj(c.draft).evidence_id
      &&Object.keys(labels).every(k=>filled(obj(c.draft)[k]))));
}
function Input({label,value,onChange,maxLength=2048}:{label:string;value:unknown;onChange:(v:string)=>void;maxLength?:number}) {
  return <label className="block">{label}<textarea className={field} maxLength={maxLength} value={text(value)} onChange={e=>onChange(e.target.value)}/></label>;
}
export function CostReductionProposalView({projectId,payload,onChange}:{projectId:string;payload:Row;onChange?:(v:Row)=>void}) {
  const base=`/api/projects/${projectId}/npi`, assessment=obj(payload.assessment), selection=obj(payload.selection), refLabels=obj(payload.reference_labels);
  const review=obj(payload.review),choices=rows(review.choices),options=rows(assessment.options);
  const [context,setContext]=useState<Row|null>(null),[search,setSearch]=useState(""),[calculations,setCalculations]=useState<Row[]>([]),[cursor,setCursor]=useState<string|null>(null);
  const [previews,setPreviews]=useState<Record<string,Row>>({}),[busy,setBusy]=useState(false),[error,setError]=useState("");
  const update=(patch:Row)=>onChange?.({...payload,review:{...review,...patch},details_confirmed:false});
  const change=(key:unknown,patch:Row)=>update({choices:choices.map(c=>c.key===key?{...c,...patch}:c)});
  const edit=(c:Row,k:string,v:unknown)=>change(c.key,{draft:{...obj(c.draft),[k]:v},expected_digest:null});
  async function act(fn:()=>Promise<void>){setBusy(true);setError("");try{await fn();}catch(e){setError(e instanceof Error?e.message:"核对未完成");}finally{setBusy(false);}}
  async function load(start=false){const data=await noticeCall(`${base}/cost-reduction/review-context?${new URLSearchParams({observation_id:text(selection.observation_id),search})}`);setContext(data);
    if(start)update({reason:"",scope_and_limits:"",choices:options.map(o=>({key:o.key,disposition:"",reason:"",draft:null,expected_digest:null}))});
  }
  function adopt(c:Row){const o=options.find(o=>o.key===c.key)??{};change(c.key,{disposition:"adopt",expected_digest:null,draft:{
    case_id:context?.case_id,observation_id:selection.observation_id,previous_id:null,status:"proposed",title:o.title,
    scope:obj(o.scope).text??"",quality_impact:obj(o.quality_impact).text??"",schedule_impact:obj(o.schedule_impact).text??"",supplier_impact:obj(o.supplier_impact).text??"",nre_impact:obj(o.nre_impact).text??"",
    validation_requirements:obj(o.verification).text??"",correspondence_basis:obj(o.correspondence_basis).text??"",unknowns:"",evidence_id:"",evidence_location:"",proposal_rollup_id:null,reason:""
  }});}
  async function loadCalculations(before?:string){const value=await noticeCall(`${base}/cost-rollups${before?`?before=${before}`:""}`);setCalculations(old=>{const next=rows(value.items);const keep=old.filter(r=>choices.some(c=>obj(c.draft).proposal_rollup_id===r.id)&&!next.some(n=>n.id===r.id));return [...keep,...next];});setCursor(value.next_cursor?text(value.next_cursor):null);}
  return <div className="space-y-3 p-3 text-sm">
    <p>接受保存逐项人工方案；独立应用后为每个采用项建立新的降本备选，后续仍走原ECR影响分析、批准及验证。</p>
    <p className="whitespace-pre-wrap">本次分析范围：{text(assessment.coverage_limits)}</p>
    {Array.isArray(assessment.missing)&&<p>共同待补：{assessment.missing.map(String).join("；")||"无列出项，仍须具名核对"}</p>}
    {rows(assessment.observations).map((v,i)=><Statement key={i} value={v} labels={refLabels}/>)}
    {options.map(o=><details className="rounded-md border p-3 space-y-2" key={text(o.key)} open><summary className="cursor-pointer font-medium">原建议：{text(o.title)}</summary>{Object.entries(originalLabels).map(([k,label])=><div key={k}><strong>{label}</strong><Statement value={obj(o[k])} labels={refLabels}/></div>)}{Array.isArray(o.missing)&&<p>本项待补：{o.missing.map(String).join("；")||"未列出"}</p>}</details>)}
    {error&&<p role="alert" className="text-destructive">{error}</p>}
    {onChange&&!payload.review&&<Button size="sm" variant="outline" disabled={busy} onClick={()=>void act(()=>load(true))}>开始逐项核对及编辑方案</Button>}
    {payload.review!=null&&<><div className="flex gap-2 items-end"><label className="flex-1">查找方案原文件<input className={field} value={search} maxLength={256} onChange={e=>setSearch(e.target.value)}/></label><Button size="sm" variant="outline" disabled={busy} onClick={()=>void act(()=>load())}>读取文件与当前范围</Button></div>
      {context?.documents_more===true&&<p>当前显示最近200份匹配文件，请缩小搜索范围。</p>}
      <Button size="sm" variant="outline" disabled={busy} onClick={()=>void act(()=>loadCalculations())}>读取已保存的费用计算</Button>{cursor&&<Button size="sm" variant="outline" disabled={busy} onClick={()=>void act(()=>loadCalculations(cursor))}>更早费用计算</Button>}
      <fieldset disabled={!onChange||busy} className="space-y-3"><legend className="font-medium">人工核对与实际采用内容</legend>
      {choices.map(c=>{const d=obj(c.draft),key=text(c.key),v=previews[key],current=v?.digest===c.expected_digest;return <article key={key} className="space-y-3 rounded-md border p-3"><h4 className="font-medium">{text(options.find(o=>o.key===c.key)?.title)}</h4>
        <label className="block">本次处理<select className={field} value={text(c.disposition)} onChange={e=>{if(e.target.value==="adopt")adopt(c);else change(c.key,{disposition:e.target.value,draft:null,expected_digest:null});}}><option value="">请选择</option><option disabled={!context} value="adopt">采用，建立待验证的备选方案</option><option value="exclude">本次不采用</option></select></label>
        <Input label="采用、调整或不采用的理由" value={c.reason} onChange={reason=>change(c.key,{reason})}/>
        {c.disposition==="adopt"&&<>
          <Input label="实际方案名称" value={d.title} maxLength={256} onChange={title=>edit(c,"title",title)}/>
          <label className="block">方案原文件<select className={field} value={text(d.evidence_id)} onChange={e=>edit(c,"evidence_id",e.target.value)}><option value="">请选择实际原件</option>{!!d.evidence_id&&!rows(context?.documents).some(v=>v.id===d.evidence_id)&&<option value={text(d.evidence_id)}>原选文件：{text(d.evidence_id)}</option>}{rows(context?.documents).map(v=><option value={text(v.id)} key={text(v.id)}>{text(v.filename)}</option>)}</select></label>
          <label className="block">备选预期费用（可选）<select className={field} value={text(d.proposal_rollup_id)} onChange={e=>edit(c,"proposal_rollup_id",e.target.value||null)}><option value="">尚无计算，金额未知</option>{!!d.proposal_rollup_id&&!calculations.some(v=>v.id===d.proposal_rollup_id)&&<option value={text(d.proposal_rollup_id)}>原选计算：{text(d.proposal_rollup_id)}</option>}{calculations.map(v=><option disabled={obj(v.command).stage==="actual"} value={text(v.id)} key={text(v.id)}>{text(v.title)} · {obj(v.command).stage==="actual"?"ERP实际，不能作为预期":obj(v.command).stage==="quote"?"报价":"估算"} · {text(obj(v.command).as_of)}</option>)}</select></label>
          {Object.entries(labels).map(([k,label])=><Input key={k} label={label} value={d[k]} onChange={value=>edit(c,k,value)}/>)}
          <Button size="sm" variant="outline" onClick={()=>void act(async()=>{const value=await noticeCall(`${base}/cost-alternatives/preview`,d);setPreviews(old=>({...old,[key]:value}));change(c.key,{draft:value.command,expected_digest:value.digest});})}>预览实际费用、原件与代价</Button>
          {!!c.expected_digest&&!current&&<p>已保存预览标识。可重新读取费用和原件；接受及应用均会重核其版本。</p>}
          {v&&<div className="space-y-2"><p>{current?"此预览对应当前方案":"方案已调整，请重新预览"}</p><CostAlternativeSnapshot value={v} projectId={projectId}/></div>}
        </>}
      </article>;})}
      <Input label="本次接受理由" value={review.reason} onChange={reason=>update({reason})}/>
      <Input label="本次应用范围、排除项及整体保留限制" value={review.scope_and_limits} onChange={scope_and_limits=>update({scope_and_limits})}/>
      <label className="flex gap-2 items-start"><input type="checkbox" checked={payload.details_confirmed===true} onChange={e=>onChange?.({...payload,details_confirmed:e.target.checked})}/><span>已核对每项原引用、实际文件、费用范围、质量／时间／供方／NRE代价和缺项。独立应用后的业务方案供项目有权限成员读取，原私人讨论保持原读取范围。保存的预期金额不代表已经实现的降本。</span></label>
      </fieldset></>}
  </div>;
}
export function CostReductionApplied({projectId,findingId}:{projectId:string;findingId:string}) {
  const [data,setData]=useState<Row|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState("");
  async function load(){setBusy(true);setError("");try{setData(await noticeCall(`/api/projects/${projectId}/npi/cost-reduction/applications?finding_id=${findingId}`));}catch(e){setError(e instanceof Error?e.message:"读取实际方案未完成");}finally{setBusy(false);}}
  return <details className="space-y-2 rounded-md border p-3 text-sm" onToggle={e=>{if(e.currentTarget.open&&!data&&!busy)void load();}}><summary className="cursor-pointer">实际采用方案、原版本及当前修订</summary><Button size="sm" variant="outline" disabled={busy} onClick={()=>void load()}>刷新实际方案</Button>{error&&<p role="alert" className="text-destructive">{error}</p>}{data&&!data.application&&<p>尚未独立应用。</p>}{rows(data?.items).map(v=>{const a=obj(v.alternative),now=obj(v.current);return <article key={text(a.id)} className="space-y-2 border-l pl-3"><h4 className="font-medium">原采用：{text(a.title)} · v{text(a.revision_number)}</h4><p>当前：{text(now.title)} · v{text(now.revision_number)} · {now.status==="withdrawn"?"已撤回":"备选方案，待原工程批准与验证"}</p><CostAlternativeSnapshot projectId={projectId} value={obj(a.snapshot)}/><a className="text-primary underline" href={`/projects?project=${projectId}&tab=materials`}>回成本与供应页继续比较、修订或转入ECR</a></article>;})}</details>;
}
