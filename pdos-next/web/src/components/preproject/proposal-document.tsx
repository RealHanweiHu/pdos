"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Dialog } from "radix-ui";
import { ArrowLeft, ArrowUpRight, ArrowClockwise, Sparkle, CheckCircle, WarningCircle } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { ProposalViews } from "@/components/preproject/proposal-views";
import { ProposalShare } from "@/components/preproject/proposal-share";
import type { MaterialContext } from "@/components/category-material-editor";
import { ProposalPai } from "@/components/preproject/proposal-pai";
import { ProposalHandoff } from "@/components/preproject/proposal-handoff";
import { ProposalSourceInspector } from "@/components/preproject/proposal-source-inspector";
import { ProposalVoices } from "@/components/preproject/proposal-voices";
import { ProposalItemTable } from "./proposal-item-table";
import { ProposalSpecEditor } from "./proposal-spec-editor";
import { proposalDraftPatches } from "@/lib/proposal-spec-editor";
import type { ProposalPatch, ProposalRowDraft, ProposalDrafts } from "@/lib/proposal-spec-editor";
import styles from "./proposal-document.module.css";
import type { G0Decision } from "@/lib/proposal-handoff";
import type { ProposalShareReceipt } from "@/components/preproject/proposal-share";
import { isProposalViewResponse, matchesProposalDocument } from "@/components/preproject/proposal-view-contracts";
import type { ProposalViewDocument, ProposalViewName, ProposalViewResponse } from "@/components/preproject/proposal-view-contracts";

type Item = { item_id: string; version: number; kind: string; content: Record<string, unknown>; source_refs: unknown[]; origin: string };
type Person = { id: string; name: string; reviewer_eligible: boolean; can_write: boolean };
type Disposition = { subject_type: string; subject_id: string; title: string };
type Proposal = {
  id: string; title: string; brief: string; owner_id: string; revision: number; status: string;
  visibility: string; private_source_count: number; items: Item[];
  document_identity: ProposalViewDocument;
  display_document: { title: string; brief: string; items: Item[]; entry_kind: "customer_request" | "new_product" | "derivative"; target_kind: "new_product" | "new_variant"; baseline_product_id?: string | null; baseline_definition_revision?: number | null };
  maturity: { spec_count: number; option_count: number; required_dispositions: Disposition[]; freeze_blockers: Item[] };
  submission: { id: string; reviewer_id: string; frozen_document: { items: Item[] } | null } | null;
  decision: G0Decision | null;
};
type Command = { command_id: string; idempotency_key: string; category_id: string; product_id: null; operation: string; expected_revision: number; source_read_set: unknown[]; payload: Record<string, unknown> };
type Prepared = { command: Command; review: { effect?: string; target_kind?: string; identity_name?: string; variant_kind?: string; dispositions?: { note: string; audience_added: boolean }[]; project_owner_audience_added?: boolean } };
type Assignment = { kind: string; owner_id: string; due_date: string };

const statuses: Record<string, string> = { draft: "草稿", returned: "已退回", in_review: "G0 评审中", approved: "已批准", rejected: "不立项" };

const variantNames: Record<string, string> = { customer: "客户变体", region: "地区变体", configuration: "配置变体" };
const documentTabs = [
  { id: "narrative", label: "提案" }, { id: "comparison", label: "规格对标" }, { id: "features", label: "功能配置" }, { id: "maturity", label: "定义成熟度" },
  { id: "voice", label: "用户声音" }, { id: "options", label: "方案对比" },
  { id: "questions", label: "待决问题" }, { id: "risks", label: "风险" },
  { id: "evidence", label: "证据与决定" }, { id: "decisions", label: "决策记录" },
] as const;
type DocumentTab = typeof documentTabs[number]["id"];
const sectionNames: Record<string, string> = { worth_it: "要解决的问题", target_customer_market_channel: "目标用户、市场与渠道", features_in_out: "做成什么样", certification_regions: "认证地区", launch_window: "上市窗口" };
const itemNames: Record<string, string> = { option: "方案对比", question: "待决问题", risk: "风险", assumption: "待验证假设", difference: "派生差异", commercial_target: "商业目标", decision_note: "取舍记录" };
const readableSources = (item: Item) => item.source_refs.filter((source): source is Record<string, unknown> => source !== null && typeof source === "object" && !Array.isArray(source));


async function api<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`/api/v1/${path}`, {
    method: body === undefined ? "GET" : "POST", cache: "no-store", signal,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const value = await response.json();
  if (!response.ok) throw Object.assign(new Error(value.message ?? "暂未取得当前结果，请重试原操作。"), { status: response.status });
  return value;
}

