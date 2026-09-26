"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { obj, rows, text, field, type Row } from "@/components/quality/fmea-sources";
import { request } from "./product-work-api";

const targets = { opportunity: "机会与原方案", strategy: "关联产品策略", definition: "关联产品定义" };
const verdicts: Record<string, string> = { adopt_for_followup: "采用为后续调整依据", reject_application: "不采用到本次字段", needs_evidence: "要求补充证据", withdrawn: "撤回原反馈" };
const results: Record<string, string> = { supported: "支持原假设", refuted: "证伪原假设", inconclusive: "结果不确定" };
const planFields = { hypothesis: "原假设", method: "原方法", sample_basis: "原样本依据", success_criterion: "原支持判据", falsification_criterion: "原证伪判据" };

export function ExperimentFeedbackInbox({ base, targetKind, targetId }: { base: string; targetKind: keyof typeof targets; targetId: string }) {
  const [data, setData] = useState<Row | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  async function read(before?: string) {
    setBusy(true); setError("");
    try {
      const value = await request<Row>(`${base}/experiment-feedback-target`, "POST", { target_kind: targetKind, target_id: targetId, before_id: before ?? null });
      setData(old => before ? { ...value, items: [...rows(old?.items), ...rows(value.items)], unavailable_count: Number(old?.unavailable_count ?? 0) + Number(value.unavailable_count ?? 0) } : value);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "实验反馈暂不可用"); }
    finally { setBusy(false); }
  }
  return <details className="space-y-3 rounded-md border p-3 text-sm" onToggle={event => { if (event.currentTarget.open && !data && !busy) void read(); }}>
    <summary className="cursor-pointer font-medium">此版本收到的实验反馈</summary>
    <p className="text-muted-foreground">保留各实验对本版本字段的具名判断。采用意见供后续修订使用，正式内容按原流程办理。</p>
    <Button size="sm" variant="outline" disabled={busy} onClick={() => void read()}>刷新反馈</Button>
    {error && <p role="alert" className="text-destructive">{error}</p>}
    {busy && <p role="status">正在读取…</p>}
    {data && rows(data.items).length === 0 && <p>暂无可读取的实验反馈。</p>}
    {Number(data?.unavailable_count ?? 0) > 0 && <p className="text-primary">部分历史反馈的来源或关联范围已不可读取，未展示其内容。</p>}
    {rows(data?.items).map(value => {
      const actual = obj(obj(value.source_snapshot).experiment);
      return <article key={text(value.id)} className="space-y-2 border-t pt-3">
        <a className="inline-flex min-h-11 items-center underline" href={`/product-work?space=${base.split("/")[1]}&tab=experiments#experiment-${text(value.experiment_id)}`}>原实验：{text(actual.hypothesis)} · {results[text(actual.result)] ?? "未知"}</a>
        <p>反馈 v{text(value.version)} · {verdicts[text(value.verdict)]} · {value.is_latest ? "该实验最新回应" : "历史回应"}</p>
        <p className="text-xs text-muted-foreground">{text(value.actor_name)} · {new Date(text(value.created_at)).toLocaleString()}</p>
        <p className="whitespace-pre-wrap">{text(value.reason)}</p><p className="whitespace-pre-wrap">后续安排：{text(value.proposed_change)}</p><p className="whitespace-pre-wrap">适用限制：{text(value.limitations)}</p>
        {value.sources_current !== true && <p className="text-primary">原实验、证据或目标已有变化，需重新核对。</p>}
        <details><summary className="cursor-pointer">当时所选字段、计划与实际结果</summary><pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words text-xs">{JSON.stringify({ selected_fields: value.selected_fields, source: value.source_snapshot }, null, 2)}</pre></details>
      </article>;
    })}
    {data?.next_before_id != null && <Button size="sm" variant="outline" disabled={busy} onClick={() => void read(text(data.next_before_id))}>更多历史反馈</Button>}
  </details>;
}

