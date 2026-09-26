"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { field, obj, rows, text, type Row } from "@/components/quality/fmea-sources";

export type QuietAnchor = { baseline_id: string; node_id: string; expected_digest: string };
const date = (v: unknown) => typeof v === "string" ? new Date(v).toLocaleString("zh-CN") : "日期未定";

export function QuietAnchorValue({ source }: { source: unknown }) {
  const status = obj(source), snapshot = obj(status.snapshot), time = obj(snapshot.time);
  return <div className="space-y-1 text-xs">{snapshot.baseline_id != null && <p>正式基线 v{String(snapshot.baseline_version)} · {text(obj(snapshot.plan_node).title)} · {date(time.start)} 至 {date(time.end)}</p>}{status.current === false && <p className="text-destructive">{text(status.reason)}</p>}</div>;
}

export function QuietAnchorPicker({ projectId, value, onChange }: { projectId: string; value: QuietAnchor | null; onChange: (value: QuietAnchor | null) => void }) {
  const [options, setOptions] = useState<Row[]>([]), [next, setNext] = useState<number | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState("");
  async function read(more = false) { setBusy(true); setError(""); try {
    const res = await fetch(`/api/projects/${projectId}/changes/quiet-policy/sources?offset=${more ? next ?? 0 : 0}`, { cache: "no-store" }); const raw: unknown = await res.json(); const result = obj(raw);
    if (!res.ok) throw new Error(text(obj(result.detail).message) || "正式计划暂不可读");
    setOptions(old => more ? [...old, ...rows(result.items)] : rows(result.items)); setNext(typeof result.next_offset === "number" ? result.next_offset : null); if (result.source_error) setError(text(result.source_error));
  } catch(e) { setError(e instanceof Error ? e.message : "读取失败"); } finally { setBusy(false); } }
  const selected = options.find(o => o.node_id === value?.node_id && o.baseline_id === value?.baseline_id && o.digest === value?.expected_digest);
  return <fieldset disabled={busy} className="space-y-2 rounded-md border p-2"><legend className="px-1 text-xs">绑定正式计划节点</legend><Button type="button" size="sm" variant="outline" onClick={() => void read()}>读取当前正式计划</Button><label className="block text-xs">本窗口对应的阶段节点<select required className={field} value={selected ? text(selected.node_id) : value ? "original" : ""} onChange={e => { const v = options.find(o => o.node_id === e.target.value); onChange(v ? { baseline_id: text(v.baseline_id), node_id: text(v.node_id), expected_digest: text(v.digest) } : null); }}><option value="">选择实际正式节点</option>{value && !selected && <option value="original">保留的原绑定，请读取并核对当前版本</option>}{options.map(o => <option key={`${o.baseline_id}:${o.node_id}`} value={text(o.node_id)}>基线 v{String(o.baseline_version)} · {text(obj(o.plan_node).title)} · {date(obj(o.time).start)} 至 {date(obj(o.time).end)}</option>)}</select></label>{selected && <p className="text-xs">{text(obj(selected.plan_node).completion_criteria)}</p>}{next !== null && <Button type="button" size="sm" variant="outline" onClick={() => void read(true)}>更多正式节点</Button>}{error && <p role="alert" className="text-xs text-destructive">{error}</p>}<p className="text-xs text-muted-foreground">冻结时间仍按本次人工确认的窗口保存；新基线须重新核对，预测日期不会覆盖本绑定。</p></fieldset>;
}

export function QuietApproverReplacement({ entry, data, busy, write }: { entry: Row; data: Row; busy: boolean; write: (body: Row) => void }) {
  const [editing, setEditing] = useState(false), [chain, setChain] = useState<string[]>(Array.isArray(entry.approver_ids) ? entry.approver_ids.map(String) : []), [reason, setReason] = useState("");
  const ecr = obj(data.ecr), blocked = new Set([data.actor_id, entry.created_by_user_id, ecr.requested_by_user_id, ecr.analyzed_by_user_id]);
  const people = rows(data.people).filter(p => !blocked.has(p.id));
  const can = data.can_decide === true && entry.current === true && obj(entry.source).current === true && ecr.status === "approval" && entry.status !== "rejected" && ![entry.created_by_user_id, ecr.requested_by_user_id, ecr.analyzed_by_user_id].includes(data.actor_id);
  if (!can) return null;
  return <div className="space-y-2">{!editing ? <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => setEditing(true)}>明确替换审批人员</Button> : <form className="space-y-2" onSubmit={e => { e.preventDefault(); write({ approver_ids: chain, reason }); }}><fieldset disabled={busy} className="space-y-2"><p>保留全部审批环节，从第一环重新审批。旧裁决保留为历史；确认替换的人不能进入本次新审批链。</p>{chain.map((id, i) => <label className="block" key={i}>第 {i + 1} 环替代审批人<select required className={field} value={id} onChange={e => setChain(chain.map((v, n) => n === i ? e.target.value : v))}><option value="">请选择具名人员</option>{!people.some(p => p.id === id) && id && <option value={id} disabled>原人员当前不具资格，请替换</option>}{people.map(p => <option key={text(p.id)} value={text(p.id)} disabled={chain.includes(text(p.id)) && id !== p.id}>{text(p.name)}</option>)}</select></label>)}<label className="block">人员变化及替换依据<textarea required maxLength={4000} className={field} value={reason} onChange={e => setReason(e.target.value)}/></label><div className="flex gap-2"><Button size="sm" disabled={chain.some(id => !people.some(p => p.id === id))}>确认替换并重新审批</Button><Button type="button" size="sm" variant="outline" onClick={() => setEditing(false)}>放弃替换</Button></div></fieldset></form>}</div>;
}
