"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { PaiDocumentCard } from "@/components/pai-conversation";
import { Button } from "@/components/ui/button";
import type { WorkspaceTransport } from "@/lib/workspace-api";
import { proofClockCurrent } from "@/lib/proof-clock";
import { editableMaterial } from "@/lib/category-materials";
import { boundCandidateCommand, candidateLabels, matchesPendingCandidate, sameCandidateCommand, type CandidatePage, type CandidatePreview, type CandidateReceipt, type DomainCandidate, type DomainCommand, verificationPreparationCandidate, matchesPendingVerificationRequest } from "@/lib/domain-candidate";

import { WorkFollowupCandidate } from "./work-followup-candidate";
import { VerificationPreparationCandidate } from "./verification-preparation-candidate";
import { professionalAuthorityReads, professionalCommand, professionalCreate, professionalReads, validProfessionalReceipt, type ProfessionalCommand, type ProfessionalPreparation, type ProfessionalRequest } from "@/lib/verification-professional";

type Props = { categoryName?: string; materialContexts?: Record<string, { title: string; version?: number } | undefined>; editingMaterial?: string | null; api: WorkspaceTransport; categoryId: string; principalId: string; runId: string; eventSequence: number; disabled?: boolean; onEditMaterial?: (candidate: DomainCandidate) => void; onUnavailable?: () => void };
type Pending = { eventId: string; command: DomainCommand; kind?: "verification_preparation" | "verification_request" | "work_followup" };
function matchesAction(item: DomainCandidate | undefined, value: Pending, category: string, run: string) { return value.kind === "verification_request" ? matchesPendingVerificationRequest(item, value.command, value.eventId, category, run) : matchesPendingCandidate(item, value.command, value.eventId, category, run); }
const fields: Record<string, string> = {
  payload: "本次内容", product_name: "型号", variant_name: "变体", platform: "平台",
  operation: "办理类型",
  new_platform: "新建平台", code: "编号", name: "名称", title: "名称", description: "说明",
  compatibility: "兼容范围", platform_version: "平台版本", reason: "原因", effect: "本次影响",
  action: "动作", next_link_version: "新关联版本", expected_link_version: "原关联版本",
  question: "待决问题", owner_id: "负责人编号", due_date: "期限", brief: "说明",
  groups: "内容分组", items: "条目", ops: "修订", op: "动作", content: "内容", sources: "来源",
  source_refs: "来源引用", source_read_set: "读取依据", before: "原内容", after: "确认后的内容",
  item_id: "条目编号", base_version: "原版本", key: "条目键", value: "值", unit: "单位",
  lower: "下限", upper: "上限", availability: "可用情况", item_status: "条目状态",
  statement: "说明", quote: "原文片段", line: "行", expected_revision: "依据版本",
  parameter: "参数", parameter_id: "参数编号", parameter_version: "参数版本", version: "版本",
  condition_note: "条件", test_conditions: "测试条件", unknowns: "未知项", use_cases: "用途",
  requirements: "要求", constraints: "约束", exclusions: "排除范围", entry_kind: "立项入口",
  target_kind: "立项目标", applicable_variants: "适用变体", acceptance_criterion: "判据",
  verification_method: "验证方法", origin: "作者类型", writer_id: "作者编号", confirmed_by: "确认人",
  visibility: "可见范围", kind: "类型", text: "正文", questions: "待决问题",
  value_type: "数值类型", tolerance: "公差", text_value: "文本或选择值", modality: "要求强度",
  exceptions: "例外", nature: "要求性质", related_item_ids: "关联条目", status: "状态",
  answer: "答复", supersedes_item_id: "替代条目", type: "来源类型", id: "记录编号",
};
const values: Record<string, string> = { ...candidateLabels, attach: "关联", detach: "解除", unknown: "未知", ai_draft: "AI 草稿", known: "已知", upsert: "新增或修订", remove: "移除", new_product: "自主新品", customer_requirement: "客户需求", derivative: "派生迭代", private: "私有", category: "品类授权成员", section: "说明章节", option: "备选方案", spec: "规格要求", new: "新方案", do_nothing: "保持现状", worth_it: "立项价值", number: "数值", boolean: "是或否", decided: "已作产品决定", open: "待处理", human: "具名人员" };
const internal = new Set(["confirmation_token", "prepared_by_run_id", "candidate_digest", "prepared_event_id"]);
const enumerated = new Set(["operation", "action", "availability", "item_status", "origin", "kind", "visibility", "value_type", "nature", "status", "entry_kind", "target_kind", "type"]);
function display(value: unknown): unknown {
  if (!value || typeof value !== "object" || Array.isArray(value)) return value;
  return Object.fromEntries(Object.entries(value).filter(([key]) => !internal.has(key)).map(([key, entry]) => [key, key === "payload" ? display(entry) : entry]));
}
function detail(value: unknown, field?: string): ReactNode {
  if (value == null) return <span className="subtle">未确定</span>;
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "string") return field && enumerated.has(field) ? values[value] ?? value : value;
  if (typeof value === "number") return String(value);
  if (Array.isArray(value)) return value.length ? <ul className="space-y-2">{value.map((entry, index) => <li key={index}>{detail(entry, field)}</li>)}</ul> : <span className="subtle">无已登记内容</span>;
  if (typeof value === "object") return <dl className="candidate-fields">{Object.entries(value).map(([key, entry]) => <div key={key} className="min-w-0"><dt className="subtle">{fields[key] ?? key}</dt><dd className="whitespace-pre-wrap break-words">{detail(entry, key)}</dd></div>)}</dl>;
  return null;
}
function platformReview(preview: CandidatePreview) {
  const payload = preview.command.payload, review = preview.review;
  return <div className="space-y-2"><p>{String(review.product_name ?? "当前型号")}{typeof review.variant_name === "string" && ` / ${review.variant_name}`}</p>{detail(review.platform)}<p>动作：{payload.action === "detach" ? "解除关联" : "关联平台"}</p><p>兼容范围：{typeof payload.compatibility === "string" && payload.compatibility || "待确认"}</p><p>平台版本：{typeof payload.platform_version === "string" && payload.platform_version || "待确认"}</p><p>原因：{String(payload.reason ?? "未填写")}</p><p className="subtle">{String(review.effect ?? "核对本次保存范围。")}</p></div>;
}
function snapshotReview(review: Record<string, unknown>) {
  return <div className="space-y-2 break-words"><p className="font-medium">{String(review.title ?? "实际读取的来源")}</p><p className="subtle">{String(review.url ?? "")}</p><p>保存范围：{review.visibility === "private" ? "原私有上下文受众" : review.visibility === "category" ? "当前品类授权成员" : "范围待核对"}</p><p>{String(review.effect ?? "登记原研究快照，保留小Pai来源与本人确认。")}</p></div>;
}
const failureMessage = (failure: unknown) => {
  const message = (failure as Error)?.message;
  return message && !/^(Failed to fetch|Load failed)$/.test(message) ? message : "连接中断，请核对原请求。";
};

