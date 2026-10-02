"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { ProductRequestError, request } from "./product-work-api";

type Item = { title: string; description: string; priority: string; acceptance_criteria: string[]; missing: string[]; category_label: string | null; basis: { text: string; nature: string; citations: { reference_id: string; digest: string; field_path: string[]; quoted_value: string }[] } };
type Finding = { id: string; status: string; proposed_digest: string };
type Record = { requirement_id: string; accepted_item: Item };
type Detail = { finding: Finding | null; items: Item[]; sources_current: boolean; references: { reference_id: string; label: string }[]; records: Record[] };
type Confirmation = { run_id: string; finding_id: string; expected_digest: string; decision: "accepted" | "rejected"; comment: string; items: Item[] };

type Props = { base: string; runId: string; disabled?: boolean; onFailure: (message: string) => void; onAccessDenied?: (message: string) => void; onPendingChange?: (pending: boolean) => void; captureAccess?: () => () => boolean };
export function ProductRfqProposal(props: Props) {
  return <ProductRfqProposalPanel key={JSON.stringify([props.base, props.runId])} {...props}/>;
}
function ProductRfqProposalPanel({ base, runId, disabled = false, onFailure, onAccessDenied, onPendingChange, captureAccess }: Props) {
  const [detail, setDetail] = useState<Detail | null>(null), [items, setItems] = useState<Item[]>([]);
  const [comment, setComment] = useState(""), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [pending, setPending] = useState<Confirmation | null>(null), [notice, setNotice] = useState("");
  const live = useRef(true), revision = useRef(0), working = useRef(false), original = useRef<Confirmation | null>(null);
  const callbacks = useRef({ onFailure, onAccessDenied, onPendingChange, captureAccess });
  useEffect(() => { callbacks.current = { onFailure, onAccessDenied, onPendingChange, captureAccess }; }, [onFailure, onAccessDenied, onPendingChange, captureAccess]);
  function capture() { const version = revision.current, parent = callbacks.current.captureAccess?.() ?? (() => true); return () => live.current && version === revision.current && parent(); }
  function clearPending() { original.current = null; setPending(null); callbacks.current.onPendingChange?.(false); }
  function clearPrivateContent(message: string) {
    revision.current += 1; working.current = false; setDetail(null); setItems([]); setComment(""); clearPending(); setNotice(""); setBusy(false); setError(message);
    callbacks.current.onAccessDenied?.(message); callbacks.current.onFailure(message);
  }
  useEffect(() => {
    live.current = true; const current = capture();
    void request<Detail>(`${base}/rfq-ai-finding`, "POST", { run_id: runId }).then(value => { if (current()) { setDetail(value); setItems(value.items); } }).catch(failure => {
      if (!current()) return;
      if (failure instanceof ProductRequestError && [401, 403].includes(failure.status)) clearPrivateContent(failure.message);
      else { const message = failure instanceof Error ? failure.message : "需求候选暂不可读"; setError(message); callbacks.current.onFailure(message); }
    });
    return () => { live.current = false; revision.current += 1; original.current = null; callbacks.current.onPendingChange?.(false); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  async function confirm(body: Confirmation) {
    if (!live.current || working.current || disabled || (original.current && original.current !== body)) return;
    const requestBody = original.current ?? JSON.parse(JSON.stringify(body)) as Confirmation;
    original.current = requestBody; working.current = true; setBusy(true); setError(""); setNotice(""); setPending(requestBody); callbacks.current.onPendingChange?.(true); const current = capture();
    try {
      const result = await request<{ finding: Finding; records: Record[] }>(`${base}/rfq-ai-confirm`, "POST", requestBody);
      if (current()) { setDetail(previous => previous ? { ...previous, ...result } : previous); clearPending(); }
    } catch (failure) {
      if (!current()) return;
      if (failure instanceof ProductRequestError && [401, 403].includes(failure.status)) clearPrivateContent(failure.message);
      else {
        if (failure instanceof ProductRequestError && failure.status < 500 && ![408, 429].includes(failure.status)) clearPending();
        setError(failure instanceof Error ? failure.message : "登记结果未确认，可用原内容重试");
      }
    } finally { if (current()) { working.current = false; setBusy(false); } }
  }
  async function recover() {
    if (!live.current || working.current || !original.current) return;
    const requestBody = original.current; working.current = true; setBusy(true); setError(""); setNotice(""); const current = capture();
    try {
      const value = await request<Detail>(`${base}/rfq-ai-finding`, "POST", { run_id: runId });
      if (!current()) return;
      if (!value.finding || value.finding.id !== requestBody.finding_id || value.finding.proposed_digest !== requestBody.expected_digest) {
        setError("未找到原确认对应的候选，请保留当前页面，稍后查询原确认结果。"); return;
      }
      setDetail(value);
      if (["applied", "rejected"].includes(value.finding.status)) { setItems(value.items); clearPending(); }
      else setNotice("尚未查到办理完成记录，已保留上次确认内容，可稍后再查询或重试原确认。");
    } catch (failure) {
      if (!current()) return;
      if (failure instanceof ProductRequestError && [401, 403].includes(failure.status)) clearPrivateContent(failure.message);
      else setError(failure instanceof Error ? failure.message : "暂时无法查询确认结果");
    } finally { if (current()) { working.current = false; setBusy(false); } }
  }
  if (!detail) return error ? <p role="alert" className="text-destructive">{error}</p> : <p role="status">正在读取需求候选…</p>;
  if (!detail.finding) return <p>本次没有可登记的需求候选，请核对原文与缺项。</p>;
  const reviewable = !disabled && !busy && !pending && detail.finding.status === "pending_review";
  const editable = reviewable && detail.sources_current;
  const update = (index: number, patch: Partial<Item>) => setItems(current => current.map((item, i) => i === index ? { ...item, ...patch } : item));
  return <section className="space-y-3 rounded-lg border p-4" aria-label="RFQ需求确认">
    <h4 className="font-medium">核对需求与原文</h4>
    <p className="text-muted-foreground">确认后整批登记为租户需求池中的草稿，有需求查看权限的成员可读；原件仍仅供上传人读取。不会批准规格或创建项目。业务四类名称待明确，暂保留未分类。</p>
    {!detail.sources_current && <p className="text-primary">原资料已变化，请重新抽取；当前候选不能登记。</p>}
    {items.map((item, index) => <fieldset key={index} disabled={!editable} className="space-y-2 rounded-md border p-3">
      <legend className="px-1 font-medium">需求{index + 1}</legend>
      <label className="block">名称<input className="mt-1 w-full rounded-md border bg-background p-2" maxLength={512} value={item.title} onChange={event => update(index, { title: event.target.value })}/></label>
      <label className="block">要求与工况<textarea className="mt-1 min-h-24 w-full rounded-md border bg-background p-2" maxLength={12000} value={item.description} onChange={event => update(index, { description: event.target.value })}/></label>
      <label className="block">优先级<select className="ml-2 rounded-md border bg-background p-2" value={item.priority} onChange={event => update(index, { priority: event.target.value })}>{[["low", "低"], ["medium", "中"], ["high", "高"], ["critical", "关键"]].map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
      <label className="block">验收条件（每行一项，未知可留空）<textarea className="mt-1 w-full rounded-md border bg-background p-2" value={item.acceptance_criteria.join("\n")} onChange={event => update(index, { acceptance_criteria: event.target.value.split("\n") })}/></label>
      <label className="block">待澄清项（每行一项）<textarea className="mt-1 w-full rounded-md border bg-background p-2" value={item.missing.join("\n")} onChange={event => update(index, { missing: event.target.value.split("\n") })}/></label>
      <p className="text-muted-foreground">依据：{item.basis.text}</p>
      {item.basis.citations.map((citation, i) => <div key={i}><p className="text-xs">{detail.references.find(ref => ref.reference_id === citation.reference_id)?.label ?? "本次原文"}</p><blockquote className="whitespace-pre-wrap break-words border-l-2 pl-3">{citation.quoted_value}</blockquote></div>)}
    </fieldset>)}
    {detail.finding.status === "pending_review" && <><label className="block">核对说明<textarea className="mt-1 w-full rounded-md border bg-background p-2" disabled={!reviewable} maxLength={2048} value={comment} onChange={event => setComment(event.target.value)}/></label>
      <div className="flex flex-wrap gap-2"><Button disabled={!editable || !comment.trim() || !items.length} onClick={() => void confirm({ run_id: runId, finding_id: detail.finding!.id, expected_digest: detail.finding!.proposed_digest, decision: "accepted", comment: comment.trim(), items: items.map(item => ({ ...item, acceptance_criteria: item.acceptance_criteria.map(text => text.trim()).filter(Boolean), missing: item.missing.map(text => text.trim()).filter(Boolean) })) })}>确认并登记需求草稿</Button><Button variant="outline" disabled={!reviewable || !comment.trim()} onClick={() => void confirm({ run_id: runId, finding_id: detail.finding!.id, expected_digest: detail.finding!.proposed_digest, decision: "rejected", comment: comment.trim(), items: [] })}>拒绝此批候选</Button></div></>}
    {pending && <div><p>上次办理结果尚未确认，可先查询结果；重试会保留相同内容，请保持当前页面。</p><div className="flex flex-wrap gap-2"><Button variant="outline" disabled={busy} onClick={() => void recover()}>查询确认结果</Button><Button variant="outline" disabled={busy || disabled} onClick={() => void confirm(pending)}>重试原确认</Button></div></div>}
    {notice && <p role="status">{notice}</p>}
    {detail.finding.status === "applied" && <p role="status">已登记{detail.records.length}项需求草稿。<a href="/requirements" className="ml-2 text-primary underline">查看需求池</a></p>}
    {detail.finding.status === "rejected" && <p role="status">已拒绝，未登记需求。</p>}
    {error && <p role="alert" className="text-destructive">{error}</p>}
  </section>;
}
