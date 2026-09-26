"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { obj, rows, text, field, type Row } from "@/components/quality/fmea-sources";
import { request } from "./product-work-api";

type Mapping = { item_key: string; metric_index: number; metric_name: string; comparability: "same_conditions" | "not_comparable" | "unknown"; basis: string };

function Result({ value }: { value: Row }) {
  return <div className="space-y-2"><p>{text(value.formula)}</p><p className="text-xs text-muted-foreground">{text(value.rounding)}</p><p className="text-primary">{text(value.interpretation)}</p><p>已计算 {text(value.calculated_count)} 项 · 未知 {text(value.unknown_count)} 项</p>
    {rows(value.items).map(item => <div key={text(item.item_key)} className="space-y-1 rounded-md border p-3"><h6 className="font-medium">{text(obj(item.specification).title) || text(item.item_key)} ← {text(obj(item.metric).name) || "原指标缺失"}</h6><p>原值：{text(obj(item.metric).value)} {text(obj(item.metric).unit)} · 原目标：{text(obj(item.specification).target_value) || "未知"} {text(obj(item.specification).unit)}</p><p>差额：{item.delta == null ? "未知" : text(item.delta)} · 变化率：{item.relative_delta_percent == null ? "未知" : text(item.relative_delta_percent) + "%"}</p>{item.relative_unknown_reason != null && <p>{text(item.relative_unknown_reason)}</p>}{Array.isArray(item.reasons) && item.reasons.map((reason,index)=><p key={index} className="text-primary">{String(reason)}</p>)}<p className="text-xs text-muted-foreground">原指标登记判定：{({pass:"通过",fail:"失败",info:"仅记录"} as Record<string,string>)[text(obj(item.metric).verdict)] ?? "未登记"}；本次计算不改写该判定。</p></div>)}
  </div>;
}