export function RunCandidates(props: Props) {
  return <CandidatePanel key={`${props.principalId}:${props.categoryId}:${props.runId}`} {...props} />;
}

export function syncCandidatePreviewDialog(dialog: HTMLDialogElement, mobile: boolean) {
  const modal = dialog.matches(":modal");
  if (mobile && !modal) {
    if (dialog.open) dialog.close();
    dialog.showModal();
  } else if (!mobile && (!dialog.open || modal)) {
    if (dialog.open) dialog.close();
    dialog.show();
  }
}

function CandidatePanel({ api, categoryId, categoryName, materialContexts, editingMaterial, principalId, runId, eventSequence, disabled, onEditMaterial, onUnavailable }: Props) {
  const storageKey = `pdos-next:run-candidate:${principalId}:${categoryId}:${runId}`;
  const [items, setItems] = useState<DomainCandidate[]>([]);
  const [cursor, setCursor] = useState<number | null>(null);
  const [preview, setPreview] = useState<(CandidatePreview & { eventId: string }) | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [receipt, setReceipt] = useState<CandidateReceipt | null>(null);
  const [busy, setBusy] = useState(false), [loading, setLoading] = useState(true), [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const [readVersion, setReadVersion] = useState(0), [requestNotice, setRequestNotice] = useState("");
  const [, setClock] = useState(0);
  const alive = useRef(true), lock = useRef(false), generation = useRef(0);
  const dialog = useRef<HTMLDialogElement>(null), trigger = useRef<HTMLElement | null>(null);
  function remember(value: Pending | null) {
    try { if (value) localStorage.setItem(storageKey, JSON.stringify(value)); else localStorage.removeItem(storageKey); } catch { /* In-memory original request remains available. */ }
  }
  function close() { dialog.current?.close(); setPreview(null); trigger.current?.focus(); }
  const load = useCallback(async (after = 0) => {
    const own = ++generation.current;
    setLoading(true);
    try {
      const page = await api<CandidatePage>(`v1/agent-runs/${runId}/candidates?after=${after}&page_size=50`);
      if (!alive.current || own !== generation.current) return;
      if (page.run_id !== runId || !Array.isArray(page.items)) throw new Error("候选范围尚未核对，请刷新。");
      setItems(previous => after ? [...previous, ...page.items.filter(row => !previous.some(old => old.event_id === row.event_id))] : page.items);
      setCursor(page.next_cursor); setError(""); setReadVersion(value => value + 1);
    } catch (failure) {
      if (!alive.current || own !== generation.current) return;
      setItems([]); setCursor(null); setError(failureMessage(failure));
      if ([401, 403].includes((failure as { status?: number }).status ?? 0)) {
        try { localStorage.removeItem(storageKey); } catch { /* Optional storage. */ }
        setPending(null); setPreview(null); setReceipt(null); dialog.current?.close();
        onUnavailable?.();
      }
    } finally { if (alive.current && own === generation.current) setLoading(false); }
  }, [api, runId, storageKey, onUnavailable]);
  useEffect(() => {
    alive.current = true;
    void Promise.resolve().then(() => {
      if (!alive.current) return;
      try {
        const saved = JSON.parse(localStorage.getItem(storageKey) ?? "null");
        if (saved && typeof saved.eventId === "string" && boundCandidateCommand(saved.command, categoryId, runId, saved.eventId, saved.kind)) setPending(saved);
      } catch { /* Optional local recovery. */ }
      setReady(true);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- Numeric request generation, not a DOM ref.
    return () => { alive.current = false; generation.current++; };
  }, [storageKey, categoryId, runId]);
  useEffect(() => { void Promise.resolve().then(() => { if (alive.current) return load(); }); }, [load, eventSequence]);
  useEffect(() => {
    if (!preview || !dialog.current) return;
    const media = window.matchMedia("(max-width:767px)");
    const element = dialog.current;
    const sync = () => syncCandidatePreviewDialog(element, media.matches);
    sync();
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, [preview]);
  useEffect(() => {
    if (!pending) return;
    const proof = items.find(item => item.event_id === pending.eventId
      && item.command_id === pending.command.command_id && item.idempotency_key === pending.command.idempotency_key
      && item.state === "adopted" && item.receipt?.operation === pending.command.operation)?.receipt;
    if (!proof) return;
    void Promise.resolve().then(() => {
      if (!alive.current) return;
      setReceipt(proof); setPending(null);
      try { localStorage.removeItem(storageKey); } catch { /* Server receipt remains authoritative. */ }
    });
  }, [items, pending, storageKey]);
  useEffect(() => {
    if (!preview || receipt) return;
    const timer = setInterval(() => setClock(value => value + 1), 1000);
    return () => clearInterval(timer);
  }, [preview, receipt]);
  const expired = !!preview && !proofClockCurrent("T1", preview.expires_at);
  const previewState = preview && items.find(item => item.event_id === preview.eventId)?.state;
  const invalidated = !!previewState && previewState !== "pending";
  async function prepare(item: DomainCandidate, element: HTMLElement) {
    if (lock.current || pending || !item.command || !boundCandidateCommand(item.command, categoryId, runId, item.event_id, item.kind)) return;
    lock.current = true; setBusy(true); setError(""); setReceipt(null); trigger.current = element;
    try {
      const result = await api<CandidatePreview>("v1/commands/preview", item.command);
      if (!boundCandidateCommand(result.command, categoryId, runId, item.event_id, item.kind) || !sameCandidateCommand(result.command, item.command) || !result.command.payload.confirmation_token || !result.review) throw new Error("预览与原候选不一致，请重新读取核对。");
      if (alive.current) setPreview({ ...result, eventId: item.event_id });
    } catch (failure) { if (alive.current) {
      if ([401, 403].includes((failure as { status?: number }).status ?? 0)) { setItems([]); setPreview(null); setReceipt(null); dialog.current?.close(); }
      setError(failureMessage(failure));
    } }
    finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  async function confirm(value: Pending) {
    if (lock.current) return;
    if (!matchesAction(items.find(item => item.event_id === value.eventId), value, categoryId, runId)) {
      setError("当前候选尚未核对，请刷新候选后再核对原请求。"); return;
    }
    lock.current = true; generation.current++; setBusy(true); setError(""); setPending(value); remember(value);
    let committed = false;
    try {
      const result = await api<CandidateReceipt>("v1/commands", value.command);
      if (!result.id || result.operation !== value.command.operation || !result.subject_id || value.command.operation === "research.snapshot.register" && result.subject_id !== value.command.payload.snapshot_id) throw new Error("保存结果尚未确认，请核对原请求。");
      if (value.kind === "verification_request" && !validProfessionalReceipt(result, value.command as unknown as ProfessionalCommand)) throw new Error("创建请求的回执尚未核对，请保留原请求。");
      if (!alive.current) return;
      committed = true; setPending(null); remember(null); setReceipt(result); await load();
    } catch (failure) {
      if (!alive.current) return;
      const status = (failure as { status?: number }).status;
      if (status && status >= 400 && status < 500 && status !== 408 && status !== 429) { setPending(null); remember(null); }
      if (status === 401 || status === 403) { setItems([]); setCursor(null); setPreview(null); setReceipt(null); dialog.current?.close(); }
      setError(committed ? `已保存；最新候选读取失败，可刷新。${failureMessage(failure)}` : failureMessage(failure));
    } finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  function createRequest(item: DomainCandidate, preparation: ProfessionalPreparation, product: { id: string; revision: number }, element: HTMLButtonElement) {
    if (lock.current || pending || disabled || busy || loading) return;
    try {
      const payload = professionalCreate(preparation, crypto.randomUUID(), "根据已确认的复验准备创建请求");
      const reads = professionalReads(preparation.required_source_read_set, professionalAuthorityReads(preparation.authority?.request_create));
      const command = { ...professionalCommand(product, "verification.request.create", payload, reads, crypto.randomUUID(), crypto.randomUUID()), category_id: categoryId } as DomainCommand;
      const value: Pending = { eventId: item.event_id, kind: "verification_request", command };
      if (!matchesAction(item, value, categoryId, runId)) throw new Error("实际准备与创建请求的固定范围不一致，请刷新。");
      trigger.current = element; dialog.current?.close(); setPreview(null); setReceipt(null); setRequestNotice(""); void confirm(value);
    } catch (failure) { setError(failureMessage(failure)); }
  }
  function requestRead(item: DomainCandidate, value: ProfessionalRequest) {
    if (pending?.kind !== "verification_request" || pending.eventId !== item.event_id) return;
    const payload = pending.command.payload;
    if (value.request_id !== payload.request_id || value.preparation_id !== payload.preparation_id
      || value.preparation_revision !== payload.expected_preparation_revision || value.preparation_sha256 !== payload.preparation_sha256) return;
    setPending(null); remember(null); setError(""); setRequestNotice("已读回复验请求，未再次提交。");
  }
  const canBrowse = ready && !disabled && !busy && !loading;
  const canAct = canBrowse && !pending;
  const pendingItem = pending ? items.find(item => item.event_id === pending.eventId) : undefined;
  const canReplay = !!pending && matchesAction(pendingItem, pending, categoryId, runId);
  if (ready && !loading && !items.length && !error && !pending && !preview && !receipt) return null;
  return <section className="space-y-3 border-t pt-4" aria-label="小Pai 待确认动作">
    <div className="flex items-center justify-end"><Button size="sm" variant="ghost" className="text-xs text-muted-foreground" disabled={busy || disabled} onClick={() => void load()}>刷新材料</Button></div>
    {error && <p role="alert" className="break-words">{error}</p>}
    {requestNotice && <p role="status" className="text-sm">{requestNotice}</p>}
    {pending && <div className="rounded-lg border p-3 space-y-2"><p>保存结果待核对，已保留原请求。可以刷新后继续恢复。</p>{!pendingItem && cursor !== null && <p className="subtle">原候选尚未读到，请继续查看更多候选以核对回执。</p>}<Button variant="outline" disabled={!canBrowse || !canReplay} onClick={() => void confirm(pending)}>核对原请求</Button></div>}
    {receipt && <div role="status" className="rounded-lg border p-3 space-y-2"><p>{candidateLabels[receipt.operation] ?? "候选"}已保存，回执可查。</p>{receipt.subject_type === "proposal" && <Link className="underline" href={`/categories/${categoryId}/proposals/${receipt.subject_id}`}>打开立项提案</Link>}<details><summary className="cursor-pointer">查看保存回执</summary><p className="subtle break-all mt-2">{receipt.id}</p></details></div>}
    {loading && <p className="subtle" role="status">正在核对候选与已保存回执…</p>}
    {!loading && items.length === 0 && !error && <p className="subtle">当前没有领域候选。</p>}
    {items.map(item => {
      if (item.kind === "work_followup") return <WorkFollowupCandidate key={item.event_id} api={api} categoryId={categoryId} principalId={principalId} candidate={item} disabled={!canAct} onRefresh={() => { void load(); }} onUnavailable={onUnavailable}/>;
      if (item.operation === "verification.preparation.record" && !verificationPreparationCandidate(item)) return <p key={item.event_id} role="alert">复验准备暂不可核对，请刷新。</p>;
      if (verificationPreparationCandidate(item) && (item.state === "pending" || item.state === "adopted")) return <VerificationPreparationCandidate key={item.event_id} api={api} categoryId={categoryId} candidate={item} pendingRequestId={pending?.eventId === item.event_id && pending.kind === "verification_request" ? String(pending.command.payload.request_id) : undefined} readVersion={readVersion} disabled={!canAct} onUnavailable={onUnavailable} onPreview={element => void prepare(item, element)} onCreate={(preparation, product, element) => createRequest(item, preparation, product, element)} onRequestRead={value => requestRead(item, value)}/>;
      const editable = !!onEditMaterial && (!!editableMaterial(item) || ["proposal.create", "proposal.item.patch"].includes(item.operation ?? ""));
      if (editable && (item.state === "pending" && item.command || item.state === "adopted" && item.receipt)) {
        const content = item.command?.payload.content as Record<string, unknown> | undefined;
        const label = candidateLabels[item.operation ?? ""] ?? "品类资料";
        const context = materialContexts?.[item.event_id];
        const title = String(context?.title ?? item.command?.payload.title ?? item.command?.payload.name ?? content?.model ?? content?.label ?? item.receipt?.result.title ?? item.receipt?.result.name ?? label);
        return <PaiDocumentCard key={item.event_id} title={title} metadata={`${categoryName || label} · ${item.state === "adopted" ? `已保存${context?.version ? ` · v${context.version}` : ""}` : pending?.eventId === item.event_id ? "保存结果待核对" : "小Pai 起草 · 待确认"}`} action={editingMaterial === item.event_id ? "返回编辑" : item.state === "adopted" ? "继续编辑" : "查看与编辑"} disabled={!canAct} onOpen={() => onEditMaterial!(item)} />;
      }
      return <article key={item.event_id} className="min-w-0 rounded-lg border p-3 space-y-2"><h4 className="font-medium">{candidateLabels[item.operation ?? ""] ?? "领域候选"}</h4>{item.state === "pending" && item.command ? <><p className="subtle">小Pai起草 · {pending?.eventId === item.event_id ? "保存结果待核对" : "尚未保存"}</p>{item.command.operation === "platform.link.create" ? <><p>{item.command.payload.action === "detach" ? "解除平台关联" : item.command.payload.new_platform ? "新建平台并关联" : "关联已有平台"}</p>{item.command.payload.new_platform && detail(item.command.payload.new_platform)}<p>兼容范围：{String(item.command.payload.compatibility ?? "待确认")}</p><p>平台版本：{String(item.command.payload.platform_version ?? "待确认")}</p><p>{String(item.command.payload.reason ?? "")}</p></> : item.command.operation === "research.snapshot.register" ? snapshotReview({ ...item.summary, effect: "登记本次实际读取的来源，保留原运行与确认回执。" }) : <p className="subtle">{String(item.command.payload.title ?? item.command.payload.name ?? (item.command.payload.content as Record<string, unknown> | undefined)?.model ?? (item.command.payload.content as Record<string, unknown> | undefined)?.label ?? "打开材料区，核对本次内容与来源。")}</p>}<Button variant="outline" disabled={!canAct || loading} onClick={event => { if (onEditMaterial && (editableMaterial(item) || ["proposal.create", "proposal.item.patch"].includes(item.operation ?? ""))) onEditMaterial(item); else void prepare(item, event.currentTarget); }}>{onEditMaterial && (editableMaterial(item) || ["proposal.create", "proposal.item.patch"].includes(item.operation ?? "")) ? "查看与编辑" : `核对并预览${candidateLabels[item.operation ?? ""] ?? "候选"}`}</Button></> : item.state === "adopted" && item.receipt ? <><p>已保存，可以继续完善。</p>{onEditMaterial && (editableMaterial(item) || ["proposal.create", "proposal.item.patch"].includes(item.operation ?? "")) && <Button size="sm" variant="outline" disabled={!canAct} onClick={() => onEditMaterial(item)}>继续编辑</Button>}{item.receipt.subject_type === "proposal" && <Link className="underline" href={`/categories/${categoryId}/proposals/${item.receipt.subject_id}`}>打开立项提案</Link>}<details><summary className="cursor-pointer">查看保存回执</summary><p className="subtle mt-2 break-all">{item.receipt.id}</p></details></> : <p className="subtle">{item.state === "cancelled" ? "运行已取消或撤回，此候选不能再采用。" : "对象或依据已变化，请重新核对或重新起草。"}</p>}</article>; })}
    {cursor !== null && <Button variant="outline" disabled={!canBrowse} onClick={() => void load(cursor)}>查看更多候选</Button>}
    <dialog ref={dialog} className="candidate-editor" data-candidate-preview="true" aria-label="确认小Pai候选" onCancel={event => { if (busy) event.preventDefault(); else close(); }}>
      {preview && <><header className="candidate-editor-heading"><div><h3>{candidateLabels[preview.command.operation]}</h3><p className="subtle">{receipt ? "已保存，可在旁边继续与小Pai完善" : "小Pai 起草 · 待你确认"}</p></div><Button size="sm" variant="ghost" disabled={busy} onClick={close}>收起材料</Button></header><div className="candidate-editor-body">{preview.command.operation === "platform.link.create" ? platformReview(preview) : preview.command.operation === "research.snapshot.register" ? snapshotReview(preview.review) : detail(display(preview.review))}{!receipt && <p className="subtle mt-4">如需调整内容，可在旁边告诉小Pai，重新起草后再核对。本次确认只保存当前固定候选。</p>}{error && <p role="alert" className="mt-4">{error}</p>}</div><footer className="candidate-editor-footer">{receipt ? <><span role="status">已保存</span>{receipt.subject_type === "proposal" && <Link className="underline" href={`/categories/${categoryId}/proposals/${receipt.subject_id}`}>继续编辑提案</Link>}<details><summary>保存回执</summary><p>{receipt.id}</p></details></> : <>{pending && <Button disabled={!canBrowse || !canReplay} onClick={() => void confirm(pending)}>核对原请求</Button>}{invalidated && <p role="alert">候选状态已变化，请重新核对。</p>}<p className="subtle">{expired ? "确认材料已过期，请重新打开核对。" : `确认有效至 ${new Date(preview.expires_at).toLocaleTimeString("zh-CN")}`}</p><Button disabled={!canAct || expired || invalidated} onClick={() => void confirm({ eventId: preview.eventId, command: preview.command, kind: items.find(item => item.event_id === preview.eventId)?.kind })}>确认保存</Button></>}</footer></>}

    </dialog>
  </section>;
}
