"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { field, obj, rows, text, type Row } from "@/components/quality/fmea-sources";
import { ChangeDiscussionRuns } from "./change-discussion-runs";

type Selection = { kind: string; id: string; seats: string[] };
const kinds: Record<string, string> = { task: "任务", issue: "问题", risk: "风险", decision: "裁决", specification: "规格", product_definition: "已发布产品定义", cost_gap_observation: "Cost Gap观察", cost_alternative: "降本备选方案", cost_backtest: "成本回测" };
const identity = (v: { kind: unknown; id: unknown }) => `${v.kind}:${v.id}`;

export function ProjectDiscussionTopics({ projectId, initialSource }: { projectId: string; initialSource?: {kind:string;id:string;title:string} }) {
  const [choices, setChoices] = useState<Row | null>(null), [selected, setSelected] = useState<Selection[]>(()=>initialSource?[{kind:initialSource.kind,id:initialSource.id,seats:[]}]:[]);
  const [prepared, setPrepared] = useState<Row | null>(null), [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const loaded = useRef(false);
  async function request(path: string, body?: unknown) {
    const response = await fetch(`/api/projects/${projectId}/changes/discussion-topics${path}`, body === undefined ? { cache: "no-store" } : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const value: unknown = await response.json();
    if (!response.ok) throw new Error(text(obj(obj(value).detail).message) || "主题资料读取未完成，请核对权限后重试");
    return obj(value);
  }
  async function act(fn: () => Promise<void>) {
    setBusy(true); setError("");
    try { await fn(); } catch (e) { setError(e instanceof Error ? e.message : "操作未完成"); }
    finally { setBusy(false); }
  }
  function change(values: Selection[]) { setSelected(values); setPrepared(null); }
  async function load() { setChoices(await request("/sources")); loaded.current = true; }
  const listed = rows(choices?.items), options = initialSource&&!listed.some(v=>v.kind===initialSource.kind&&v.id===initialSource.id)?[{...initialSource,status:"fixed_source"},...listed]:listed, seats = rows(choices?.seats);
  const picked = new Set(selected.map(identity));
  const filtered = options.filter(v => !picked.has(identity({ kind: v.kind, id: v.id })) && `${kinds[text(v.kind)]} ${text(v.title)}`.toLowerCase().includes(query.toLowerCase()));
  return <details className="rounded-md border p-3" onToggle={e => { if (e.currentTarget.open && !loaded.current && !busy) void act(load); }}>
    <summary className="cursor-pointer text-sm font-medium">{initialSource?"围绕本成本资料发起多专业讨论":"项目主题讨论 · 选择依据与比较方案"}</summary>
    <div className="mt-3 space-y-3 text-sm">
      <p>围绕项目中的问题或方案选择实际依据，分配给不同专业后发起讨论。本入口的讨论仅原发起人可见，读取时仍核对资料权限。</p>
      <p className="text-xs text-muted-foreground">{text(choices?.notice) || "可查看自己的讨论历史，或加载本项目可用资料准备新话题。"}</p>
      {error && <p role="alert" className="text-destructive">{error}</p>}
      <Button size="sm" variant="outline" disabled={busy} onClick={() => void act(load)}>刷新可选资料</Button>
      <fieldset disabled={busy} className="space-y-3">
        <label className="block">查找项目资料<input className={field} value={query} onChange={e => setQuery(e.target.value)} placeholder="按名称或资料类型查找"/></label>
        <div className="max-h-64 space-y-1 overflow-auto" aria-label="可选讨论资料">
          {filtered.map(item => <div className="flex items-center justify-between gap-3 rounded-md border px-2 py-1" key={identity({ kind: item.kind, id: item.id })}>
            <span>{kinds[text(item.kind)]} · {text(item.title)}</span>
            <Button size="sm" variant="outline" disabled={selected.length >= 30} onClick={() => change([...selected, { kind: text(item.kind), id: text(item.id), seats: [] }])}>选择</Button>
          </div>)}
          {choices && !filtered.length && <p className="text-muted-foreground">没有匹配的未选资料。</p>}
        </div>
        {selected.map(value => { const item = options.find(v => v.kind === value.kind && v.id === value.id); return <div key={identity(value)} className="space-y-2 rounded-md border p-2">
          <div className="flex items-center justify-between gap-2"><p>{kinds[value.kind]} · {text(item?.title) || "原选资料，准备时重新核对"}</p><Button size="sm" variant="ghost" onClick={() => change(selected.filter(v => identity(v) !== identity(value)))}>移除</Button></div>
          <div className="grid gap-2 text-xs sm:grid-cols-3">{seats.map(seat => <label className="flex items-start gap-2" key={text(seat.key)}><input type="checkbox" checked={value.seats.includes(text(seat.key))} onChange={e => change(selected.map(v => identity(v) === identity(value) ? { ...v, seats: e.target.checked ? [...v.seats, text(seat.key)] : v.seats.filter(k => k !== seat.key) } : v))}/>{text(seat.label)}</label>)}</div>
        </div>; })}
        <p className="text-xs text-muted-foreground">已选 {selected.length} / 30 项。至少两个席位须持有不同的实际依据。产品定义会附带其固定且可核对的商业画布版本。成本观察、备选预期与实际回测分列；讨论不执行成本修改、定义发布或ECR批准。</p>
        <Button size="sm" disabled={selected.length < 2 || selected.some(v => !v.seats.length)} onClick={() => void act(async () => { setPrepared(null); setPrepared(await request("/prepare", { selections: selected })); })}>准备本次讨论资料</Button>
      </fieldset>
      {prepared && <div className="space-y-1 text-xs"><p>资料已准备，选择下方参与席位并填写讨论问题即可排队；提交时会重新核对版本。</p>{rows(obj(obj(prepared.model_context).coverage).gaps).map((gap, i) => <p key={i} className="text-primary">待核对：{text(gap.message)}</p>)}<p>本次仅涵盖所选资料，不代表业务影响范围完整。</p></div>}
      <ChangeDiscussionRuns projectId={projectId} source={prepared ?? {}} requestedOpen={prepared !== null}/>
    </div>
  </details>;
}
