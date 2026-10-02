"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";
import { WorkItemRequestError, type IssueTransitionExtra } from "./project-work-item-api";
import type { MaterialClosureReference, ProjectIssue } from "./project-work-item-types";

type MaterialClosureItem = {
  exception_id: string;
  title: string;
  closure: { ready: boolean; reasons: string[]; reference: MaterialClosureReference | null };
};
export type MaterialClosureContext = { required: boolean; ready: boolean; items: MaterialClosureItem[]; access_denied?: boolean; reason?: string };

function reference(value: unknown): value is MaterialClosureReference {
  return isRecord(value) && ["exception_id", "review_id", "source_digest"].every(key => typeof value[key] === "string" && !!value[key]);
}

export function materialClosureContext(value: unknown): MaterialClosureContext | null {
  if (!isRecord(value) || typeof value.required !== "boolean" || typeof value.ready !== "boolean" || !Array.isArray(value.items)) return null;
  const items: MaterialClosureItem[] = [];
  for (const item of value.items) {
    if (!isRecord(item) || typeof item.exception_id !== "string" || typeof item.title !== "string" || !isRecord(item.closure)) return null;
    const closure = item.closure;
    if (typeof closure.ready !== "boolean" || !Array.isArray(closure.reasons) || !closure.reasons.every(reason => typeof reason === "string")) return null;
    if (closure.reference !== null && (!reference(closure.reference) || closure.reference.exception_id !== item.exception_id)) return null;
    if (closure.ready && !reference(closure.reference)) return null;
    items.push({ exception_id: item.exception_id, title: item.title, closure: { ready: closure.ready, reasons: closure.reasons, reference: closure.reference as MaterialClosureReference | null } });
  }
  if (value.access_denied === true && value.required && !value.ready && items.length === 0) return { required: true, ready: false, items, access_denied: true, reason: typeof value.reason === "string" ? value.reason : "当前没有查看物料关闭来源的权限，请由具名验证人核对。" };
  if (new Set(items.map(item => item.exception_id)).size !== items.length || value.required !== (items.length > 0)) return null;
  return { required: value.required, ready: value.ready, items };
}

export function sameMaterialReference(left: MaterialClosureReference, right: MaterialClosureReference) {
  return left.exception_id === right.exception_id && left.review_id === right.review_id && left.source_digest === right.source_digest;
}

export function materialSelectionReady(context: MaterialClosureContext | null, selected: MaterialClosureReference[] | null) {
  if (!context) return false;
  if (!context.required) return true;
  return context.ready && selected?.length === context.items.length && context.items.every(item => item.closure.ready && item.closure.reference && selected.some(value => sameMaterialReference(value, item.closure.reference!)));
}

export function linkedMaterialReference(projectId: string, issueId: string, search: string): MaterialClosureReference | null {
  const params = new URLSearchParams(search);
  if (params.get("project") !== projectId || params.get("entity_id") !== issueId) return null;
  const value = { exception_id: params.get("material_exception_id"), review_id: params.get("material_review_id"), source_digest: params.get("material_source_digest") };
  return reference(value) ? value : null;
}