function ItemEditor({ item: currentItem, save, busy, drafts = {}, onDraft }: ProposalDrafts & { item: Item; save: (item: Item, content: Record<string, unknown>) => Promise<boolean>; busy: boolean }) {
  const entry = drafts[currentItem.item_id], item = entry?.item ?? currentItem;
  const field = item.kind === "section" ? "text" : "name";
  const text = entry?.values.text ?? String(item.content[field] ?? "");
  const stale = item.version !== currentItem.version;
  return <form onSubmit={async event => { event.preventDefault(); if (await save(item, { ...item.content, [field]: text })) onDraft?.(item.item_id, null); }} className="space-y-2">
    <label className="block text-sm">{item.kind === "section" ? "叙述" : "方案名称"}<textarea disabled={busy} required value={text} onChange={event => onDraft?.(item.item_id, { item, values: { text: event.target.value } })} /></label>
    {stale && <p>版本已更新，草稿已保留；取消后重新编辑。</p>}
    <Button size="sm" variant="outline" disabled={busy || stale}>保存此条</Button>{entry && <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => onDraft?.(item.item_id, null)}>取消编辑</Button>}
  </form>;
}

export function ProposalDocument(props: { categoryId: string; proposalId: string; embedded?: boolean; onContextChange?: (context: MaterialContext | undefined) => void }) {
  return <ScopedProposalDocument key={`${props.categoryId}:${props.proposalId}`} {...props} />;
}