export function ExperimentFeedback({ base, experimentId }: { base: string; experimentId: string }) {
  const [kind, setKind] = useState<keyof typeof targets>("opportunity"), [search, setSearch] = useState(""), [loadedSearch, setLoadedSearch] = useState("");
  const [options, setOptions] = useState<Row | null>(null), [target, setTarget] = useState(""), [data, setData] = useState<Row | null>(null);
  const [paths, setPaths] = useState<string[]>([]), [verdict, setVerdict] = useState("needs_evidence"), [reason, setReason] = useState(""), [change, setChange] = useState(""), [limits, setLimits] = useState("");
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const attempt = useRef<{ key: string; id: string } | null>(null);
  async function loadOptions(before?: string) { const query = before ? loadedSearch : search; const value = await request<Row>(`${base}/experiment-feedback-options`, "POST", { experiment_id: experimentId, target_kind: kind, search: query, before_id: before ?? null }); setOptions(old => before ? { ...value, items: [...rows(old?.items), ...rows(value.items)] } : value); setLoadedSearch(query); }
  async function read(before?: number) { const value = await request<Row>(`${base}/experiment-feedback`, "POST", { experiment_id: experimentId, target_kind: kind, target_id: target, before_version: before ?? null }); setData(old => before ? { ...value, items: [...rows(old?.items), ...rows(value.items)] } : value); }
  async function act(work: () => Promise<void>) { setBusy(true); setError(""); try { await work(); } catch (failure) { setError(failure instanceof Error ? failure.message : "实验反馈暂不可用"); } finally { setBusy(false); } }
  const source = obj(data?.source), plan = obj(obj(source.approved_plan).plan_snapshot), actual = obj(source.experiment);
  async function save() {
    const body = { experiment_id: experimentId, target_kind: kind, target_id: target, expected_version: data?.version, expected_digest: source.digest, field_paths: paths, verdict, reason, proposed_change: change, limitations: limits };
    const key = JSON.stringify(body); if (attempt.current?.key !== key) attempt.current = { key, id: crypto.randomUUID() };
    await request(`${base}/experiment-feedback-save`, "POST", { ...body, request_id: attempt.current.id });
    attempt.current = null; setNotice("具名反馈已保存。目标记录和发布版本未改写，调整须继续走原办理入口。"); setReason(""); setChange(""); setLimits(""); await read();
  }
  const targetHref = `/product-work?space=${base.split("/")[1]}&tab=${kind === "opportunity" ? "opportunities" : kind === "strategy" ? "strategies" : "definitions"}#${kind}-${target}`;
  return <details className="space-y-3 rounded-md border p-3" onToggle={event => { if (event.currentTarget.open && !options && !busy) void act(() => loadOptions()); }}><summary className="cursor-pointer font-medium">反馈到原机会、策略与定义假设</summary><div className="space-y-3 text-sm"><p>按原机会系列和方案查找实际关联记录，逐项对照批准计划与真实结果。支持、失败和不确定结果都保留；采用反馈不等于批准目标修订或证明因果。</p>{error && <p role="alert" className="text-destructive">{error}</p>}{notice && <p role="status">{notice}</p>}
    <fieldset disabled={busy} className="space-y-2"><label className="block">反馈对象类型<select className={field} value={kind} onChange={event => { setKind(event.target.value as keyof typeof targets); setOptions(null); setTarget(""); setData(null); setPaths([]); setNotice(""); }} >{Object.entries(targets).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label><label className="block">名称搜索<input className={field} maxLength={128} value={search} onChange={event => setSearch(event.target.value)}/></label><Button size="sm" variant="outline" onClick={() => void act(() => loadOptions())}>查找关联版本</Button><label className="block">明确选择一个实际版本<select className={field} value={target} onChange={event => { setTarget(event.target.value); setData(null); setPaths([]); setNotice(""); }}><option value="">请选择</option>{rows(options?.items).map(item => <option key={text(item.id)} value={text(item.id)}>{text(item.title)} · v{text(item.version)} · {text(item.state)}</option>)}</select></label>{options && rows(options.items).length === 0 && <p className="text-muted-foreground">当前没有匹配且有权读取的关联版本，不创建虚构关联。</p>}{options?.next_before_id != null && <Button size="sm" variant="outline" onClick={() => void act(() => loadOptions(text(options.next_before_id)))}>更多关联版本</Button>}<Button disabled={!target} onClick={() => void act(() => read())}>核对原计划、实际结果与目标字段</Button></fieldset>
    {data && <><a href={targetHref} className="inline-flex min-h-11 items-center underline">打开目标原业务记录</a><div className="grid gap-3 md:grid-cols-2"><section className="space-y-1 rounded-md bg-muted/30 p-3"><h6 className="font-medium">批准时的计划</h6>{Object.entries(planFields).map(([key, label]) => <p key={key} className="whitespace-pre-wrap">{label}：{text(plan[key])}</p>)}<p className="text-xs text-muted-foreground">批准时点：{text(obj(source.approved_plan).approved_at)}</p></section><section className="space-y-1 rounded-md bg-muted/30 p-3"><h6 className="font-medium">实际结果：{results[text(actual.result)] ?? "未知"}</h6><p className="whitespace-pre-wrap">{text(actual.result_explanation)}</p><p>结束时点：{text(actual.concluded_at)}</p><p>实际结果证据 {rows(actual.result_evidence).length} 份</p><p className="text-xs text-muted-foreground">{text(source.interpretation)}</p></section></div>{Array.isArray(source.source_warnings) && source.source_warnings.map((warning, index) => <p key={index} className="text-primary">{String(warning)}</p>)}<details><summary className="cursor-pointer">原批准、结果证据与目标全文</summary><pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words text-xs">{JSON.stringify({ approved: source.approved_plan, actual, target: source.target }, null, 2)}</pre></details>
      {data.can_respond === true && <form className="space-y-3 rounded-md border p-3" onSubmit={event => { event.preventDefault(); void act(save); }}><fieldset disabled={busy} className="space-y-3"><h6 className="font-medium">具名回应目标字段</h6><p className="text-xs text-muted-foreground">一次选择最多 20 项，原字段值与所在版本一起保存。</p><div className="max-h-80 space-y-2 overflow-auto">{rows(source.fields).map(value => <label key={text(value.path)} className="block rounded-md border p-2"><span className="flex gap-2"><input type="checkbox" checked={paths.includes(text(value.path))} disabled={!paths.includes(text(value.path)) && paths.length >= 20} onChange={event => setPaths(old => event.target.checked ? [...old, text(value.path)] : old.filter(v => v !== value.path))}/><span className="break-all text-xs">{text(value.path)}</span></span><pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words text-xs">{JSON.stringify(value.value, null, 2)}</pre></label>)}</div><label className="block">本次回应<select className={field} value={verdict} onChange={event => setVerdict(event.target.value)}>{Object.entries(verdicts).filter(([key]) => key !== "withdrawn" || Number(data.version) > 0).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label><label className="block">实验结果对所选字段说明了什么<textarea required className={field} maxLength={2048} value={reason} onChange={event => setReason(event.target.value)}/></label><label className="block">建议调整、保留或补证安排<textarea required className={field} maxLength={2048} value={change} onChange={event => setChange(event.target.value)}/></label><label className="block">样本、方法、时间和适用范围限制<textarea required className={field} maxLength={2048} value={limits} onChange={event => setLimits(event.target.value)}/></label><label className="flex items-start gap-2"><input key={text(source.digest)} type="checkbox" required/>已核对原计划与实际证据，未将相关性当作已证明因果，未选字段保持未回应。</label><Button disabled={!paths.length}>保存具名反馈</Button></fieldset></form>}
      {rows(data.items).map(value => <article className="space-y-2 border-t pt-3" key={text(value.id)}><h6 className="font-medium">反馈 v{text(value.version)} · {verdicts[text(value.verdict)]} · {value.version === data.version ? "最新回应" : "历史回应"}</h6><p className="text-xs text-muted-foreground">{text(value.actor_name)} · {new Date(text(value.created_at)).toLocaleString()}</p><p className="whitespace-pre-wrap">{text(value.reason)}</p><p className="whitespace-pre-wrap">后续安排：{text(value.proposed_change)}</p><p className="whitespace-pre-wrap">限制：{text(value.limitations)}</p>{value.sources_current !== true && <p className="text-primary">当前实验、证据或目标内容已变化，以下保留原时点判断，需重新核对。</p>}<details><summary className="cursor-pointer text-xs">原回应字段、批准计划与实际结果</summary><pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words text-xs">{JSON.stringify({ selected_fields: value.selected_fields, source: value.source_snapshot }, null, 2)}</pre></details></article>)}{data.next_before_version != null && <Button size="sm" variant="outline" disabled={busy} onClick={() => void act(() => read(Number(data.next_before_version)))}>更早反馈</Button>}
    </>}
  </div></details>;
}
