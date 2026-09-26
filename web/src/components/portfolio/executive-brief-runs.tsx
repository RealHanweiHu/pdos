"use client";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { cancelAgentRun } from "@/components/ai/ai-api";
import { AgentRunProgressPanel } from "@/components/ai/agent-run-progress";
import { caseLinkRequest } from "@/components/cases/case-requirements";
import { obj, rows, text, field, type Row } from "@/components/quality/fmea-sources";

const states:Record<string,string>={running:"整理中",succeeded:"已生成解释",degraded:"未完成",failed:"已停止"};
function Statement({value,refs,sources}:{value:Row;refs:Row;sources:Row[]}) {
  return <div className="space-y-1"><p className="whitespace-pre-wrap">{text(value.text)} <span className="text-muted-foreground">（{value.nature==="observed"?"原资料观察":value.nature==="derived"?"基于资料的解释":"待核实假设"}）</span></p>{rows(value.citations).map((c,i)=>{const source=sources.find(r=>r.reference_id===c.reference_id);return <details key={i}><summary className="cursor-pointer text-muted-foreground">核对原字段 · {text(refs[text(c.reference_id)]??c.reference_id)}</summary><p className="whitespace-pre-wrap break-words">{text(c.quoted_value)}</p><p className="break-all text-muted-foreground">{Array.isArray(c.field_path)?c.field_path.join(" → "):""}</p>{source?.href!=null&&<a className="inline-flex min-h-11 items-center text-primary underline" href={text(source.href)}>回到原资料与办理入口</a>}</details>;})}</div>;
}
export function ExecutiveBriefRuns({prepared}:{prepared:Row}) {
  const [data,setData]=useState<Row|null>(null),[selected,setSelected]=useState<Row|null>(null);
  const [instruction,setInstruction]=useState(""),[busy,setBusy]=useState(false),[generating,setGenerating]=useState(false),[error,setError]=useState("");
  const attempt=useRef<{key:string;id:string}|null>(null);
  const selection=obj(prepared.selection);
  async function read(before?:string){const value=await caseLinkRequest<Row>("planning/executive-brief-history",{selection,before_id:before??null});setData(old=>before?{...value,items:[...rows(old?.items),...rows(value.items)]}:value);}
  async function open(id:string){const value=await caseLinkRequest<Row>("planning/executive-brief-history",{selection,run_id:id});setSelected(rows(value.items)[0]??null);}
  async function act(fn:()=>Promise<void>){setBusy(true);setError("");try{await fn();}catch(e){setError(e instanceof Error?e.message:"管理摘要读取未完成");}finally{setBusy(false);}}
  async function generate(body:Row,requestId?:string){const key=JSON.stringify(body);if(requestId)attempt.current={key,id:requestId};else if(attempt.current?.key!==key)attempt.current={key,id:crypto.randomUUID()};setGenerating(true);setError("");try{const value=await caseLinkRequest<Row>("planning/executive-brief-runs",{...body,request_id:attempt.current!.id});await read();await open(text(value.run_id));attempt.current=null;}catch(e){setError(e instanceof Error?e.message:"请求未完成，可刷新原运行或沿相同输入接续");}finally{setGenerating(false);}}
  const assessment=obj(selected?.assessment),refs=obj(selected?.reference_labels),sources=rows(selected?.frozen_sources);
  const projectName=(id:unknown)=>text(obj(sources.find(r=>r.reference_id===`executive:project:${text(id)}:health`)?.fields).project_name)||text(id);
  return <details className="space-y-3 rounded-md border p-3" onToggle={e=>{if(e.currentTarget.open&&!data&&!busy)void act(()=>read());}}>
    <summary className="cursor-pointer text-sm font-medium">AI解释管理异常与人工下一步</summary>
    <div className="space-y-3 text-xs"><p>解释上方本次读取的项目范围，逐项核对原字段、缺数和省略明细。结果保留为分析记录；正式裁决、资源调整和业务执行沿原入口办理。</p>
      {error&&<p role="alert" className="text-destructive">{error}</p>}
      {data&&data.rollout!=="live"&&<p className="text-primary">此能力待阶段评测，当前可准备资料和读取原记录，尚未开放生成。</p>}
      <Button type="button" variant="outline" size="sm" disabled={busy} onClick={()=>void act(async()=>{await read();if(selected)await open(text(selected.run_id));})}>刷新本范围原运行与回执</Button>
      {data?.can_request===true&&<div className="space-y-2 rounded-md bg-muted/30 p-3"><label className="block">本次重点要求<textarea className={field} maxLength={10000} disabled={generating} value={instruction} onChange={e=>setInstruction(e.target.value)}/></label><Button type="button" size="sm" disabled={busy||generating||data.rollout!=="live"} onClick={()=>void generate({selection,expected_digest:prepared.digest,user_instruction:instruction})}>基于本次资料生成管理解释</Button></div>}
      {generating&&<p role="status">正在处理，可刷新原运行、查看预算与进度或停止。</p>}
      {rows(data?.items).map(v=><div className="flex flex-wrap items-center gap-2 rounded-md border p-2" key={text(v.run_id)}><span>{text(v.created_at)} · {states[text(v.status)]??text(v.status)}</span><Button type="button" size="sm" variant="outline" disabled={busy} onClick={()=>void act(()=>open(text(v.run_id)))}>查看解释／原请求接续</Button>{v.status==="running"&&<Button type="button" size="sm" variant="outline" disabled={busy} onClick={()=>void act(async()=>{await cancelAgentRun(text(v.run_id));await read();if(selected?.run_id===v.run_id)await open(text(v.run_id));})}>停止原运行</Button>}</div>)}
      {data?.next_before_id!=null&&<Button type="button" size="sm" variant="outline" disabled={busy} onClick={()=>void act(()=>read(text(data.next_before_id)))}>更早记录</Button>}
      {selected&&<div className="space-y-3 rounded-md border p-3"><AgentRunProgressPanel projectId={text(selected.project_id)} runId={text(selected.run_id)}/>
        <p>{selected.sources_current===true?"当前原资料与本次运行依据一致":"当前来源已有变化，以下为原运行分析；新办理请回原记录重核"}</p>
        {selected.error_code!=null&&<p>本次未完成：{text(selected.error_code)}</p>}
        {selected.assessment!=null&&<><p className="whitespace-pre-wrap">{text(assessment.coverage_limits)}</p>{rows(assessment.portfolio_observations).map((v,i)=><Statement key={i} value={v} refs={refs} sources={sources}/>)}{rows(assessment.projects).map(p=><article key={text(p.project_id)} className="space-y-3 border-l pl-3"><h4 className="font-medium">{projectName(p.project_id)}</h4><Statement value={obj(p.situation)} refs={refs} sources={sources}/>{rows(p.exceptions).length>0&&<p className="font-medium">关注事项</p>}{rows(p.exceptions).map((v,i)=><Statement key={i} value={v} refs={refs} sources={sources}/>)}{rows(p.human_next_steps).length>0&&<p className="font-medium">建议人工下一步</p>}{rows(p.human_next_steps).map((v,i)=><Statement key={i} value={v} refs={refs} sources={sources}/>)}{Array.isArray(p.missing)&&p.missing.length>0&&<p className="text-primary">待补：{p.missing.join("；")}</p>}</article>)}{Array.isArray(assessment.missing)&&assessment.missing.length>0&&<p className="text-primary">待补：{assessment.missing.join("；")}</p>}</>}
        <details><summary className="cursor-pointer">本次固定资料与读取限制</summary><div className="mt-2 space-y-2">{sources.map(s=><div key={text(s.reference_id)}><p>{text(s.label)}</p>{Array.isArray(s.omitted_fields)&&s.omitted_fields.length>0&&<p className="text-muted-foreground">未提供明细：{s.omitted_fields.join("；")}</p>}<a className="inline-flex min-h-11 items-center text-primary underline" href={text(s.href)}>打开当前原资料</a></div>)}</div></details>
        {selected.sources_current===true&&["running","degraded"].includes(text(selected.status))&&<Button type="button" size="sm" variant="outline" disabled={busy||generating||data?.rollout!=="live"} onClick={()=>void generate({selection:selected.selection,expected_digest:selected.source_digest,user_instruction:selected.user_instruction},text(selected.request_id))}>沿原请求接续（共享累计预算）</Button>}
      </div>}
    </div>
  </details>;
}