export function MaterialIssueClosureReview({ context, selected, onSelect, disabled, linked }: {
  context: MaterialClosureContext | null;
  selected: MaterialClosureReference[] | null;
  onSelect: (references: MaterialClosureReference[] | null) => void;
  disabled: boolean;
  linked: MaterialClosureReference | null;
}) {
  if (!context) return <p className="text-sm text-destructive">尚未取得当前物料关闭依据，请刷新后核对。</p>;
  if (!context.required) return null;
  if (context.access_denied) return <p className="text-sm text-destructive">{context.reason}</p>;
  const canSelect = context.ready && context.items.every(item => item.closure.ready && item.closure.reference);
  const linkedCurrent = linked && context.items.some(item => item.closure.reference && sameMaterialReference(item.closure.reference, linked));
  return <section className="space-y-2 rounded-md border p-3 text-sm" aria-label="物料恢复关闭依据">
    <p className="font-medium">核对原问题关联的全部物料恢复记录</p>
    <p className="text-xs text-muted-foreground">来源复核只证明物料恢复；仍由原问题验证人核对关闭条件并明确关闭。</p>
    {linked && <p className={linkedCurrent ? "text-xs" : "text-xs text-destructive"}>{linkedCurrent ? "供应入口带来的记录与当前来源一致，仍需明确选择。" : "供应入口带来的记录已过期或与当前问题不符，请保留原引用核对，再重新选择当前来源。"}<span className="block break-all">原核对记录：{linked.review_id} · 原来源：{linked.source_digest}</span></p>}
    <ul className="space-y-2">{context.items.map(item => <li key={item.exception_id} className="rounded-md border p-2">
      <p>{item.title} · {item.closure.ready ? "当前复核可供关闭验证" : "仍需核对"}</p>
      {item.closure.reasons.map((reason, index) => <p key={index} className="text-xs text-destructive">{reason}</p>)}
      {item.closure.reference && <details className="mt-1 text-xs"><summary className="cursor-pointer">查看本次引用的核对记录与来源</summary><p className="break-all">异常：{item.exception_id}</p><p className="break-all">核对记录：{item.closure.reference.review_id}</p><p className="break-all">当前来源：{item.closure.reference.source_digest}</p></details>}
    </li>)}</ul>
    <label className="flex min-h-11 items-start gap-2"><input type="checkbox" className="mt-1" checked={materialSelectionReady(context, selected)} disabled={disabled || !canSelect} onChange={event => onSelect(event.target.checked ? context.items.map(item => ({ ...item.closure.reference! })) : null)}/><span>我已核对以上全部来源，引用本次物料恢复记录</span></label>
    {!canSelect && <p className="text-xs text-destructive">全部关联异常取得当前有效复核后，才可选择关闭依据。</p>}
  </section>;
}

type ClosureCard = {
  item: ProjectIssue;
  actor_id: string;
  permissions: Record<string, unknown>;
  verification_policy: Record<string, unknown>;
  material_closure: MaterialClosureContext;
};

