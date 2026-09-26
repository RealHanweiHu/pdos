"use client";
import { useState } from "react";
import { PortfolioForecastHistory } from "@/components/portfolio/portfolio-forecast-history";
import { Button } from "@/components/ui/button";
import { caseLinkRequest } from "@/components/cases/case-requirements";
import { field, obj, rows, text, type Row } from "@/components/quality/fmea-sources";

const statusNames: Record<string, string> = {draft:"草稿",proposed:"已提交",approved:"已批准",active:"进行中",on_hold:"暂停",completed:"已完成",archived:"已归档"};
const nodeNames: Record<string, string> = {task:"任务",gate:"Gate",build:"试制批次",test_run:"测试轮次",certification:"认证",tooling:"工装轮次",milestone:"里程碑"};
const stateNames: Record<string, string> = {todo:"未开工",in_progress:"进行中",done:"已结束",blocked:"阻塞",skipped:"已跳过"};
function when(value:unknown) {return value ? new Date(text(value)).toLocaleString() : "未知";}
function count(value:unknown) {return value == null ? "未知" : text(value);}
function reasons(value:unknown) {return Array.isArray(value) ? value.map(String).join("；") : "";}
const floatNames:Record<string,string>={calculated:"已计算",unknown_schedule:"日期不完整",actual_constraint_conflict:"实际时间与约束冲突",resource_constrained_not_calculated:"资源约束预测尚未计算时差"};
function countdown(due:unknown,asOf:unknown) {
 if(!due||!asOf)return "承诺倒计时未知";
 const days=(new Date(text(due)).getTime()-new Date(text(asOf)).getTime())/86400000;
 return `${days>=0?"距承诺期限":"已超过承诺期限"} ${Math.abs(days).toFixed(1)} 自然日（按本次读取时点）`;
}
function Nodes({projectId}:{projectId:string}) {
 const [data,setData]=useState<Row|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState("");
 const [focus,setFocus]=useState("all"),[loaded,setLoaded]=useState("");
 async function load(more=false) {setBusy(true);setError("");try {
  const next=await caseLinkRequest<Row>("planning/portfolio-progress-nodes",{project_id:projectId,focus,offset:more?data?.next_offset??0:0,revision:more?data?.revision:null});
  setData(old=>more?{...next,items:[...rows(old?.items),...rows(next.items)]}:next);setLoaded(focus);
 } catch(e) {setError(e instanceof Error?e.message:"节点进度读取未完成");} finally {setBusy(false);}}
 const summary=obj(data?.summary);
 return <details className="mt-3 border-t pt-2"><summary className="cursor-pointer text-sm font-medium">展开关键节点、承诺与预测缺口</summary><div className="mt-3 space-y-3">
  <label className="block text-sm">节点范围<select className={field} value={focus} disabled={busy} onChange={e=>setFocus(e.target.value)}><option value="all">全部正式节点</option><option value="milestones">独立里程碑</option><option value="key_milestones">具名业务关键里程碑</option><option value="critical">当前已知关键路径节点</option><option value="gaps">未完成且预测覆盖待补</option><option value="critical_unknown">未完成且关键性未知</option></select></label>
  <Button type="button" size="sm" variant="outline" disabled={busy} onClick={()=>void load()}>{busy?"读取中…":"读取／刷新当前节点"}</Button>
  {error&&<p role="alert" className="text-sm text-destructive">{error}</p>}
  {data&&<><p className="text-xs text-muted-foreground">本次范围 {count(data.total)} 个当前正式节点，里程碑优先展示。读取于 {when(data.as_of)}，基线 v{count(summary.baseline_version)}。节点一项计一项，不按工时或个人产出加权。{loaded!==focus&&"范围已变更，请重新读取。"}</p>
   {summary.forecast_current!==true&&<p className="text-xs text-primary">以下预测日期为原保存版本；当前不可用于判断延期。{reasons(summary.missing)}</p>}
   {rows(data.items).map(n=><article className="space-y-2 rounded-md border p-3 text-xs" key={text(n.node_id)}>
    <p className="font-medium">{nodeNames[text(n.kind)]??text(n.kind)} · {text(n.title)} · {stateNames[text(n.status)]??text(n.status)}</p>
    {n.kind==="milestone"&&<p>业务重要性：{n.business_designation==null?"尚未标记":obj(n.business_designation).is_key===true?"具名关键里程碑":"具名普通里程碑"}{n.business_designation!=null&&` · v${text(obj(n.business_designation).version)} · ${text(obj(n.business_designation).actor_name)}`}</p>}
    {n.business_designation_source_current===false&&<p className="text-primary">标记时的节点名称、判据或责任安排已变化，请回原里程碑重核业务重要性。</p>}
    <p>{n.completed_with_evidence===true?"计入有依据完成节点":"尚未计入有依据完成节点"}</p>
    <div className="grid gap-2 sm:grid-cols-3"><p>正式基线<br/>{when(n.baseline_start)} → {when(n.baseline_finish)}</p><p>保存预测<br/>{when(n.saved_forecast_start)} → {when(n.saved_forecast_finish)}</p><p>实际记录<br/>{when(n.actual_start)} → {when(n.actual_finish)}</p></div>
    <p>{n.completed_with_evidence===true?"已完成，退出当前预测覆盖分母":n.forecast_covered===true?"当前预测覆盖有效":"当前预测覆盖待补"} · {n.completed_with_evidence===true?"实际已固定":n.critical===true?"当前关键路径节点":n.critical===false?"当前非关键路径节点":"当前关键性未知"}</p>
    <p className="text-muted-foreground">保存版本关键性：{n.saved_critical===true?"关键":n.saved_critical===false?"非关键":"未知"} · 总时差 {count(n.saved_total_float_minutes)} 分钟 · 工作时差 {count(n.saved_working_float_minutes)} 分钟。时差相对原预测完工时间，旧值保留供回查。</p>
    {n.commitment!=null?<div className="space-y-1 rounded border p-2"><p>最新人工承诺 v{count(obj(n.commitment).version)} · 最晚完成 {when(obj(n.commitment).end)}</p><p>确认人 {text(obj(n.commitment).approved_by_name)||text(obj(n.commitment).approved_by_user_id)} · 确认于 {when(obj(n.commitment).approved_at)}</p><p>{n.completed_with_evidence!==true&&countdown(obj(n.commitment).end,data.as_of)}</p>{n.commitment_delay_days!=null&&<p>当前预测相对承诺：{Number(n.commitment_delay_days).toFixed(1)} 自然日（正值延期）</p>}<p className="whitespace-pre-wrap text-muted-foreground">{text(obj(n.commitment).scope_label)} · {text(obj(n.commitment).reason)}</p><a className="inline-flex min-h-11 items-center text-primary underline" href={`/projects?project=${projectId}&tab=overview&forecast=${text(obj(n.commitment).forecast_record_id)}#schedule-forecasts`}>原承诺与采用的预测</a></div>:<p className="text-muted-foreground">尚无本节点具名承诺</p>}
    {reasons(n.coverage_missing)&&<p className="text-primary">预测覆盖：{reasons(n.coverage_missing)}</p>}
    {reasons(n.commitment_comparison_missing)&&<p className="text-primary">承诺比较：{reasons(n.commitment_comparison_missing)}</p>}
    {reasons(n.missing)&&<p className="text-primary">待补依据：{reasons(n.missing)}</p>}
    <p className="break-all text-muted-foreground">节点 {text(n.node_id)}{obj(n.evidence).actual_finish_event!=null?` · 完成事件 ${text(obj(n.evidence).actual_finish_event)}`:""}{obj(n.evidence).actual_start_event!=null?` · 开工事件 ${text(obj(n.evidence).actual_start_event)}`:""}{obj(n.evidence).actual_observation!=null?` · 实际观察 ${text(obj(obj(n.evidence).actual_observation).id)}，v${text(obj(obj(n.evidence).actual_observation).version)}`:""}</p>
    <a className="inline-flex min-h-11 items-center text-primary underline" href={text(n.href)}>打开原记录与实际依据</a>
    {obj(n.evidence).actual_finish_event!=null&&<a className="ml-3 inline-flex min-h-11 items-center text-primary underline" href={`/projects?project=${projectId}&tab=timeline&event_id=${text(obj(n.evidence).actual_finish_event)}`}>实际完成事件</a>}
   </article>)}
   {data.next_offset!=null&&<Button type="button" size="sm" variant="outline" disabled={busy||loaded!==focus} onClick={()=>void load(true)}>继续读取节点</Button>}
  </>}
 </div></details>;
}
export function PortfolioProgress() {
 const [data,setData]=useState<Row|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState("");
 const [search,setSearch]=useState(""),[status,setStatus]=useState(""),[order,setOrder]=useState("deviation"),[loaded,setLoaded]=useState("");
 const body={search,project_status:status||null,order},signature=JSON.stringify(body);
 async function load(more=false) {setBusy(true);setError("");try {
  const next=await caseLinkRequest<Row>("planning/portfolio-progress",{...body,offset:more?data?.next_offset??0:0,revision:more?data?.revision:null});
  setData(old=>more?{...next,items:[...rows(old?.items),...rows(next.items)]}:next);setLoaded(signature);
 }catch(e){setError(e instanceof Error?e.message:"项目进度读取未完成");}finally{setBusy(false);}}
 return <section className="mt-5 space-y-4 rounded-lg border bg-card p-4"><div><h2 className="font-semibold">全项目进度</h2><p className="mt-1 text-sm text-muted-foreground">按当前有权项目的正式计划与实际依据汇总，先对全部筛选结果排序，再分批展示。偏差为预测完工相对获批基线的自然日差，负值表示提前。</p></div>
 <form className="flex flex-wrap items-end gap-3" onSubmit={e=>{e.preventDefault();void load();}}><fieldset disabled={busy} className="flex flex-wrap gap-3">
  <label className="text-sm">项目查找<input className={field} value={search} maxLength={200} onChange={e=>setSearch(e.target.value)}/></label>
  <label className="text-sm">项目状态<select className={field} value={status} onChange={e=>setStatus(e.target.value)}><option value="">全部状态</option>{Object.entries(statusNames).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></label>
  <label className="text-sm">全局排序<select className={field} value={order} onChange={e=>setOrder(e.target.value)}><option value="deviation">当前预测延期最多</option><option value="blocked">正式节点阻塞最多</option><option value="conditions">未闭 Gate 条件最多</option><option value="coverage">预测覆盖待补最多</option><option value="critical">已知关键路径节点最多</option><option value="code">项目编号</option></select></label>
 </fieldset><Button type="submit" size="sm" disabled={busy}>{busy?"读取中…":"读取／刷新进度"}</Button></form>
 {error&&<p role="alert" className="text-sm text-destructive">{error}</p>}
 {data&&<><p className="text-xs text-muted-foreground">本次筛选共 {count(data.total)} 个项目，读取于 {when(data.as_of)}。{data.forecast_max_age_hours==null?"尚无有效账龄政策；仅核对预测来源一致性，请结合计算时间阅读。":`预测账龄沿当前健康政策，最多 ${text(data.forecast_max_age_hours)} 小时。`}{loaded!==signature&&"筛选已变化，请重新读取。"} 缺少可比日期的项目列在偏差排序末尾。</p>
 <div className="space-y-1 rounded-md border p-3 text-xs"><p>全部筛选项目：已知未完成节点 {count(obj(data.coverage_summary).known_unfinished_count)} · 当前预测覆盖 {count(obj(data.coverage_summary).known_covered_count)} · {obj(data.coverage_summary).coverage_percent==null?"全范围覆盖率不可评估":`全范围覆盖率 ${Number(obj(data.coverage_summary).coverage_percent).toFixed(1)}%`}</p><p>已知关键路径节点 {count(obj(data.coverage_summary).known_critical_count)} · 关键性未知 {count(obj(data.coverage_summary).critical_unknown_count)} · 缺正式计划依据的项目 {count(obj(data.coverage_summary).projects_without_formal_basis)}</p><p className="text-muted-foreground">以上为全部筛选范围，非本页小计。缺正式计划的项目无法确定节点数量，保留缺口，不按零节点纳入覆盖率。</p></div>
 <p className="text-xs text-muted-foreground">完成比例＝具有实际完成依据且当前状态完成的节点数÷全部当前正式节点数；跳过、缺依据均保留在分母。它不代表工时完成率或个人绩效。</p>
 {rows(data.items).length===0&&<p className="text-sm">本次筛选没有可见项目。</p>}
 <div className="space-y-3">{rows(data.items).map(p=><article key={text(p.project_id)} className="rounded-md border p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs text-muted-foreground">{text(p.code)} · {statusNames[text(p.project_status)]??text(p.project_status)}</p><h3 className="font-medium">{text(p.name)}</h3></div><p className={p.delay_days!=null&&Number(p.delay_days)>0?"text-sm text-destructive":"text-sm text-muted-foreground"}>当前完工偏差：{p.delay_days==null?"不可评估":`${Number(p.delay_days).toFixed(1)} 天`}</p></div>
 <div className="mt-3 grid gap-3 text-xs sm:grid-cols-3"><p>获批基线 v{count(p.baseline_version)}<br/>{when(p.baseline_finish)}</p><p>保存预测 v{count(p.forecast_version)}<br/>{when(p.forecast_finish)}<br/>计算于 {when(p.forecast_as_of)}</p><p>有依据完成 {count(p.completed_count)} / {count(p.node_count)}<br/>{p.completion_percent==null?"比例未知":`${Number(p.completion_percent).toFixed(1)}%`} · 阻塞 {count(p.blocked_count)} · 缺依据 {count(p.unknown_count)}<br/>未闭 Gate 条件 {count(p.open_gate_conditions)}</p></div>
 <div className="mt-3 space-y-1 rounded-md bg-muted/40 p-3 text-xs"><p>未完成正式节点：当前可用预测覆盖 {count(p.covered_count)} / {count(p.unfinished_count)} · {p.coverage_percent==null?"覆盖率不可评估":`${Number(p.coverage_percent).toFixed(1)}%`} · 待补 {count(p.forecast_gap_count)}</p><p>未完成业务关键里程碑：标记依据一致且当前有预测覆盖 {count(p.key_milestone_covered_count)} / {count(p.key_milestone_unfinished_count)} · 另有未标记里程碑 {count(p.unclassified_milestone_count)} · 标记待重核 {count(p.designation_recheck_count)}</p><p>当前已知关键路径节点 {count(p.critical_count)} · 关键性未知 {count(p.critical_unknown_count)} · 原时差计算：{floatNames[text(p.float_status)]??"未知"}</p><p className="text-muted-foreground">覆盖须来源一致、预测日期完整且符合有效账龄政策；已完成节点退出分母。关键路径不等同于业务关键里程碑，本次覆盖不代表持续覆盖。</p>{reasons(p.coverage_missing)&&<p className="text-primary">{reasons(p.coverage_missing)}</p>}</div>
 {reasons(p.missing)&&<p className="mt-2 text-xs text-primary">{reasons(p.missing)}</p>}
 <a className="mt-2 inline-flex min-h-11 items-center text-sm text-primary underline" href={text(p.href)}>打开项目正式计划与预测</a>
 {p.forecast_href!=null&&<a className="ml-4 inline-flex min-h-11 items-center text-sm text-primary underline" href={text(p.forecast_href)}>回查此保存预测版本</a>}
 <Nodes key={`${text(p.project_id)}:${text(p.evidence_digest)}:${text(p.forecast_id)}`} projectId={text(p.project_id)}/>
 <PortfolioForecastHistory projectId={text(p.project_id)}/>
 </article>)}</div>
 {data.next_offset!=null&&<Button type="button" variant="outline" size="sm" disabled={busy||loaded!==signature} onClick={()=>void load(true)}>继续读取全局排序结果</Button>}
 </>}
 </section>;
}
