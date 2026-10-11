"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Dialog } from "radix-ui";
import { ArrowLeft, LockKey, CheckCircle, WarningCircle } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { ProposalViews } from "@/components/preproject/proposal-views";
import { ProposalShare } from "@/components/preproject/proposal-share";
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
  display_document: { title: string; brief: string; items: Item[] };
  maturity: { spec_count: number; option_count: number; required_dispositions: Disposition[]; freeze_blockers: Item[] };
  submission: { id: string; reviewer_id: string; frozen_document: { items: Item[] } | null } | null;
  decision: { outcome: string; rationale: string; product_id: string | null; project_id: string | null } | null;
};
type Command = { command_id: string; idempotency_key: string; category_id: string; product_id: null; operation: string; expected_revision: number; source_read_set: unknown[]; payload: Record<string, unknown> };
type Prepared = { command: Command; review: { effect?: string; dispositions?: { note: string; audience_added: boolean }[]; project_owner_audience_added?: boolean } };
type Assignment = { kind: string; owner_id: string; due_date: string };

const statuses: Record<string, string> = { draft: "草稿", returned: "已退回", in_review: "G0 评审中", approved: "已立项", rejected: "不立项" };
const itemStatuses: Record<string, string> = { confirmed: "人工确认", ai_draft: "AI 草稿", expert_pending: "待专家确认", unknown: "未知" };

async function api<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`/api/v1/${path}`, {
    method: body === undefined ? "GET" : "POST", cache: "no-store", signal,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const value = await response.json();
  if (!response.ok) throw new Error(value.message ?? "暂未取得当前结果，请重试原操作。");
  return value;
}

function ItemEditor({ item, save, busy }: { item: Item; save: (content: Record<string, unknown>) => void; busy: boolean }) {
  const field = item.kind === "section" ? "text" : "name";
  const [text, setText] = useState(String(item.content[field] ?? ""));
  return <form onSubmit={event => { event.preventDefault(); save({ ...item.content, [field]: text }); }} className="space-y-2">
    <label className="block text-sm">{item.kind === "section" ? "叙述" : "方案名称"}<textarea required value={text} onChange={event => setText(event.target.value)} /></label>
    <Button size="sm" variant="outline" disabled={busy}>保存此条</Button>
  </form>;
}

export function ProposalDocument(props: { categoryId: string; proposalId: string }) {
  return <ScopedProposalDocument key={`${props.categoryId}:${props.proposalId}`} {...props} />;
}

