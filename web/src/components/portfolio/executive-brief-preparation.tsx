"use client";
import { useState } from "react";
import { ExecutiveBriefRuns } from "./executive-brief-runs";
import type { Project } from "@/components/projects/project-types";
import { Button } from "@/components/ui/button";
import { caseLinkRequest } from "@/components/cases/case-requirements";
import { field, obj, rows, text, type Row } from "@/components/quality/fmea-sources";

const when=(v:unknown)=>v?new Date(text(v)).toLocaleString():"未知";
const count=(v:unknown)=>v==null?"未知":text(v);
const reasons=(v:unknown)=>Array.isArray(v)?v.map(String).join("；"):"";
const healthNames:Record<string,string>={clear:"正常范围",attention:"需关注",alert:"异常",unknown:"不可评估"};

export function ExecutiveBriefPreparation({projects}:{projects:Project[]}) {
  const [selected,setSelected]=useState<string[]>([]),[search,setSearch]=useState("");
  const [data,setData]=useState<Row|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState("");
  const [loaded,setLoaded]=useState("");
  const signature=JSON.stringify([...selected].sort());
  async function load(){setBusy(true);setError("");try{
    const result=await caseLinkRequest<Row>("planning/executive-brief-context",{project_ids:[...selected].sort()});
    setData(result);setLoaded(signature);
  }catch(e){setError(e instanceof Error?e.message:"管理摘要资料读取未完成");}finally{setBusy(false);}}
  const refs=rows(obj(data?.model_context).references);
  const queueSummary=obj(refs.find(r=>r.reference_id==="executive:queue-summary")?.fields);
  const queue:Row[]=refs.filter(r=>text(r.reference_id).startsWith("executive:queue:")).map(r=>({...obj(r.fields),href:r.href}));
  const health=refs.filter(r=>text(r.reference_id).endsWith(":health"));
  return <section className="mt-5 space-y-4 rounded-lg border bg-card p-4">
    <div><h2 className="font-semibold">管理摘要资料</h2><p className="mt-1 text-sm text-muted-foreground">选择本次关注的项目，把六维健康、正式进度和待决事项放在一起核对。这里只汇集当前资料，原审批和执行仍在原记录办理。</p></div>
    <form className="space-y-3" onSubmit={e=>{e.preventDefault();void load();}}>
      <fieldset disabled={busy} className="space-y-3"><label className="block text-sm">查找可选项目<input className={field} value={search} maxLength={200} onChange={e=>setSearch(e.target.value)}/></label>
      <div className="flex max-h-56 flex-wrap gap-3 overflow-y-auto">{projects.filter(p=>`${p.code} ${p.name}`.toLowerCase().includes(search.toLowerCase())).map(p=><label className="flex items-center gap-2 text-sm" key={p.id}><input type="checkbox" checked={selected.includes(p.id)} disabled={!selected.includes(p.id)&&selected.length>=10} onChange={e=>setSelected(old=>e.target.checked?[...old,p.id]:old.filter(v=>v!==p.id))}/>{p.code} · {p.name}</label>)}</div>
      <p className="text-xs text-muted-foreground">已选 {selected.length} / 10 个项目。查找不会清除已选项目。</p>
      {selected.length>0&&<div className="flex flex-wrap gap-2">{selected.map(id=><Button key={id} type="button" size="sm" variant="outline" onClick={()=>setSelected(old=>old.filter(v=>v!==id))}>移除 {projects.find(p=>p.id===id)?.code??id}</Button>)}</div>}
      <Button type="submit" size="sm" disabled={!selected.length}>{busy?"读取中…":"读取／刷新管理资料"}</Button></fieldset>
    </form>
    {error&&<p role="alert" className="text-sm text-destructive">{error}</p>}
    {data&&<><p className="text-xs text-muted-foreground">读取于 {when(data.as_of)}。{loaded!==signature&&"选择已改变，以下仍为上次范围，请重新读取。"}</p>
      <details className="rounded-md border p-3" open><summary className="cursor-pointer text-sm font-medium">本次读取范围与缺口</summary><ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-muted-foreground">{Array.isArray(obj(data.model_context).coverage_limits)&&(obj(data.model_context).coverage_limits as unknown[]).map((v,i)=><li key={i}>{String(v)}</li>)}</ul></details>
      {health.map(ref=>{const h=obj(ref.fields),project=text(h.project_id);const progress=obj(refs.find(r=>r.reference_id===`executive:project:${project}:progress`)?.fields);const nodes=obj(refs.find(r=>r.reference_id===`executive:project:${project}:nodes`)?.fields);return <article key={project} className="space-y-3 rounded-md border p-3">
        <h3 className="text-sm font-medium">{text(h.project_code)} · {text(h.project_name)}</h3>
        <p className="text-xs">综合健康 {h.score==null?"不可评估":Number(h.score).toFixed(1)} · 异常维度 {count(h.alert_dimensions)} · 缺数维度 {count(h.unknown_dimensions)}</p>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">{rows(h.dimensions).map(d=><div key={text(d.dimension)} className="space-y-1 rounded-md bg-muted/40 p-2 text-xs"><p className="font-medium">{text(d.label)} · {healthNames[text(d.status)]??"未知"}</p><p>{count(d.value)} {text(d.unit)} · 原来源 {count(d.source_count)} 项</p><p className="text-muted-foreground">{text(d.scope)}</p>{reasons(d.missing)&&<p className="text-primary">{reasons(d.missing)}</p>}</div>)}</div>
        <div className="grid gap-2 text-xs sm:grid-cols-3"><p>基线完工 {when(progress.baseline_finish)}<br/>保存预测 {when(progress.forecast_finish)}<br/>当前偏差 {progress.delay_days==null?"不可评估":`${Number(progress.delay_days).toFixed(1)} 自然日`}</p><p>有依据完成 {count(progress.completed_count)} / {count(progress.node_count)}<br/>阻塞 {count(progress.blocked_count)} · 缺依据 {count(progress.unknown_count)}</p><p>未完成节点预测覆盖 {count(progress.covered_count)} / {count(progress.unfinished_count)}<br/>关键业务里程碑当前覆盖 {count(progress.key_milestone_covered_count)} / {count(progress.key_milestone_unfinished_count)}</p></div>
        {reasons(progress.coverage_missing)&&<p className="text-xs text-primary">{reasons(progress.coverage_missing)}</p>}
        <details><summary className="cursor-pointer text-xs">关注节点 {count(nodes.included_count)} / {count(nodes.unfinished_total)} · 未展开 {count(nodes.omitted_count)}</summary><p className="my-2 text-xs text-muted-foreground">{text(nodes.ordering)}</p><div className="space-y-2">{rows(nodes.items).map(n=><div key={text(n.node_id)} className="rounded border p-2 text-xs"><p className="font-medium">{text(n.title)}</p><p>基线 {when(n.baseline_finish)} · 保存预测 {when(n.saved_forecast_finish)} · 人工承诺 {when(obj(n.commitment).end)}</p>{reasons(n.coverage_missing)&&<p className="text-primary">{reasons(n.coverage_missing)}</p>}<a className="inline-flex min-h-11 items-center text-primary underline" href={text(n.href)}>原节点与依据</a></div>)}</div></details>
        <a className="inline-flex min-h-11 items-center text-xs text-primary underline" href={text(ref.href)}>打开项目原始资料</a>
      </article>;})}
      <div className="space-y-3 rounded-md border p-3"><h3 className="text-sm font-medium">所选项目待决与例外</h3><p className="text-xs">全范围共 {count(queueSummary.total)} 项，本次展开 {count(queueSummary.included_count)} 项，另有 {count(queueSummary.omitted_count)} 项未展开。{text(queueSummary.ordering)}</p>
        <div className="flex flex-wrap gap-2 text-xs">{Object.entries(obj(queueSummary.counts)).map(([key,value])=><span className="rounded border px-2 py-1" key={key}>{text(obj(queueSummary.labels)[key])} {count(value)}</span>)}</div>
        {reasons(queueSummary.unavailable)&&<p className="text-xs text-primary">读取缺口：{reasons(queueSummary.unavailable)}</p>}
        <p className="text-xs text-muted-foreground">{text(queueSummary.timing_basis)}</p>
        {queue.map(v=><article key={`${text(v.kind)}:${text(v.id)}`} className="space-y-1 border-t pt-2 text-xs"><p className="font-medium">{text(v.project_code)} · {text(v.label)} · {text(v.title)}</p><p>当前负责人 {text(v.owner_name)||"待明确"} · 原等待起点 {when(v.waiting_since)} · 期限 {text(v.due_date)||"未知"}{v.overdue===true?" · 已过期":""}</p>{v.note!=null&&<p className="whitespace-pre-wrap text-muted-foreground">{text(v.note)}</p>}<a className="inline-flex min-h-11 items-center text-primary underline" href={text(v.href)}>沿原记录办理</a></article>)}
      </div>
      {loaded===signature&&<ExecutiveBriefRuns key={text(data.digest)} prepared={data}/>}
    </>}
  </section>;
}
