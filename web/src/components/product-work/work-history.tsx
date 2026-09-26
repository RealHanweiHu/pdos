"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { request, stateLabels, type Evidence, type EvidenceContent, type SourceRef } from "./product-work-api";

type Snapshot = { version: number | null; state: string | null; result_note: string | null; evidence: SourceRef[] | null; accepted_at: string | null; cancellation_reason: string | null };
type Entry = { id: number; event_id: string; action: string; timestamp: string; actor_user_id: string | null; actor_display_name: string | null; before: Snapshot | null; after: Snapshot | null };
type History = { current_version: number; items: Entry[]; next_before_id: number | null };
const actions: Record<string, string> = { created: "登记工作", assign: "确认分派", start: "开始办理", submit: "提交结果", return: "退回补充", accept: "确认接收", cancel: "取消工作" };
const time = (value: string) => new Date(value).toLocaleString();

export function WorkHistory({ base, workId, version, evidence }: { base: string; workId: string; version: number; evidence: Evidence[] }) {
  const [open, setOpen] = useState(false), [busy, setBusy] = useState(false);
  const [items, setItems] = useState<Entry[]>([]), [next, setNext] = useState<number | null>(null);
  const [currentVersion, setCurrentVersion] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null), [body, setBody] = useState<EvidenceContent | null>(null);
  async function load(before?: number) {
    setBusy(true); setError(null); setBody(null);
    try {
      const value = await request<History>(`${base}/work-items/${workId}/history${before ? `?before_id=${before}` : ""}`);
      setItems(previous => before ? [...previous, ...value.items].filter((item, index, all) => all.findIndex(other => other.id === item.id) === index) : value.items);
      setNext(value.next_before_id); setCurrentVersion(value.current_version);
    } catch (failure) { setItems([]); setNext(null); setError(failure instanceof Error ? failure.message : "办理历史暂不可用"); }
    finally { setBusy(false); }
  }
  async function readSource(ref: SourceRef) {
    setBusy(true); setError(null); setBody(null);
    try {
      const value = await request<EvidenceContent>(`${base}/evidence/${ref.ref_id}/content`);
      if (value.snapshot_id !== ref.ref_id || value.content_digest !== ref.digest) throw new Error("原依据摘要不匹配，请刷新并核对原记录");
      setBody(value);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "原依据正文暂不可用"); }
    finally { setBusy(false); }
  }
  function sources(refs: SourceRef[] | null) {
    return !!refs?.length && <ul className="space-y-1">{refs.map((ref, index) => <li key={`${ref.ref_id}:${index}`} className="break-words text-xs">{evidence.find(item => item.id === ref.ref_id)?.name ?? `原依据 ${index + 1}`} · {time(ref.as_of)} <Button size="sm" variant="ghost" disabled={busy} onClick={() => void readSource(ref)}>查看此版原文</Button><details><summary className="cursor-pointer">来源编号与摘要</summary><p className="break-all">{ref.ref_id} · {ref.digest}</p></details></li>)}</ul>;
  }
  return <section aria-label="专业工作办理历史" className="border-t pt-3">
    <Button size="sm" variant="outline" disabled={busy} aria-expanded={open} onClick={() => { setOpen(value => !value); if (!open) void load(); }}>{open ? "收起办理历史" : "查看办理历史"}</Button>
    {open && <div className="mt-3 space-y-3">
      <p className="text-xs text-muted-foreground">按实际办理回执倒序。保留每次提交与退回前的结果及原依据；人员姓名为当前账号显示名，原账号与事件编号可回查。责任调整另见原入口。</p>
      {busy && <p role="status" className="text-sm">正在读取…</p>}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {currentVersion !== null && currentVersion !== version && <p className="text-sm">工作记录已更新，请刷新工作区核对当前状态。</p>}
      <Button size="sm" variant="ghost" disabled={busy} onClick={() => void load()}>刷新办理历史</Button>
      <ol className="space-y-3">{items.map(item => <li key={item.id} className="space-y-2 border-l-2 pl-3 text-sm">
        <p className="font-medium">{actions[item.action] ?? item.action} · {item.actor_display_name ?? "历史账号"} · {time(item.timestamp)}</p>
        <p className="text-xs text-muted-foreground">{item.before?.state ? stateLabels[item.before.state] ?? item.before.state : "未登记"} → {item.after?.state ? stateLabels[item.after.state] ?? item.after.state : "历史状态缺失"} · 原版本 {item.before?.version ?? "—"} → {item.after?.version ?? "—"}</p>
        {item.after?.result_note && <p className="whitespace-pre-wrap">本次记录：{item.after.result_note}</p>}
        {item.after?.cancellation_reason && <p className="whitespace-pre-wrap">取消原因：{item.after.cancellation_reason}</p>}
        {sources(item.after?.evidence ?? null)}
        {item.before && (item.before.result_note !== item.after?.result_note || JSON.stringify(item.before.evidence) !== JSON.stringify(item.after?.evidence)) && <details><summary className="cursor-pointer">办理前的结果与依据</summary><p className="mt-2 whitespace-pre-wrap">{item.before.result_note}</p>{sources(item.before.evidence)}</details>}
        <details className="text-xs text-muted-foreground"><summary className="cursor-pointer">原回执</summary><p className="break-all">账号 {item.actor_user_id ?? "未记录"} · 回执 {item.id} · 事件 {item.event_id}</p>{item.after?.accepted_at && <p>接收时间：{time(item.after.accepted_at)}</p>}</details>
      </li>)}</ol>
      {!busy && !error && currentVersion !== null && !items.length && <p className="text-sm">没有可读取的业务办理历史；不根据当前状态补造历史。</p>}
      {next !== null && <Button size="sm" variant="outline" disabled={busy} onClick={() => void load(next)}>继续读取更早办理</Button>}
      {body && <section aria-label="历史依据原文" className="space-y-2 rounded-md border p-3"><div className="flex justify-between gap-2"><h5 className="font-medium">此版原始正文</h5><Button size="sm" variant="ghost" onClick={() => setBody(null)}>关闭原文</Button></div><p className="text-xs text-muted-foreground">原文不代表已独立核实 · {body.taint}</p><pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words text-xs">{body.content}</pre></section>}
    </div>}
  </section>;
}
