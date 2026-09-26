"use client";

import { useState } from "react";
import { FindingReviewUndo } from "./finding-review-undo";
import { Button } from "@/components/ui/button";
import { FINDING_TYPE_LABELS, type AiFinding } from "./ai-types";
import { FindingBatchError, requestFinding, requestFindings, requestFindingBatch, type FindingBatchRequest, type FindingBatchResult } from "./ai-api";
import { FindingAppliedReceipt, FindingDraftDiff, FindingProposal, PayloadEditor, findingApplyEffect, proposalReady } from "./finding-proposal";

const keyOf = (item: AiFinding) => `${item.project_id}:${item.finding_type}:${item.status}`;
const actions = { review_undone: "整组撤销裁决", accepted: "整组接受", rejected: "整组拒绝", applied: "整组独立应用" };
type Prepared = { action: FindingBatchRequest["action"]; items: AiFinding[] };

export function FindingBatchReview({ projectNames, onRecorded }: { projectNames?: Map<string, string>; onRecorded?: (items: AiFinding[]) => void }) {
  const [open, setOpen] = useState(false), [loaded, setLoaded] = useState(false);
  const [items, setItems] = useState<AiFinding[]>([]), [group, setGroup] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set()), [drafts, setDrafts] = useState<Record<string, Record<string, unknown>>>({});
  const [comment, setComment] = useState(""), [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null), [needsRefresh, setNeedsRefresh] = useState(false);
  const [prepared, setPrepared] = useState<Prepared | null>(null), [checked, setChecked] = useState(false);
  const [pending, setPending] = useState<FindingBatchRequest | null>(null);
  const [receipt, setReceipt] = useState<FindingBatchResult | null>(null), [lookup, setLookup] = useState("");
  const available = items.filter(item => ["pending_review", "accepted"].includes(item.status) && !item.superseded_by);
  const groups = [...new Map(available.map(item => [keyOf(item), item])).values()];
  const activeKey = groups.some(item => keyOf(item) === group) ? group : groups[0] ? keyOf(groups[0]) : "";
  const grouped = available.filter(item => keyOf(item) === activeKey);
  const chosen = grouped.filter(item => selected.has(item.id));
  const commonEvidence = chosen[0]?.evidence.filter(evidence => chosen.every(item => item.evidence.some(value => value.event_row_id === evidence.event_row_id))) ?? [];
  function invalidate() { setPrepared(null); setChecked(false); }
  async function load() {
    setBusy(true); setError(null); invalidate();
    try { setItems(await requestFindings()); setLoaded(true); setNeedsRefresh(false); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "建议读取失败"); }
    finally { setBusy(false); }
  }
  function adopt(result: FindingBatchResult) {
    setReceipt(result); setPending(null); invalidate(); setNeedsRefresh(false);
    setItems(current => [...current.filter(item => !result.items.some(value => value.id === item.id)), ...result.items]);
    setDrafts(current => Object.fromEntries(Object.entries(current).filter(([id]) => !result.items.some(value => value.id === id))));
    if (result.items[0]?.status === "accepted") { setGroup(keyOf(result.items[0])); setSelected(new Set(result.items.map(item => item.id))); }
    else setSelected(new Set());
    setLookup(result.receipt.request_id); onRecorded?.(result.items);
  }
  async function prepare(action: FindingBatchRequest["action"]) {
    if (!chosen.length || chosen.length > 20 || pending) return;
    setBusy(true); setError(null); invalidate();
    try {
      const current = await Promise.all(chosen.map(item => requestFinding(item.id)));
      if (current.some((item, index) => item.updated_at !== chosen[index].updated_at || item.superseded_by)) {
        setItems(existing => existing.map(item => current.find(value => value.id === item.id) ?? item));
        throw new Error("本组内容已有变化，已读取新版本；人工输入保留，请重新核对后准备。");
      }
      setPrepared({ action, items: current });
    } catch (failure) { setError(failure instanceof Error ? failure.message : "当前候选读取失败"); }
    finally { setBusy(false); }
  }
  async function submit(request: FindingBatchRequest) {
    setPending(request); setLookup(request.request_id); setBusy(true); setError(null);
    const url = new URL(window.location.href); url.searchParams.set("finding_batch_request", request.request_id); window.history.replaceState(null, "", url);
    try { adopt(await requestFindingBatch(request)); }
    catch (failure) {
      if (failure instanceof FindingBatchError && [400, 403, 404, 409, 422].includes(failure.status)) { setPending(null); invalidate(); setNeedsRefresh(true); }
      setError(failure instanceof Error ? failure.message : "批次结果未确认，请读取原请求回执。");
    } finally { setBusy(false); }
  }
  async function readReceipt() {
    if (!lookup.trim()) return;
    setBusy(true); setError(null);
    try { adopt(await requestFindingBatch(lookup.trim())); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "当前没有可读取的批次回执；原请求若尚在处理，请稍后再读。"); }
    finally { setBusy(false); }
  }
  return <section className="my-4 space-y-3 rounded-lg border bg-card p-3" aria-label="同类建议集中办理">
    <Button variant="outline" aria-expanded={open} onClick={() => { setOpen(value => !value); if (!open && !loaded) { setLookup(new URLSearchParams(window.location.search).get("finding_batch_request") ?? ""); void load(); } }}>同类建议集中办理</Button>
    {open && <>
      <p className="text-xs text-muted-foreground">每组选择同一项目、同一类型且同一办理状态的最多20条建议。整组同事务办理；一条冲突会整组回滚。接受和独立应用分开进行，每条沿用原业务核验与审批。</p>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" disabled={busy || !!pending} onClick={() => void load()}>刷新可办理建议</Button><input aria-label="批次请求编号" className="min-w-0 flex-1 rounded-md border bg-background p-2 text-xs" placeholder="粘贴本人的批次请求编号，或使用当前地址中的编号" value={lookup} disabled={busy || !!pending} onChange={event => setLookup(event.target.value)}/><Button size="sm" variant="outline" disabled={busy || !lookup.trim()} onClick={() => void readReceipt()}>读取原请求回执</Button></div>
      {pending && <div className="space-y-2 rounded-md border p-3 text-xs"><p>原请求结果尚未确认：{pending.request_id}。请先读取回执；也可用完全相同的请求重试，服务器会复用已完成结果。</p><Button variant="outline" size="sm" disabled={busy} onClick={() => void submit(pending)}>用原请求重试</Button></div>}
      {needsRefresh && <p className="text-xs">本次整组办理未完成。请刷新可办理建议后核对，未提交输入保留。</p>}
      <fieldset disabled={busy || !!pending || needsRefresh} className="space-y-3">
        <label className="block text-sm">本次办理范围<select className="ml-2 max-w-full rounded-md border bg-background p-2" value={activeKey} onChange={event => { setGroup(event.target.value); setSelected(new Set()); invalidate(); }}>{groups.map(item => <option key={keyOf(item)} value={keyOf(item)}>{projectNames?.get(item.project_id) ?? item.project_id} · {FINDING_TYPE_LABELS[item.finding_type]} · {item.status === "accepted" ? "待应用" : "待审阅"}</option>)}</select></label>
        {!grouped.length && loaded && <p className="text-sm text-muted-foreground">当前没有可集中办理的建议。</p>}
        {grouped.map(item => <article className="space-y-2 rounded-md border p-3 text-sm" key={item.id}>
          <label className="flex items-start gap-2"><input type="checkbox" checked={selected.has(item.id)} disabled={!selected.has(item.id) && chosen.length >= 20} onChange={event => { setSelected(current => { const next = new Set(current); if (event.target.checked) next.add(item.id); else next.delete(item.id); return next; }); invalidate(); }}/><span>{item.title}</span></label>
          {selected.has(item.id) && <details><summary className="cursor-pointer text-primary">核对本项内容、差异和业务结果</summary><div className="mt-2 space-y-2"><p>{item.summary}</p>
            {item.status === "pending_review" ? <PayloadEditor finding={item} payload={drafts[item.id] ?? item.proposed_payload} onChange={value => { setDrafts(current => ({ ...current, [item.id]: value })); invalidate(); }}/> : <FindingProposal finding={item} payload={item.accepted_payload ?? {}}/>}
            <FindingDraftDiff original={item.proposed_payload} changed={item.status === "accepted" ? item.accepted_payload ?? {} : drafts[item.id] ?? item.proposed_payload}/>
            <p>{findingApplyEffect(item)}</p><ul>{item.evidence.map((evidence,index) => <li key={`${evidence.event_row_id}:${index}`}><a className="text-primary underline" href={evidence.href}>{evidence.label}</a></li>)}</ul><a className="text-xs text-primary underline" href={`/ai-review?finding=${item.id}`}>打开本项完整记录</a>
          </div></details>}
        </article>)}
        {chosen.length > 0 && <>
          <div className="text-xs"><p>共同事件依据：{commonEvidence.length ? "以下事件被本组所有建议引用；不代表结论已成立。" : "没有本组全部共享的事件引用，请逐项核对各自来源。"}</p>{commonEvidence.map((evidence,index) => <a className="mr-3 text-primary underline" key={`${evidence.event_row_id}:${index}`} href={evidence.href}>{evidence.label}</a>)}</div>
          <label className="block text-sm">共同办理说明／拒绝理由<textarea className="mt-1 w-full rounded-md border bg-background p-2" maxLength={3000} value={comment} onChange={event => { setComment(event.target.value); invalidate(); }}/></label>
          <div className="flex flex-wrap gap-2">{(chosen[0].status === "accepted" ? ["applied"] as const : ["accepted", "rejected"] as const).map(action => <Button variant={action === "rejected" ? "outline" : "default"} key={action} disabled={!comment.trim() || action === "accepted" && chosen.some(item => !proposalReady(item, drafts[item.id] ?? item.proposed_payload))} onClick={() => void prepare(action)}>准备{actions[action]}（{chosen.length}）</Button>)}</div>
        </>}
        {prepared && <section className="space-y-3 rounded-md border border-primary/30 p-3" aria-label="整组最终核对"><h3 className="font-semibold">{actions[prepared.action]} · {prepared.items.length} 条</h3><p className="text-sm">{comment}</p>{prepared.items.map(item => <div className="space-y-2 rounded-md border p-2" key={item.id}><h4 className="text-sm font-medium">{item.title}</h4><FindingProposal finding={item} payload={prepared.action === "applied" ? item.accepted_payload ?? {} : drafts[item.id] ?? item.proposed_payload}/><FindingDraftDiff original={item.proposed_payload} changed={prepared.action === "applied" ? item.accepted_payload ?? {} : drafts[item.id] ?? item.proposed_payload}/><p className="text-xs">{prepared.action === "applied" ? findingApplyEffect(item) : prepared.action === "accepted" ? "只保存本项裁决，之后需独立应用。" : "只记录拒绝理由；未提交的字段修改不会保存，不创建业务对象。"}</p></div>)}<label className="flex gap-2 text-sm"><input type="checkbox" checked={checked} onChange={event => setChecked(event.target.checked)}/>我已核对本组每项内容、来源及办理结果</label><Button disabled={!checked} onClick={() => void submit({ request_id: crypto.randomUUID(), action: prepared.action, comment: comment.trim(), items: prepared.items.map(item => ({ finding_id: item.id, expected_updated_at: item.updated_at, ...(prepared.action === "accepted" && drafts[item.id] ? { edited_payload: drafts[item.id] } : {}) })) })}>确认{actions[prepared.action]}</Button></section>}
      </fieldset>
      {receipt && ["accepted", "rejected"].includes(receipt.receipt.action) && <FindingReviewUndo key={receipt.receipt.id} items={receipt.items} onRecorded={adopt}/>}
      {receipt && <section className="space-y-2 rounded-md border p-3" aria-label="整组办理回执"><p className="text-sm font-semibold">已记录{actions[receipt.receipt.action as keyof typeof actions]} · {receipt.receipt.results.length} 条{receipt.replayed ? "（读取原回执）" : ""}</p><p className="break-all text-xs">请求：{receipt.receipt.request_id} · {new Date(receipt.receipt.created_at).toLocaleString("zh-CN")}</p><p className="text-xs">{receipt.receipt.request.comment}</p><p className="text-xs text-muted-foreground">以下为各项当前状态；本批次原结果已独立留档。</p>{receipt.items.map(item => <div className="rounded-md border p-2" key={item.id}><a className="text-sm text-primary underline" href={`/ai-review?finding=${item.id}`}>{item.title}</a><p className="text-xs">当前：{({ pending_review: "待审", accepted: "已接受待应用", applied: "已应用", rejected: "已拒绝", archived: "已归档" })[item.status]}；本批次：{actions[receipt.receipt.action as keyof typeof actions]}</p><FindingAppliedReceipt finding={item}/></div>)}</section>}
    </>}
  </section>;
}