export function ProductMetricCalculations({ base, definitionId, projectId, testRunId }: { base: string; definitionId: string; projectId: string; testRunId: string }) {
  const [data, setData] = useState<Row | null>(null), [preview, setPreview] = useState<Row | null>(null), [replay, setReplay] = useState<Row | null>(null);
  const [mappings, setMappings] = useState<Mapping[]>([]), [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const attempt = useRef<{ key: string; id: string } | null>(null);
  const scope = { definition_id: definitionId, project_id: projectId, test_run_id: testRunId };
  const source = obj(data?.source), actual = obj(source.source), run = obj(actual.record), specs = rows(obj(obj(source.definition).content).items), metrics = rows(run.metrics);
  async function act(work: () => Promise<void>) { setBusy(true); setError(""); try { await work(); } catch (failure) { setError(failure instanceof Error ? failure.message : "指标计算暂不可用"); } finally { setBusy(false); } }
  async function load(before?: number) {
    const value = await request<Row>(base + "/result-metric-context", "POST", { ...scope, before_version: before ?? null });
    if (data && obj(data.source).digest !== obj(value.source).digest) { setMappings(old => old.map(v => ({...v, comparability:"unknown"}))); setNotice("原资料已有变化，指标对应和条件需重新核对。"); }
    setPreview(null); setData(old => before ? { ...value, items: [...rows(old?.items), ...rows(value.items)] } : value);
  }
  function change(index: number, value: Partial<Mapping>) { setMappings(old => old.map((m, i) => i === index ? { ...m, ...value } : m)); setPreview(null); }
  function draft() { return { ...scope, expected_source_digest: source.digest, mappings, reason }; }
  async function save() {
    const body = { ...draft(), expected_version: data?.version, expected_preview_digest: preview?.digest };
    const key = JSON.stringify(body); if (attempt.current?.key !== key) attempt.current = { key, id: crypto.randomUUID() };
    await request(base + "/result-metric-save", "POST", { ...body, request_id: attempt.current.id }); attempt.current = null;
    await load(); setNotice("计算口径、原输入和结果已按新版本保存，历史结果保持不变。");
  }
  async function reuse(value: Row) {
    await load(); setMappings(rows(obj(value.configuration).mappings).map(v => ({item_key:text(v.item_key), metric_index:Number(v.metric_index), metric_name:text(v.metric_name), comparability:"unknown", basis:text(v.basis)}))); setReason(text(value.reason)); setNotice("已恢复原对应关系并读取当前资料，请重新核对条件后预览，不自动沿用旧的可比判断。");
  }
  return <details className="space-y-3 rounded-md border p-3 text-sm" onToggle={event => { if (event.currentTarget.open && !data && !busy) void act(() => load()); }}>
    <summary className="cursor-pointer font-medium">实测指标与原目标 · 版本计算与回放</summary>
    <p className="text-muted-foreground">明确指定原规格与本次实际指标，核对样机、条件和方法后计算差额。旧值与原判定保留，未知项不补零。</p>
    {error && <p role="alert" className="text-destructive">{error}</p>}{notice && <p role="status">{notice}</p>}
    <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(() => load())}>读取当前资料与历史</Button>
    {data && <>
      <details><summary className="cursor-pointer">核对原规格、实际指标、样机配置和条件</summary><pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words text-xs">{JSON.stringify({ items:specs, metrics, conditions:run.conditions, method:obj(actual.test_case).method, criterion:obj(actual.test_case).acceptance_criteria, configuration:actual.sample_configuration, evidence:actual.evidence, inherited:actual.inherited_specifications }, null, 2)}</pre></details>
      <form className="space-y-3" onSubmit={event => { event.preventDefault(); void act(async () => { setPreview(await request<Row>(base + "/result-metric-preview", "POST", draft())); }); }}><fieldset className="space-y-3" disabled={busy}>
        {mappings.map((mapping,index)=><section key={index} className="space-y-2 rounded-md border p-3">
          <label className="block">原定义规格<select className={field} required value={mapping.item_key} onChange={event=>change(index,{item_key:event.target.value})}><option value="">请选择实际条目</option>{specs.map(item=><option key={text(item.item_key)} value={text(item.item_key)}>{text(item.title)} · {text(item.target_value) || text(item.target_text) || "目标未知"} {text(item.unit)}</option>)}</select></label>
          <label className="block">本次实际指标<select className={field} value={mapping.metric_index} onChange={event=>{const i=Number(event.target.value);change(index,{metric_index:i,metric_name:text(metrics[i]?.name)});}}>{metrics.map((metric,i)=><option key={i} value={i}>{i+1}. {text(metric.name)}：{text(metric.value)} {text(metric.unit)}</option>)}</select></label>
          <label className="block">条件、方法和适用范围<select className={field} value={mapping.comparability} onChange={event=>change(index,{comparability:event.target.value as Mapping["comparability"]})}><option value="unknown">尚待核对</option><option value="same_conditions">已核对为同口径</option><option value="not_comparable">本次不可比</option></select></label>
          <label className="block">对应及可比判断依据<textarea className={field} required maxLength={2048} value={mapping.basis} onChange={event=>change(index,{basis:event.target.value})}/></label><Button type="button" size="sm" variant="ghost" onClick={()=>{setMappings(old=>old.filter((_,i)=>i!==index));setPreview(null);}}>移除此对应</Button>
        </section>)}
        <Button type="button" size="sm" variant="outline" disabled={!metrics.length || !specs.length || mappings.length>=20} onClick={()=>{setMappings(old=>[...old,{item_key:"",metric_index:0,metric_name:text(metrics[0]?.name),comparability:"unknown",basis:""}]);setPreview(null);}}>添加指标对应</Button>
        <label className="block">本次计算或重算原因<textarea className={field} required maxLength={2048} value={reason} onChange={event=>{setReason(event.target.value);setPreview(null);}}/></label><Button disabled={!mappings.length}>预览原值、差额与未知项</Button>
      </fieldset></form>
      {preview && <section className="space-y-3 rounded-md bg-muted/30 p-3"><h6 className="font-medium">计算预览</h6><Result value={obj(preview.result)}/>{data.can_save===true && <form onSubmit={event=>{event.preventDefault();void act(save);}} className="space-y-3"><label className="flex items-start gap-2"><input key={text(preview.digest)} type="checkbox" required disabled={busy}/>已核对原值、样机/测试条件、人工对应和未知项；本结果只作差额分析。</label><Button disabled={busy}>保存为新的计算版本</Button></form>}</section>}
      {rows(data.items).map(value=><article key={text(value.id)} className="space-y-3 border-t pt-3"><h6 className="font-medium">计算 v{text(value.version)} · {new Date(text(value.created_at)).toLocaleString()}</h6><p className="whitespace-pre-wrap">{text(value.reason)}</p>{value.sources_current!==true&&<p className="text-primary">当前资料已变化，以下为固定原输入计算结果。</p>}<Result value={obj(value.result)}/><div className="flex flex-wrap gap-2"><Button type="button" size="sm" variant="outline" disabled={busy} onClick={()=>void act(async()=>{setReplay(await request<Row>(base + "/result-metric-replay","POST",{calculation_id:value.id}));})}>按原输入与公式回放</Button><Button type="button" size="sm" variant="outline" disabled={busy} onClick={()=>void act(()=>reuse(value))}>沿原对应读取当前资料</Button></div><details><summary className="cursor-pointer">当时完整口径、输入与记录人</summary><pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words text-xs">{JSON.stringify({configuration:value.configuration,input:value.source_snapshot,actor:value.actor_user_id},null,2)}</pre></details></article>)}
      {data.next_before_version!=null&&<Button type="button" size="sm" variant="outline" disabled={busy} onClick={()=>void act(()=>load(Number(data.next_before_version)))}>更早计算版本</Button>}
      {replay&&<section className="space-y-3 rounded-md border p-3"><h6 className="font-medium">原计算 v{text(obj(replay.record).version)} 回放</h6><p>{replay.matches_saved===true?"与当时保存结果一致。":"与原结果不一致，需核对计算版本；原记录保持不变。"}</p>{replay.sources_current!==true&&<p className="text-primary">当前来源已有变化；本回放使用保存的原输入。</p>}<Result value={obj(replay.replayed_result)}/><Button type="button" size="sm" variant="ghost" onClick={()=>setReplay(null)}>收起回放</Button></section>}
    </>}
  </details>;
}