function ScopedProposalDocument({ categoryId, proposalId }: { categoryId: string; proposalId: string }) {
  const root = `categories/${categoryId}`;
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [documentReady, setDocumentReady] = useState(false);
  const [documentError, setDocumentError] = useState("");
  const [readVersion, setReadVersion] = useState(0);
  const [selectedView, setSelectedView] = useState<ProposalViewName>("spec-benchmark");
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
  const [prepared, setPrepared] = useState<Prepared | null>(null);
  const [reviewer, setReviewer] = useState("");
  const [alternativeReason, setAlternativeReason] = useState("");
  const [outcome, setOutcome] = useState("approved");
  const [rationale, setRationale] = useState("");
  const [selectedOption, setSelectedOption] = useState("");
  const [projectName, setProjectName] = useState("");
  const [projectOwner, setProjectOwner] = useState("");
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
        || (value.status === "in_review" && value.submission?.reviewer_id === session.principal_id
          && (!value.submission.frozen_document || identity.document_mode !== "frozen"))) {
        throw new Error("当前接口未提供可读的提案文档身份，请重新读取。");
      }
      setProposal(value); setPeople(participants.items); setMe(session.principal_id);
      if (!initialized.current) {
        setProjectName(value.display_document.title); setProjectOwner(value.owner_id);
        initialized.current = true;
      }
      // A frozen identity can remain unchanged after source withdrawal or ACL changes.
      setReadVersion(previous => previous + 1);
      setDocumentReady(true);
    }).catch(failure => {
      if (live.current && !controller.signal.aborted && request === documentRequest.current) {
        controller.abort();
        setProposal(null); setPeople([]); setDocumentError((failure as Error).message);
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
  async function patch(item: Item, content: Record<string, unknown>) {
    setBusy(true); setError("");
    try {
      await api(`${root}/commands`, command("proposal.item.patch", { proposal_id: proposalId,
        ops: [{ op: "upsert", item_id: item.item_id, base_version: item.version, kind: item.kind,
          content, source_refs: item.source_refs }] }));
      await reload();
    } catch (failure) { if (live.current) setError((failure as Error).message); }
    finally { if (live.current) setBusy(false); }
  }
  const owner = proposal?.owner_id === me;
  const editable = people.some(person => person.id === me && person.can_write) && ["draft", "returned"].includes(proposal?.status ?? "");
  const deciding = proposal?.status === "in_review" && proposal.submission?.reviewer_id === me;
  const frozenAvailable = !!proposal?.submission?.frozen_document;
  const docItems = proposal?.display_document.items ?? [];
  const options = docItems.filter(item => item.kind === "option");
  return <main className="mx-auto max-w-6xl space-y-6 px-4 py-6 sm:px-8">
    <Link href={`/?category=${categoryId}`} className="inline-flex items-center gap-2 text-sm text-muted-foreground"><ArrowLeft />品类工作区</Link>
    <Button type="button" variant="outline" disabled={busy} onClick={() => { void reload(); }}>刷新文档与视图</Button>
    {documentError && <p role="alert">{documentError}</p>}
    {error && <div role="alert" className="panel flex items-start gap-2"><WarningCircle size={20} /><span>{error}</span></div>}
    {!proposal || !documentReady ? <p role="status">{documentError ? "请核对当前会话与提案受众后重新读取。" : "正在读取提案…"}</p> : <>
      <header className="space-y-3">
        <div className="flex flex-wrap items-center gap-3"><h1 className="text-2xl font-semibold">{proposal.display_document.title}</h1><span className="rounded-md border px-2 py-1 text-xs">{statuses[proposal.status] ?? proposal.status}</span><span className="inline-flex items-center gap-1 text-sm text-muted-foreground"><LockKey />{proposal.visibility === "private" ? "私有提案" : "已共享"}</span></div>
        <p className="text-muted-foreground">{proposal.display_document.brief}</p>
        {proposal.private_source_count > 0 && <p className="text-sm">引用了私有来源，内容只对提案受众可见。</p>}
      </header>
      <ProposalViews view={selectedView} result={viewResult} document={proposal.document_identity} people={people}
        loading={viewLoading} error={viewError} onViewChange={changeView} onRetry={() => { void reload(); }} />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]"><div className="space-y-4">
        {deciding && <p className="panel text-sm">{frozenAvailable ? "当前评审的是提交时的固定副本。未知规格可带入立项，须逐条明确后续处置。" : "提交副本的来源不在当前可读范围，请核对权限后刷新。"}</p>}
        {docItems.map(item => <section key={`${item.item_id}:${item.version}`} className="panel space-y-3">
          <div className="flex items-center justify-between gap-3"><h2 className="font-semibold">{item.kind === "spec" ? String(item.content.parameter) : item.kind === "question" ? "待决问题" : item.kind === "option" ? "方案对比" : item.content.key === "worth_it" ? "为什么值得做" : "提案内容"}</h2><span className="text-xs text-muted-foreground">{item.origin === "ai_draft" ? "AI 草稿" : "人工记录"}</span></div>
          {item.kind === "spec" ? <><p>{item.content.availability === "unknown" ? "值未知" : String(item.content.value ?? item.content.text_value ?? `${item.content.lower ?? ""}–${item.content.upper ?? ""}`)} {String(item.content.unit ?? (["number", "range"].includes(String(item.content.value_type)) ? "（单位未定）" : ""))}</p><p className="text-sm text-muted-foreground">{itemStatuses[String(item.content.item_status)]} · {String(item.content.condition_note ?? "工况未定")}</p></> : item.kind === "question" ? <><p>{String(item.content.question)}</p><p className="text-sm text-muted-foreground">负责人：{people.find(person => person.id === item.content.owner_id)?.name ?? "提案受众"} · {String(item.content.due_date)} · {item.content.status === "carried" ? "已转入项目" : item.content.status === "answered" ? "已答复" : "待答复"}</p></> : editable && ["section", "option"].includes(item.kind) ? <ItemEditor item={item} busy={busy || !!prepared} save={content => patch(item, content)} /> : <p className="whitespace-pre-wrap">{String(item.content.text ?? item.content.name ?? item.content.statement ?? item.content.summary ?? "")}</p>}
          <p className="text-xs text-muted-foreground">第 {item.version} 版 · {item.source_refs.length} 个来源</p>
        </section>)}
      </div><aside className="space-y-4">
        <section className="panel space-y-2"><h2 className="font-semibold">定义成熟度</h2><p className="text-sm">{proposal.maturity.spec_count} 条规格 · {proposal.maturity.option_count} 个方案</p><p className="text-sm">{proposal.maturity.freeze_blockers.length} 条规格仍需完善</p><ul className="list-inside list-disc text-sm">{proposal.maturity.freeze_blockers.map(item => <li key={item.item_id}>{String(item.content.parameter)}：{itemStatuses[String(item.content.item_status)]}，单位或工况需核对</li>)}</ul><p className="text-xs text-muted-foreground">10–20 条关键规格仅作提示。G0 批准后封存定义 v1，保留未知与草稿状态。</p></section>
        {editable && owner && <form className="panel space-y-3" onSubmit={event => { event.preventDefault(); preview("proposal.g0.submit", { proposal_id: proposalId, expected_revision: proposal.revision, reviewer_id: reviewer, no_alternative_reason: alternativeReason || null }); }}>
          <h2 className="font-semibold">提交 G0 立项评审</h2><label className="block text-sm">具名评审人<select required value={reviewer} onChange={event => setReviewer(event.target.value)}><option value="">选择产品经理</option>{people.filter(person => person.reviewer_eligible).map(person => <option key={person.id} value={person.id}>{person.name}</option>)}</select></label>
          {options.length < 2 && <label className="block text-sm">没有替代方案的理由<textarea required value={alternativeReason} onChange={event => setAlternativeReason(event.target.value)} /></label>}
          <Button ref={reviewTrigger} disabled={busy || !!prepared || !reviewer}>核对提交内容</Button><p className="text-xs text-muted-foreground">负责人不能评审自己的提案。</p>
        </form>}
        {deciding && frozenAvailable && <form className="panel space-y-3" onSubmit={event => {
          event.preventDefault();
          preview("proposal.g0.decide", { proposal_id: proposalId, submission_id: proposal.submission!.id,
            expected_revision: proposal.revision, outcome, rationale, selected_option_item_id: selectedOption || null,
            project: { name: projectName, owner_id: projectOwner },
            dispositions: outcome === "approved" ? proposal.maturity.required_dispositions.map(item => ({
              subject_type: item.subject_type, subject_id: item.subject_id, note: item.title, ...dispositions[item.subject_id],
            })) : [] });
        }}>
          <h2 className="font-semibold">具名 G0 决定</h2><label className="block text-sm">决定<select value={outcome} onChange={event => setOutcome(event.target.value)}><option value="approved">批准立项</option><option value="returned">退回完善</option><option value="rejected">不立项</option></select></label>
          <label className="block text-sm">理由<textarea required value={rationale} onChange={event => setRationale(event.target.value)} /></label>
          {outcome === "approved" && <>
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
        {proposal.decision && <section className="panel space-y-2"><h2 className="flex items-center gap-2 font-semibold"><CheckCircle />决定记录</h2><p className="text-sm">{proposal.decision.rationale}</p>{proposal.decision.product_id && <Link className="text-sm underline" href={`/?category=${categoryId}&product=${proposal.decision.product_id}&area=products&view=overview`}>查看立项结果</Link>}</section>}
        <p className="text-xs text-muted-foreground">小Pai 接入后可起草与查漏。人工编辑与 G0 可独立办理。</p>
      </aside></div>
    </>}
    {owner && <ProposalShare categoryId={categoryId} proposalId={proposalId} principalId={me}
      onChanged={receipt => { setShareReceipt(receipt); return reload(); }} />}
    {shareReceipt && !owner && <p role="status" className="panel text-sm">{shareReceipt.operation === "proposal.share" ? "共享成功" : "事实已撤回，引用条目值保留"} · 回执：{shareReceipt.id}</p>}
    {prepared && documentReady && <Dialog.Root open onOpenChange={open => { if (!open && !busy) setPrepared(null); }}><Dialog.Portal><Dialog.Overlay className="fixed inset-0 z-50 bg-black/40" /><Dialog.Content onCloseAutoFocus={event => { event.preventDefault(); reviewTrigger.current?.focus(); }} onEscapeKeyDown={event => { if (busy) event.preventDefault(); }} onPointerDownOutside={event => { if (busy) event.preventDefault(); }} className="fixed left-1/2 top-1/2 z-50 max-h-[85vh] w-[calc(100%-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg border bg-background p-6 shadow-lg">
      <Dialog.Title className="text-lg font-semibold">{prepared.command.operation === "proposal.g0.decide" ? "确认具名 G0 决定" : "确认提交 G0"}</Dialog.Title><Dialog.Description className="my-4">{prepared.review.effect ?? "提交副本将锁定，评审人获得此提案读取权限。"}</Dialog.Description>
      {error && <p role="alert" className="mb-4 text-sm text-destructive">{error}</p>}
      {prepared.command.operation === "proposal.g0.submit" && <p className="mb-4 text-sm">评审人：{people.find(person => person.id === prepared.command.payload.reviewer_id)?.name}</p>}
      {prepared.command.operation === "proposal.g0.decide" && <><p className="mb-4 text-sm">决定：{statuses[String(prepared.command.payload.outcome)]} · {String(prepared.command.payload.rationale)}</p>
        {prepared.command.payload.outcome === "approved" && <div className="mb-4 space-y-2 text-sm"><p>选定方案：{String(options.find(item => item.item_id === prepared.command.payload.selected_option_item_id)?.content.name ?? "无方案")}</p><p>项目：{String((prepared.command.payload.project as { name: string }).name)} · 负责人：{people.find(person => person.id === (prepared.command.payload.project as { owner_id: string }).owner_id)?.name}</p>
          {(prepared.command.payload.dispositions as (Assignment & { note: string })[]).map((item, index) => <p key={index}>{item.note} → {item.kind === "task" ? "任务" : "风险"} · {people.find(person => person.id === item.owner_id)?.name} · {item.due_date}</p>)}
        </div>}
      </>}
      {prepared.review.dispositions?.map((item, index) => <p key={index} className="mb-2 text-sm">{item.note}{item.audience_added ? "：负责人会获得型号与项目读取权限" : ""}</p>)}
      {prepared.review.project_owner_audience_added && <p className="text-sm">项目负责人会获得型号与项目读取权限。</p>}
      <div className="mt-6 flex gap-3"><Button disabled={busy} onClick={async () => {
        setBusy(true); setError("");
        try { await api(`${root}/commands`, prepared.command); if (live.current) { setPrepared(null); await reload(); } }
        catch (failure) { if (live.current) setError((failure as Error).message); }
        finally { if (live.current) setBusy(false); }
      }}>确认办理</Button><Button variant="outline" disabled={busy} onClick={() => setPrepared(null)}>返回修改</Button></div><p className="mt-3 text-xs text-muted-foreground">暂未取得回执时可重试本次办理，重复请求会返回原结果。</p>
    </Dialog.Content></Dialog.Portal></Dialog.Root>}
  </main>;
}