function ScopedProposalDocument({ categoryId, proposalId, embedded = false, onContextChange }: { categoryId: string; proposalId: string; embedded?: boolean; onContextChange?: (context: MaterialContext | undefined) => void }) {
  const root = `categories/${categoryId}`;
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [documentReady, setDocumentReady] = useState(false);
  const [documentError, setDocumentError] = useState("");
  const [readVersion, setReadVersion] = useState(0);
  const [selectedView, setSelectedView] = useState<ProposalViewName>("spec-benchmark");
  const [documentTab, setDocumentTab] = useState<DocumentTab>("narrative");
  const [paiOpen, setPaiOpen] = useState(false);
  const [mobileView, setMobileView] = useState<"document" | "pai">("document");
  const [reviewOpen, setReviewOpen] = useState(false);
  const [viewResult, setViewResult] = useState<ProposalViewResponse | null>(null);
  const [viewLoading, setViewLoading] = useState(true);
  const [viewError, setViewError] = useState("");
  const live = useRef(true);
  const initialized = useRef(false);
  const documentRequest = useRef(0);
  const viewRequest = useRef(0);
  const documentController = useRef<AbortController | null>(null);
  const viewController = useRef<AbortController | null>(null);
  const [people, setPeople] = useState<Person[]>([]);
  const [me, setMe] = useState("");
  const [error, setError] = useState("");
  const [shareReceipt, setShareReceipt] = useState<ProposalShareReceipt | null>(null);
  const [busy, setBusy] = useState(false);
  const [patchRequest, setPatchRequest] = useState<{ principalId: string; command: Command } | null>(null);
  const patchLock = useRef(false);
  const [saveNotice, setSaveNotice] = useState("");
  const [drafts, setDrafts] = useState<Record<string, ProposalRowDraft>>({});
  const draftPrincipal = useRef("");
  const onDraft = (id: string, value: ProposalRowDraft | null) => setDrafts(old => { const next = { ...old }; if (value) next[id] = value; else delete next[id]; return next; });
  const [prepared, setPrepared] = useState<Prepared | null>(null);
  const [reviewer, setReviewer] = useState("");
  const [alternativeReason, setAlternativeReason] = useState("");
  const [outcome, setOutcome] = useState("approved");
  const [rationale, setRationale] = useState("");
  const [selectedOption, setSelectedOption] = useState("");
  const [projectName, setProjectName] = useState("");
  const [projectOwner, setProjectOwner] = useState("");
  const [identityName, setIdentityName] = useState("");
  const [variantKind, setVariantKind] = useState("configuration");
  const [dispositions, setDispositions] = useState<Record<string, Assignment>>({});
  const reviewTrigger = useRef<HTMLButtonElement>(null);
  const loadDocument = useCallback(() => {
    if (!live.current) return;
    const request = ++documentRequest.current;
    documentController.current?.abort();
    const controller = new AbortController();
    documentController.current = controller;
    return Promise.all([
        api<Proposal>(`${root}/proposals/${proposalId}`, undefined, controller.signal),
        api<{ items: Person[] }>(`${root}/proposals/${proposalId}/participants`, undefined, controller.signal),
        api<{ principal_id: string }>("session", undefined, controller.signal),
      ]).then(([value, participants, session]) => {
      if (!live.current || controller.signal.aborted || request !== documentRequest.current) return;
      const identity = value.document_identity;
      if (value.id !== proposalId || !identity || identity.proposal_id !== proposalId
        || !Number.isSafeInteger(identity.revision) || identity.revision < 1
        || typeof identity.document_digest !== "string" || !identity.document_digest || !["frozen", "current"].includes(identity.document_mode)
        || (identity.document_mode === "frozen" ? typeof identity.submission_id !== "string" : identity.submission_id !== null)
        || !value.display_document || !Array.isArray(value.display_document.items)
        || typeof value.display_document.title !== "string" || typeof value.display_document.brief !== "string"
        || !["customer_request", "new_product", "derivative"].includes(value.display_document.entry_kind)
        || !["new_product", "new_variant"].includes(value.display_document.target_kind)
        || (value.status === "in_review" && value.submission?.reviewer_id === session.principal_id
          && (!value.submission.frozen_document || identity.document_mode !== "frozen"))) {
        throw new Error("当前接口未提供可读的提案文档身份，请重新读取。");
      }
      if (draftPrincipal.current && draftPrincipal.current !== session.principal_id) { setDrafts({}); setPatchRequest(null); }
      draftPrincipal.current = session.principal_id;
      setProposal(value); setPeople(participants.items); setMe(session.principal_id);
      if (!initialized.current) {
        setProjectName(value.display_document.title); setProjectOwner(value.owner_id); setIdentityName(value.display_document.title);
        initialized.current = true;
      }
      // A frozen identity can remain unchanged after source withdrawal or ACL changes.
      setReadVersion(previous => previous + 1);
      setDocumentReady(true);
    }).catch(failure => {
      if (live.current && !controller.signal.aborted && request === documentRequest.current) {
        controller.abort();
        setProposal(null); setPeople([]); setDocumentError((failure as Error).message);
        if ([401, 403].includes((failure as { status?: number }).status ?? 0)) { setDrafts({}); setPatchRequest(null); }
        setViewResult(null); setViewLoading(false);
      }
    });
  }, [root, proposalId]);
  const reload = useCallback(() => {
    if (!live.current) return Promise.resolve();
    ++viewRequest.current; viewController.current?.abort();
    setDocumentReady(false); setDocumentError("");
    setViewResult(null); setViewLoading(true); setViewError("");
    return loadDocument();
  }, [loadDocument]);
  useEffect(() => {
    live.current = true;
    void loadDocument();
    return () => {
      live.current = false;
      documentController.current?.abort(); viewController.current?.abort();
    };
  }, [loadDocument]);
  useEffect(() => {
    if (!documentReady || !proposal) return;
    const request = ++viewRequest.current;
    const controller = new AbortController();
    viewController.current?.abort(); viewController.current = controller;
    const identity = proposal.document_identity;
    const query = new URLSearchParams({ proposal_id: proposalId });
    void api<unknown>(`${root}/views/${selectedView}?${query}`, undefined, controller.signal).then(value => {
      if (!live.current || controller.signal.aborted || request !== viewRequest.current) return;
      if (!isProposalViewResponse(value) || value.view !== selectedView || !matchesProposalDocument(value, identity)) {
        throw new Error("视图与当前提案文档不一致，请刷新文档与视图。");
      }
      setViewResult(value);
    }).catch(failure => {
      if (live.current && !controller.signal.aborted && request === viewRequest.current) {
        setViewResult(null); setViewError((failure as Error).message);
      }
    }).finally(() => {
      if (live.current && !controller.signal.aborted && request === viewRequest.current) setViewLoading(false);
    });
    return () => controller.abort();
  }, [documentReady, proposal, readVersion, selectedView, root, proposalId]);
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const refreshVisible = () => {
      if (document.visibilityState !== "visible" || busy) return;
      clearTimeout(timer);
      timer = setTimeout(() => { void reload(); }, 0);
    };
    window.addEventListener("focus", refreshVisible);
    document.addEventListener("visibilitychange", refreshVisible);
    return () => {
      clearTimeout(timer);
      window.removeEventListener("focus", refreshVisible);
      document.removeEventListener("visibilitychange", refreshVisible);
    };
  }, [reload, busy]);
  function changeView(next: ProposalViewName) {
    if (next === selectedView) return;
    ++viewRequest.current; viewController.current?.abort();
    setViewResult(null); setViewError(""); setViewLoading(true); setSelectedView(next);
  }
  function command(operation: string, payload: Record<string, unknown>): Command {
    return { command_id: crypto.randomUUID(), idempotency_key: crypto.randomUUID(), operation,
      category_id: categoryId, product_id: null, expected_revision: proposal!.revision,
      source_read_set: [], payload };
  }
  async function preview(operation: string, payload: Record<string, unknown>) {
    setBusy(true); setError("");
    try { const value = await api<Prepared>(`${root}/commands/preview`, command(operation, payload)); if (live.current) setPrepared(value); }
    catch (failure) { if (live.current) setError((failure as Error).message); }
    finally { if (live.current) setBusy(false); }
  }
  const patchKey = `pdos-next:proposal-edit:${me}:${categoryId}:${proposalId}`;
  useEffect(() => {
    if (!me) return;
    try {
      const value = JSON.parse(localStorage.getItem(patchKey) ?? "null");
      if (value?.principalId === me && value.command?.category_id === categoryId && value.command?.operation === "proposal.item.patch" && value.command?.payload?.proposal_id === proposalId && Array.isArray(value.command.payload.ops) && typeof value.command.command_id === "string" && typeof value.command.idempotency_key === "string") {
        void Promise.resolve().then(() => { if (live.current) setPatchRequest(value); });
      }
    } catch { /* No write is attempted until the explicit save can retain its request. */ }
  }, [me, categoryId, proposalId, patchKey]);
  async function savePatch(request: { principalId: string; command: Command }): Promise<boolean> {
    if (patchLock.current || request.principalId !== me || request.command.category_id !== categoryId || request.command.payload.proposal_id !== proposalId) return false;
    patchLock.current = true; setBusy(true); setError(""); setSaveNotice("");
    try {
      localStorage.setItem(patchKey, JSON.stringify(request));
      setPatchRequest(request);
      const receipt = await api<{ id: string; operation: string }>(`${root}/commands`, request.command);
      if (!receipt.id || receipt.operation !== "proposal.item.patch") throw new Error("保存回执未完整取得，请核对原请求。");
      if (!live.current) return false;
      try { localStorage.removeItem(patchKey); } catch { /* A retained successful command is safe to reconcile with its original idempotency key. */ }
      const savedIds = new Set((request.command.payload.ops as ProposalPatch[]).map(op => op.item_id));
      setDrafts(old => Object.fromEntries(Object.entries(old).filter(([id]) => !savedIds.has(id))));
      setPatchRequest(null); setSaveNotice("已保存，可继续与小Pai完善。");
      await reload();
      return true;
    } catch (failure) {
      if (live.current) {
        const status = (failure as { status?: number }).status;
        if (status && status >= 400 && status < 500 && ![408, 429].includes(status)) {
          setPatchRequest(null); try { localStorage.removeItem(patchKey); } catch { /* Same original request remains server-guarded. */ }
        }
        if (status === 401 || status === 403) { setProposal(null); setPeople([]); setDrafts({}); setSaveNotice(""); setDocumentReady(false); }
        setError((failure as Error).message);
      }
      return false;
    } finally { patchLock.current = false; if (live.current) setBusy(false); }
  }
  async function mutate(ops: ProposalPatch[]) {
    if (!ops.length || !documentReady || !proposal || patchRequest || busy || prepared) return false;
    return savePatch({ principalId: me, command: command("proposal.item.patch", { proposal_id: proposalId, ops }) });
  }
  async function patch(item: Item, content: Record<string, unknown>) {
    return mutate([{ op: "upsert", item_id: item.item_id, base_version: item.version, kind: item.kind, content, source_refs: item.source_refs }]);
  }
  useEffect(() => {
    onContextChange?.(proposal && documentReady ? { kind: "proposal", id: proposalId, title: proposal.display_document.title, version: proposal.revision, draft: { unsaved_items: drafts, document: proposal.display_document } } : undefined);
  }, [proposal, documentReady, drafts, proposalId, onContextChange]);
  const owner = proposal?.owner_id === me;
  const editable = documentReady && !patchRequest && people.some(person => person.id === me && person.can_write) && ["draft", "returned"].includes(proposal?.status ?? "");
  const deciding = proposal?.status === "in_review" && proposal.submission?.reviewer_id === me;
  const frozenAvailable = !!proposal?.submission?.frozen_document;
  const docItems = proposal?.display_document.items ?? [];
  const options = docItems.filter(item => item.kind === "option");
  const variantTarget = proposal?.display_document.target_kind === "new_variant";
  const tabItems = docItems.filter(item => documentTab === "options" ? item.kind === "option" : documentTab === "questions" ? item.kind === "question" : documentTab === "risks" ? item.kind === "risk" : documentTab === "decisions" ? item.kind === "decision_note" : !["spec", "option", "question", "risk", "decision_note"].includes(item.kind));
  return <div className={styles.page} data-embedded={embedded} data-pai-open={paiOpen} data-mobile-view={mobileView}>
    {!embedded && <div className={styles.toolbar}><Link href={`/?area=category&category=${categoryId}&focus=proposals`} className={styles.backLink}><ArrowLeft size={14}/>全部提案</Link><Button type="button" size="icon" variant="ghost" aria-label="刷新提案" title="刷新提案" disabled={busy} onClick={() => { void reload(); }}><ArrowClockwise size={14}/></Button></div>}
    {documentError && <p role="alert">{documentError}</p>}
    {error && <div role="alert" className="panel flex items-start gap-2"><WarningCircle size={20} /><span>{error}</span></div>}
    {saveNotice && <p role="status" className={styles.saveNotice}>{saveNotice}</p>}
    {patchRequest?.principalId === me && <div className={styles.recovery} role="status"><p>保存结果尚待核对，原请求与编辑内容已保留。</p><Button size="sm" variant="outline" disabled={busy} onClick={() => void savePatch(patchRequest)}>按原请求核对保存结果</Button></div>}
    {proposal && documentReady && <>
      <header className={styles.documentHeader}><div><h1>{proposal.display_document.title}</h1><p className={styles.meta}>{{ customer_request: "客户需求", new_product: "自主新品", derivative: "派生迭代" }[proposal.display_document.entry_kind]} · {variantTarget ? "新变体" : "新型号"}</p></div><div className={styles.headerActions}>{proposal.decision?.project_id ? <Button asChild size="sm"><Link href={`/?area=cockpit&category=${categoryId}&project=${proposal.decision.project_id}`}>进入项目<ArrowUpRight size={14}/></Link></Button> : <Button type="button" size="sm" onClick={() => { setReviewOpen(true); requestAnimationFrame(() => document.getElementById("proposal-g0-review")?.scrollIntoView({ block: "nearest" })); }}>{proposal.status === "in_review" ? "查看评审" : "提交评审"}</Button>}</div></header>
      <div className={styles.documentMeta}><span className={styles.status} data-state={proposal.status}>{statuses[proposal.status] ?? proposal.status}</span><span>v{proposal.revision}</span><span>负责人 {people.find(person => person.id === proposal.owner_id)?.name ?? "未取得姓名"}</span><span>{proposal.visibility === "private" ? "私有提案" : "已共享"}{proposal.private_source_count > 0 ? " · 含私有来源" : ""}</span>{!embedded && <button type="button" onClick={() => { setPaiOpen(true); setMobileView("pai"); }}>与小Pai{editable ? "完善" : "讨论"}<ArrowUpRight size={13}/></button>}</div>
      {proposal.status === "approved" && <p className={styles.frozen}>立项时的版本已固定。后续产品定义修订在项目中继续。</p>}
      {Object.keys(drafts).length > 0 && <div className={styles.draftBar}><span>有 {Object.keys(drafts).length} 条未保存编辑</span><Button size="sm" disabled={!editable || busy || !!prepared || !!patchRequest} onClick={() => { try { void mutate(proposalDraftPatches(drafts, docItems)); } catch (failure) { setError((failure as Error).message); } }}>保存修订</Button></div>}
      <nav className={styles.tabs} aria-label="提案文档视图">{documentTabs.filter(tab => ["narrative", "comparison", "features", "maturity", "evidence"].includes(tab.id)).map(tab => <button type="button" key={tab.id} className={styles.chip} aria-pressed={documentTab === tab.id} onClick={() => { setDocumentTab(tab.id); if (["comparison", "features", "maturity"].includes(tab.id)) changeView(tab.id === "features" ? "feature-config" : tab.id === "maturity" ? "definition-maturity" : "spec-benchmark"); }}>{tab.label}</button>)}<details className={styles.moreViews}><summary>更多</summary><div>{documentTabs.filter(tab => !["narrative", "comparison", "features", "maturity", "evidence"].includes(tab.id)).map(tab => <button type="button" key={tab.id} aria-pressed={documentTab === tab.id} onClick={event => { setDocumentTab(tab.id); event.currentTarget.closest("details")?.removeAttribute("open"); }}>{tab.label}</button>)}</div></details></nav>
    </>}
    <div className={styles.mobileSwitch} role="group" aria-label="提案工作区">{(["document", "pai"] as const).map(view => <Button key={view} size="sm" variant={mobileView === view ? "secondary" : "ghost"} aria-pressed={mobileView === view} onClick={() => { setMobileView(view); if (view === "pai") setPaiOpen(true); }}>{view === "document" ? "编辑提案" : "与小Pai对话"}</Button>)}</div>
    <div className={styles.layout} data-mobile-view={mobileView}>
    {!proposal || !documentReady ? <p role="status">{documentError ? "请核对当前会话与提案受众后重新读取。" : "正在读取提案…"}</p> : <div className={styles.document}>
      <div className={styles.documentContent}>
        {documentTab === "narrative" && <p className={styles.brief}>{proposal.display_document.brief}</p>}
        {deciding && <p className="panel text-sm">{frozenAvailable ? "当前评审的是提交时的固定副本。未知规格可带入立项，须逐条明确后续处置。" : "提交副本的来源不在当前可读范围，请核对权限后刷新。"}</p>}
        {!["comparison", "features", "maturity", "voice", "evidence", "options", "questions"].includes(documentTab) && tabItems.map(item => <section key={`${item.item_id}:${item.version}`} className={item.kind === "section" ? styles.narrative : styles.itemCard}>
          <div className={styles.itemHeading}><h2>{item.kind === "section" ? sectionNames[String(item.content.key)] ?? "提案内容" : itemNames[item.kind] ?? "提案内容"}</h2><span>{item.origin === "ai_draft" ? "AI 草稿" : "人工记录"}</span></div>
          {item.kind === "question" ? <><p>{String(item.content.question)}</p><p className={styles.meta}>负责人：{people.find(person => person.id === item.content.owner_id)?.name ?? "提案受众"} · {String(item.content.due_date)} · {item.content.status === "carried" ? "已转入项目" : item.content.status === "answered" ? "已答复" : "待答复"}</p></> : <><p className={styles.itemText}>{String(item.content.text ?? item.content.name ?? item.content.statement ?? item.content.summary ?? "")}</p>{editable && ["section", "option"].includes(item.kind) && <details className={styles.inlineEditor}><summary>编辑此条</summary><ItemEditor item={item} drafts={drafts} onDraft={onDraft} busy={busy || !!prepared || !!patchRequest} save={patch}/></details>}</>}
          <p className={styles.itemVersion}>第 {item.version} 版 · {item.source_refs.length} 个来源</p>
        </section>)}
        {documentTab === "narrative" && <ProposalSpecEditor items={docItems.filter(item => item.kind === "spec")} categoryId={categoryId} editable={editable} drafts={drafts} onDraft={onDraft} busy={busy || !!prepared || !!patchRequest} mutate={mutate}/>}
        {(["option", "question"] as const).filter(kind => documentTab === "narrative" || documentTab === (kind === "option" ? "options" : "questions")).map(kind => <ProposalItemTable key={kind} onAssignQuestion={(item, content) => { void preview("proposal.question.create", { proposal_id: proposalId, expected_revision: proposal.revision, question: content.question, owner_id: content.owner_id, due_date: content.due_date, related_item_ids: content.related_item_ids ?? [], supersedes_item_id: item.item_id, status: "open", answer: null }); }} kind={kind} items={docItems.filter(item => item.kind === kind)} people={people} editable={editable} drafts={drafts} onDraft={onDraft} busy={busy || !!prepared || !!patchRequest} mutate={mutate}/>)}

        {documentTab === "voice" && <ProposalVoices categoryId={categoryId} proposalId={proposalId} document={proposal.document_identity} readVersion={readVersion}/>}
        {["decisions", "evidence"].includes(documentTab) && proposal.decision && <section className={styles.itemCard}><h2>具名 G0 决定</h2><p>{proposal.decision.rationale}</p><p className={styles.meta}>{people.find(person => person.id === proposal.decision?.decided_by)?.name ?? "原签发人"}{proposal.decision.decided_at && <> · <time dateTime={proposal.decision.decided_at}>{new Date(proposal.decision.decided_at).toLocaleString()}</time></>}</p></section>}
        {documentTab === "evidence" && <section className={styles.panel}><header className={styles.panelHeading}><h2>证据引用</h2><span>按提案条目保留来源身份与版本</span></header>{docItems.filter(item => item.source_refs.length > 0).map(item => <div className={styles.evidenceRow} key={item.item_id}><h3>{String(item.content.parameter ?? item.content.name ?? sectionNames[String(item.content.key)] ?? itemNames[item.kind] ?? "提案条目")}</h3><ProposalSourceInspector sources={readableSources(item)}/></div>)}{!docItems.some(item => item.source_refs.length > 0) && <p className={styles.empty}>当前条目未提供可读来源引用。</p>}</section>}
        {!["narrative", "comparison", "features", "maturity", "voice", "evidence", "options", "questions"].includes(documentTab) && tabItems.length === 0 && !(["decisions", "evidence"].includes(documentTab) && proposal.decision) && <p className={styles.empty}>当前提案没有{documentTabs.find(tab => tab.id === documentTab)?.label}条目。</p>}
        <div hidden={!["comparison", "features", "maturity"].includes(documentTab)}><ProposalViews navigation={false} onViewChange={changeView} view={selectedView} result={viewResult} document={proposal.document_identity} people={people} loading={viewLoading} error={viewError} onRetry={() => { void reload(); }}/></div>

      </div>
      <details id="proposal-g0-review" className={styles.reviewPanel} open={reviewOpen} onToggle={event => setReviewOpen(event.currentTarget.open)}><summary>G0 评审与项目承接</summary><div className={styles.reviewBody}>
        {editable && owner && <form className="panel space-y-3" onSubmit={event => { event.preventDefault(); preview("proposal.g0.submit", { proposal_id: proposalId, expected_revision: proposal.revision, reviewer_id: reviewer, no_alternative_reason: alternativeReason || null }); }}>
          <h2 className="font-semibold">提交 G0 立项评审</h2><label className="block text-sm">具名评审人<select required value={reviewer} onChange={event => setReviewer(event.target.value)}><option value="">选择产品经理</option>{people.filter(person => person.reviewer_eligible).map(person => <option key={person.id} value={person.id}>{person.name}</option>)}</select></label>
          {options.length < 2 && <label className="block text-sm">没有替代方案的理由<textarea required value={alternativeReason} onChange={event => setAlternativeReason(event.target.value)} /></label>}
          <Button ref={reviewTrigger} disabled={busy || !!prepared || !reviewer}>核对提交内容</Button><p className="text-xs text-muted-foreground">评审人须有品类产品管理权限；试点租户支持负责人本人具名评审。</p>
        </form>}
        {deciding && frozenAvailable && <form className="panel space-y-3" onSubmit={event => {
          event.preventDefault();
          preview("proposal.g0.decide", { proposal_id: proposalId, submission_id: proposal.submission!.id,
            expected_revision: proposal.revision, outcome, rationale, selected_option_item_id: selectedOption || null,
            ...(outcome === "approved" ? { project: { name: projectName, owner_id: projectOwner }, new_identity: { name: identityName, ...(variantTarget ? { variant_kind: variantKind } : {}) } } : {}),
            dispositions: outcome === "approved" ? proposal.maturity.required_dispositions.map(item => ({
              subject_type: item.subject_type, subject_id: item.subject_id, note: item.title, ...dispositions[item.subject_id],
            })) : [] });
        }}>
          <h2 className="font-semibold">具名 G0 决定</h2><label className="block text-sm">决定<select value={outcome} onChange={event => setOutcome(event.target.value)}><option value="approved">批准立项</option><option value="returned">退回完善</option><option value="rejected">不立项</option></select></label>
          <label className="block text-sm">理由<textarea required value={rationale} onChange={event => setRationale(event.target.value)} /></label>
          {outcome === "approved" && <>
            <label className="block text-sm">{variantTarget ? "新变体名称" : "新型号名称"}<input required value={identityName} onChange={event => setIdentityName(event.target.value)} /></label>
            {variantTarget && <label className="block text-sm">变体类别<select value={variantKind} onChange={event => setVariantKind(event.target.value)}><option value="customer">客户变体</option><option value="region">地区变体</option><option value="configuration">配置变体</option></select></label>}
            {options.length > 0 && <label className="block text-sm">选定方案<select required value={selectedOption} onChange={event => setSelectedOption(event.target.value)}><option value="">选择方案</option>{options.map(item => <option key={item.item_id} value={item.item_id}>{String(item.content.name)}</option>)}</select></label>}
            <label className="block text-sm">项目名称<input required value={projectName} onChange={event => setProjectName(event.target.value)} /></label><label className="block text-sm">项目负责人<select required value={projectOwner} onChange={event => setProjectOwner(event.target.value)}>{people.map(person => <option key={person.id} value={person.id}>{person.name}</option>)}</select></label>
            {proposal.maturity.required_dispositions.map(item => {
              const value = dispositions[item.subject_id] ?? { kind: "task", owner_id: "", due_date: "" };
              const change = (key: string, next: string) => setDispositions(previous => ({ ...previous, [item.subject_id]: { ...value, [key]: next } }));
              return <fieldset key={item.subject_id} className="space-y-2 rounded-md border p-3"><legend className="text-sm">{item.title}</legend><label className="block text-sm">处置<select value={value.kind} onChange={event => change("kind", event.target.value)}><option value="task">项目任务</option><option value="risk">项目风险</option></select></label><label className="block text-sm">负责人<select required value={value.owner_id} onChange={event => change("owner_id", event.target.value)}><option value="">选择品类成员</option>{people.map(person => <option key={person.id} value={person.id}>{person.name}</option>)}</select></label><label className="block text-sm">期限<input required type="date" value={value.due_date} onChange={event => change("due_date", event.target.value)} /></label></fieldset>;
            })}
          </>}
          <Button ref={reviewTrigger} disabled={busy || !!prepared}>核对具名决定</Button>
        </form>}
        {proposal.decision && <section className="panel space-y-2"><h2 className="flex items-center gap-2 font-semibold"><CheckCircle />决定记录</h2><p className="text-sm">{proposal.decision.rationale}</p><p className="subtle">具名评审人：{people.find(person => person.id === proposal.decision?.decided_by)?.name ?? "原签发人"}{proposal.decision.decided_at && <> · <time dateTime={proposal.decision.decided_at}>{new Date(proposal.decision.decided_at).toLocaleString()}</time></>}</p></section>}
        {proposal.decision?.outcome === "approved" && <ProposalHandoff categoryId={categoryId} proposalId={proposalId} decision={proposal.decision} />}
        {!deciding && !(editable && owner) && !proposal.decision && <p className={styles.empty}>当前没有本人可办理的 G0 动作。</p>}
      </div></details>
      </div>}
      {!embedded && proposal && documentReady && <aside className={styles.metadata}><h2>提案信息</h2><dl><dt>范围</dt><dd>{proposal.visibility === "private" ? "仅提案受众" : "当前共享受众"}</dd><dt>版本</dt><dd>v{proposal.revision}</dd><dt>评审人</dt><dd>{people.find(person => person.id === (proposal.decision?.decided_by ?? proposal.submission?.reviewer_id))?.name ?? "尚未指定"}</dd></dl><h2>当前依据</h2><p>{docItems.reduce((total,item) => total + item.source_refs.length, 0)} 个条目来源 · 保留原始版本</p><button type="button" onClick={() => setDocumentTab("evidence")}>查看依据与版本<ArrowUpRight size={13}/></button></aside>}

    </div>
    {!embedded && proposal && me && <aside className={styles.assistant} hidden={!paiOpen}><ProposalPai key={`${me}:${categoryId}:${proposalId}`} categoryId={categoryId} proposalId={proposalId} principalId={me} proposalTitle={proposal.display_document.title} onClose={() => { setPaiOpen(false); setMobileView("document"); }} materialContext={{ kind: "proposal", id: proposalId, title: proposal.display_document.title, version: proposal.revision, draft: { unsaved_items: drafts, document: proposal.display_document } }}/></aside>}
    {!embedded && !paiOpen && <button type="button" className={styles.paiFloating} aria-label="打开当前提案的小Pai" onClick={() => { setPaiOpen(true); setMobileView("pai"); }}><Sparkle size={22}/></button>}
    {owner && <details className={styles.reviewPanel}><summary>共享与撤回</summary><ProposalShare categoryId={categoryId} proposalId={proposalId} principalId={me}
      onChanged={receipt => { setShareReceipt(receipt); return reload(); }} /></details>}
    {shareReceipt && !owner && <p role="status" className="panel text-sm">{shareReceipt.operation === "proposal.share" ? "共享成功" : "事实已撤回，引用条目值保留"} · 回执：{shareReceipt.id}</p>}
    {prepared && documentReady && <Dialog.Root open onOpenChange={open => { if (!open && !busy) setPrepared(null); }}><Dialog.Portal><Dialog.Overlay className="fixed inset-0 z-50 bg-black/40" /><Dialog.Content onCloseAutoFocus={event => { event.preventDefault(); reviewTrigger.current?.focus(); }} onEscapeKeyDown={event => { if (busy) event.preventDefault(); }} onPointerDownOutside={event => { if (busy) event.preventDefault(); }} className="fixed left-1/2 top-1/2 z-50 max-h-[85vh] w-[calc(100%-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg border bg-background p-6 shadow-lg">
      <Dialog.Title className="text-lg font-semibold">{prepared.command.operation === "proposal.g0.decide" ? "确认具名 G0 决定" : "确认提交 G0"}</Dialog.Title><Dialog.Description className="my-4">{prepared.review.effect ?? "提交副本将锁定，评审人获得此提案读取权限。"}</Dialog.Description>
      {error && <p role="alert" className="mb-4 text-sm text-destructive">{error}</p>}
      {prepared.command.operation === "proposal.g0.submit" && <p className="mb-4 text-sm">评审人：{people.find(person => person.id === prepared.command.payload.reviewer_id)?.name}</p>}
      {prepared.command.operation === "proposal.question.create" && <div className="space-y-2 mb-4 text-sm"><p>{String(prepared.command.payload.question)}</p><p>负责人：{people.find(person => person.id === prepared.command.payload.owner_id)?.name} · 期限：{String(prepared.command.payload.due_date)}</p><p>确认后重新标记为待答复，原问题与答复保留在版本记录中。</p></div>}
      {prepared.command.operation === "proposal.g0.decide" && <><p className="mb-4 text-sm">决定：{statuses[String(prepared.command.payload.outcome)]} · {String(prepared.command.payload.rationale)}</p>
        {prepared.command.payload.outcome === "approved" && <div className="mb-4 space-y-2 text-sm"><p>选定方案：{String(options.find(item => item.item_id === prepared.command.payload.selected_option_item_id)?.content.name ?? "无方案")}</p><p>项目：{String((prepared.command.payload.project as { name: string }).name)} · 负责人：{people.find(person => person.id === (prepared.command.payload.project as { owner_id: string }).owner_id)?.name}</p>
          <p>{prepared.review.target_kind === "new_variant" ? "新变体" : "新型号"}：{prepared.review.identity_name ?? String((prepared.command.payload.new_identity as { name?: string } | undefined)?.name ?? "未提供")}{prepared.review.target_kind === "new_variant" && ` · ${variantNames[prepared.review.variant_kind ?? ""] ?? "类别待核对"}`}</p>
          {(prepared.command.payload.dispositions as (Assignment & { note: string })[]).map((item, index) => <p key={index}>{item.note} → {item.kind === "task" ? "任务" : "风险"} · {people.find(person => person.id === item.owner_id)?.name} · {item.due_date}</p>)}
        </div>}
      </>}
      {prepared.review.dispositions?.map((item, index) => <p key={index} className="mb-2 text-sm">{item.note}{item.audience_added ? "：负责人会获得型号与项目读取权限" : ""}</p>)}
      {prepared.review.project_owner_audience_added && <p className="text-sm">项目负责人会获得型号与项目读取权限。</p>}
      <div className="mt-6 flex gap-3"><Button disabled={busy} onClick={async () => {
        setBusy(true); setError("");
        try { await api(`${root}/commands`, prepared.command); if (live.current) { if (prepared.command.operation === "proposal.question.create" && typeof prepared.command.payload.supersedes_item_id === "string") onDraft(prepared.command.payload.supersedes_item_id, null); setPrepared(null); setSaveNotice("已保存，可继续与小Pai完善。"); await reload(); } }
        catch (failure) { if (live.current) setError((failure as Error).message); }
        finally { if (live.current) setBusy(false); }
      }}>确认办理</Button><Button variant="outline" disabled={busy} onClick={() => setPrepared(null)}>返回修改</Button></div><p className="mt-3 text-xs text-muted-foreground">暂未取得回执时可重试本次办理，重复请求会返回原结果。</p>
    </Dialog.Content></Dialog.Portal></Dialog.Root>}
  </div>;
}