export function MaterialIssueClosureForm({ projectId, issue, busy, onSubmit, onCancel }: {
  projectId: string;
  issue: ProjectIssue;
  busy: boolean;
  onSubmit: (extra: IssueTransitionExtra) => Promise<boolean>;
  onCancel: () => void;
}) {
  const [card, setCard] = useState<ClosureCard | null>(null);
  const [selected, setSelected] = useState<MaterialClosureReference[] | null>(null);
  const [linked, setLinked] = useState<MaterialClosureReference | null>(null);
  const [evidence, setEvidence] = useState("");
  const [loading, setLoading] = useState(true);
  const [mustRefresh, setMustRefresh] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sequence = useRef(0);
  const cardUrl = `/api/projects/${encodeURIComponent(projectId)}/issues/${encodeURIComponent(issue.id)}/work-card`;

  async function readCard() {
    const current = ++sequence.current;
    try {
      const response = await fetch(cardUrl, { cache: "no-store", credentials: "same-origin" });
      const body: unknown = await responseBody(response).catch(() => null);
      if (!response.ok) throw new WorkItemRequestError(isRecord(body) && isRecord(body.detail) && typeof body.detail.message === "string" ? body.detail.message : "未取得当前关闭依据，请刷新原记录核对", response.status);
      const context = isRecord(body) ? materialClosureContext(body.material_closure) : null;
      if (!isRecord(body) || !isRecord(body.item) || body.item.id !== issue.id || body.item.project_id !== projectId || typeof body.item.updated_at !== "string" || !context || !isRecord(body.permissions) || !isRecord(body.verification_policy) || typeof body.actor_id !== "string") throw new Error("关闭依据不完整，请刷新原记录核对");
      if (current !== sequence.current) return;
      setCard({ ...body, material_closure: context } as ClosureCard); setSelected(null); setMustRefresh(false);
      setLinked(linkedMaterialReference(projectId, issue.id, window.location.search));
    } catch (cause) {
      if (current !== sequence.current) return;
      if (cause instanceof WorkItemRequestError && [401, 403, 404].includes(cause.status)) { setCard(null); setSelected(null); }
      else if (cause instanceof WorkItemRequestError && cause.status === 409) setSelected(null);
      setMustRefresh(true); setError(cause instanceof Error ? cause.message : "读取失败");
    } finally { if (current === sequence.current) setLoading(false); }
  }

  function refresh() { setLoading(true); setError(null); void readCard(); }
  function cancelRead() { ++sequence.current; }
  useEffect(() => {
    let active = true;
    Promise.resolve().then(() => { if (active) void readCard(); });
    return () => { active = false; cancelRead(); };
  }, [cardUrl]); // eslint-disable-line react-hooks/exhaustive-deps
  const currentIssue = card?.item;
  const independent = currentIssue && (["high", "critical"].includes(currentIssue.severity) || card.verification_policy[`issue_verify_${currentIssue.severity}`] === true);
  const allowed = card?.permissions.verify === true && currentIssue?.status === "verification" && !currentIssue.withdrawn_at && (!independent || (currentIssue.verifier_user_id === card.actor_id && currentIssue.owner_user_id !== card.actor_id));
  const disabled = busy || loading || mustRefresh || !allowed || !materialSelectionReady(card?.material_closure ?? null, selected) || (!!independent && !evidence.trim());
  return <form className="space-y-3 rounded-lg border border-success/30 bg-success/5 p-3" onSubmit={async event => {
    event.preventDefault();
    if (disabled || !card) return;
    setError(null);
    try {
      if (await onSubmit({ expected_updated_at: card.item.updated_at, ...(evidence.trim() ? { closure_evidence_ref: evidence.trim() } : {}), ...(card.material_closure.required ? { material_closures: selected! } : {}) })) onCancel();
    } catch (cause) {
      if (cause instanceof WorkItemRequestError && [401, 403, 404].includes(cause.status)) { setCard(null); setSelected(null); setMustRefresh(true); }
      else if (cause instanceof WorkItemRequestError && cause.status === 409) { setSelected(null); setMustRefresh(true); }
      else setMustRefresh(true);
      setError(cause instanceof Error ? cause.message : "未取得关闭回执，请保留输入并刷新原记录核对");
    }
  }}>
    <Button type="button" size="sm" variant="outline" disabled={busy || loading} onClick={refresh}>刷新当前关闭依据（保留填写内容）</Button>
    {loading && <p role="status">正在读取当前关闭依据…</p>}
    {card && <>
      <p className="text-sm font-medium">{card.item.title} · 本次关闭验证</p>
      {card.item.updated_at !== issue.updated_at && <p className="text-xs text-muted-foreground">原问题资料已更新，请按本次读取的记录重新核对关闭条件。</p>}
      <p className="whitespace-pre-wrap break-words text-sm">关闭条件：{card.item.closure_criteria || "未填写"}</p>
      <p className="whitespace-pre-wrap break-words text-sm">实际处理：{card.item.resolution || "未填写"}</p>
      <MaterialIssueClosureReview context={card.material_closure} selected={selected} onSelect={setSelected} disabled={busy || loading || mustRefresh || !allowed} linked={linked}/>
      {!allowed && <p className="text-sm text-destructive">当前身份或问题状态不满足原问题的关闭验证要求，请由具名验证人核对。</p>}
      <label className="block text-sm">关闭证据{independent ? "（必填）" : "（按实际验证记录填写）"}<textarea aria-label={`关闭证据 ${issue.title}`} className="mt-1 w-full rounded-md border bg-background p-2 text-sm" disabled={busy || loading} maxLength={2000} rows={2} required={!!independent} value={evidence} onChange={event => setEvidence(event.target.value)}/></label>
    </>}
    {mustRefresh && <p className="text-sm">请先刷新原记录再继续。物料来源需重新明确选择，已填写证据保留。</p>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    <div className="flex gap-2"><Button type="submit" disabled={disabled}>确认关闭</Button><Button type="button" variant="outline" disabled={busy} onClick={onCancel}>取消</Button></div>
  </form>;
}
