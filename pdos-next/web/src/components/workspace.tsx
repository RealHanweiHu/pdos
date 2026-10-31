"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowCounterClockwise, CheckCircle, FileText } from "@phosphor-icons/react";
import { originalLocation, type LocatedSource } from "@/lib/original-location";
import { sourceLines } from "@/lib/product-view";
import { ProductDefinition } from "@/components/product/product-definition";
import { OriginalLifecycle } from "@/components/product/original-lifecycle";
import { OriginalFiles } from "@/components/product/original-files";
import type { OriginalSecurity } from "@/lib/original-security";
import { ProductVariants } from "@/components/product/product-variants";
import { ProductPlatforms } from "@/components/product/product-platforms";
import { ModelAccounting } from "@/components/product/model-accounting";
import { ConnectedProviderAgreements } from "@/components/model_configuration/provider-agreements";
import { ConnectedAgentSkills } from "@/components/model_configuration/agent-skills";
import { ConnectedMcpManagement } from "@/components/model_configuration/mcp-management";
import { ConnectedAgentBudgets } from "@/components/model_configuration/agent-budgets";
import { BuildPreparation } from "@/components/builds/build-preparation";
import { ManufacturingPreparation } from "@/components/manufacturing-preparation/manufacturing-preparation";
import { ManufacturingPublication } from "@/components/manufacturing-publication/manufacturing-publication";
import { NativePilots } from "@/components/manufacturing/native-pilots";
import { ReleasePackages } from "@/components/manufacturing/release-packages";
import { ExternalHandoffs } from "@/components/manufacturing/external-handoffs";
import { ReleaseExceptions } from "@/components/manufacturing/release-exceptions";
import { BuildExecution } from "@/components/builds/build-execution";
import { BuildHandoff } from "@/components/builds/build-handoff";
import { BuildLaunch } from "@/components/builds/build-launch";
import { BuildResults } from "@/components/builds/build-results";
import { BuildQualityLoop } from "@/components/builds/build-quality-loop";
import { BuildQualityFollowup } from "@/components/builds/build-quality-followup";
import { BuildChangeOrders } from "@/components/builds/build-change-orders";
import { BuildStart } from "@/components/builds/build-start";
import { BuildSupply } from "@/components/builds/build-supply";
import { BuildCost } from "@/components/builds/build-cost";
import { BuildVerification } from "@/components/builds/build-verification";
import { VerificationProfessional } from "@/components/product/verification-professional";
import { ProjectActivity } from "@/components/projects/project-activity";
import { ProjectWork } from "@/components/projects/project-work";
import { ProjectPlanning } from "@/components/projects/project-planning";
import { KnowledgeExperience } from "@/components/knowledge/knowledge-experience";
import { FieldFeedback } from "@/components/field/field-feedback";
import { Button } from "@/components/ui/button";
import { categoryTransport } from "@/lib/category-transport";
import { createWorkspaceApi } from "@/lib/workspace-api";
import { ConnectedModelSettings } from "@/components/model_configuration/connected-settings";
import { WorkspaceExperience, WorkspacePanel } from "@/components/workspace-experience";
import type { PaiContext } from "@/components/pai-rail";

type Product = { id: string; name: string; purpose: string; revision: number };
type Source = LocatedSource & { id: string; title: string; source_label: string; content: string; revision: number; visibility: string; status: string };
type Claim = { id: string; artifact_id: string; line: number; quote: string; statement: string; nature: string; availability: string; status: string; source_status: string };
type Work = { id: string; goal: string; artifact_id: string; source_revision: number; status: string; error_code: string | null; revision: number };
type Receipt = { id: string; operation: string; subject_id: string; created_at: string; writer_id: string; requester_id: string };
type Original = { id: string; title: string; filename: string; status: string; parse_code: string | null; byte_count: number; artifact_id: string | null; security?: OriginalSecurity };
type Data = { originals: Original[]; product: Product; sources: Source[]; claims: Claim[]; works: Work[]; receipts: Receipt[] };
type Pending = { path: string; body: unknown };
type Confirmation = { confirmation_token: string; expected_revision: number; effect: string; statement: string; subject: string; operation: string };
type Draft = { title: string; content: string; source_label: string; visibility: string };
const emptyDraft: Draft = { title: "", content: "", source_label: "", visibility: "private" };
const operationNames: Record<string, string> = { "evidence.artifact.register": "资料已登记", "evidence.claim.record": "事实已登记", "ai.work.start": "委派已保存", "ai.work.state.update": "工作状态已更新", "ai.run.revert": "事实已撤回", "ai.run.cancel": "工作已取消", "product.create": "型号已建立", "product.definition.draft": "型号定义草稿已保存", "evidence.original.upload": "原件已保存", "evidence.original.parse": "资料处理已返回", "ai.work.resume": "继续请求已保存" };
Object.assign(operationNames, { "evidence.lifecycle.upload.abandon": "未完成上传已具名终止", "evidence.lifecycle.quarantine": "隔离意图已登记", "evidence.lifecycle.restore": "恢复意图已登记", "evidence.lifecycle.cancel": "待执行意图已取消", "evidence.lifecycle.protection.record": "保留事实已核对", "evidence.lifecycle.effect": "生命周期实际结果已核对", "evidence.original.scan.request": "扫描请求已登记", "evidence.original.scan.record": "扫描结果已核对", "evidence.original.withdraw": "原件来源已撤回", "product.variant.derive": "派生草稿已建立", "product.variant.rebase": "派生父版重核已记录", "project.create": "研发项目已建立", "work.plan.propose": "首版计划候选已保存", "work.plan.apply": "首版计划已应用", "ai.model_call.reconcile": "原调用费用核对已记录", "engineering.bom.revise": "BOM草稿已固定", "engineering.configuration.create": "工程配置草稿已固定", "npi.process.revise": "制造配置草稿已固定", "build.create": "本轮试制计划已固定", "build.readiness.compute": "试制准备缺项已计算", "build.configuration.actual.record": "实际配置与差异已记录", "build.output.record": "已发生产出批次已记录", "build.sample.allocate": "样件身份已分配", "supply.snapshot.record": "供给来源快照已保存", "supply.kit.compute": "固定快照齐套缺项已计算", "cost.inputs.record": "成本口径与报价快照已保存", "cost.estimate.compute": "固定输入成本估算已计算", "verification.preparation.record": "验证准备版本已保存" });
Object.assign(operationNames, { "quality.issue.create": "确定失败问题已建立", "quality.issue.merge": "问题合并及待重核已保存", "quality.issue.triage": "问题分诊已保存", "quality.issue.containment.record": "实际遏制已保存", "quality.capa.draft": "CAPA假设草稿已保存", "change.request.create": "固定依据的变更草稿已建立", "change.impact.compute": "变更影响与未知范围已计算", "quality.policy.import": "本地合成风险政策已导入" });


async function rawApi<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/${path}`, { method: body === undefined ? "GET" : "POST", headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body), cache: "no-store" });
  const value = await response.json();
  if (!response.ok) throw Object.assign(new Error(value.message ?? "服务暂不可用。"), { code: value.code, status: response.status, detail: value.detail, recovery: value.recovery });
  return value;
}

export function Workspace({ categoryId, projectId = "", fixedProductId, embeddedPanel, onSaved, onPaiContext }: { categoryId: string; projectId?: string; fixedProductId?: string; embeddedPanel?: string; onSaved?: () => void; onPaiContext?: (context: PaiContext | null) => void }) {
  const transport = useMemo(() => categoryTransport(categoryId, rawApi), [categoryId]);
  const [products, setProducts] = useState<Product[]>([]);
  const [productId, setProductId] = useState("");
  const [data, setData] = useState<Data | null>(null);
  const [session, setSession] = useState<{ name: string; principal_id: string } | null>(null);
  const [auth, setAuth] = useState<"loading" | "signed_out" | "ready">("loading");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [readingFacts, setReadingFacts] = useState(false);
  const factsReadLock = useRef(false);
  const [draft, setDraft] = useState<Draft>(emptyDraft);
  const [sourceId, setSourceId] = useState("");
  const [line, setLine] = useState(1);
  const [quote, setQuote] = useState("");
  const [statement, setStatement] = useState("");
  const [availability, setAvailability] = useState("known");
  const [visibility, setVisibility] = useState("private");
  const [newProduct, setNewProduct] = useState(false);
  const [name, setName] = useState("");
  const [purpose, setPurpose] = useState("");
  const [pending, setPending] = useState<Pending | null>(null);
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const confirmationTrigger = useRef<HTMLElement | null>(null);
  const storageKey = session && productId ? `pdos-next:${session.principal_id}:${productId}` : "";
  const source = data?.sources.find((s) => s.id === sourceId);
  const readScope = `${auth}:${session?.principal_id ?? "signed-out"}:${categoryId}:${productId}`;
  const client = useMemo(() => createWorkspaceApi(transport, readScope, 2), [transport, readScope]);
  const api = client.api;
  useEffect(() => { client.activate(); return () => client.dispose(); }, [client]);

  const load = useCallback(async () => {
    try {
      const who = await rawApi<{ name: string; principal_id: string }>("v1/session");
      const list = await transport<Product[]>("v1/products");
      setSession(who); setProducts(list); setAuth("ready");
      if (fixedProductId && !list.some(product => product.id === fixedProductId)) setError("本项目的型号当前不可读，请核对授权范围后重新进入项目。");
      setProductId((current) => { const requested = fixedProductId ?? new URLSearchParams(window.location.search).get("product"); if (fixedProductId) return list.some(p => p.id === fixedProductId) ? fixedProductId : ""; return list.some((p) => p.id === current) ? current : list.some((p) => p.id === requested) ? requested! : list[0]?.id ?? ""; });
    } catch (e) {
      if ((e as { status?: number }).status === 401) setAuth("signed_out");
      else { setError((e as Error).message); setAuth("signed_out"); }
    }
  }, [transport, fixedProductId]);
  useEffect(() => { let active = true; void Promise.resolve().then(() => { if (active) return load(); }); return () => { active = false; }; }, [load]);

  const refresh = useCallback(async () => {
    if (!productId) { setData(null); return; }
    const next = await api<Data>(`v1/products/${productId}/workspace`);
    setData(next);
    setSourceId((current) => next.sources.some((s) => s.id === current) ? current : next.sources[0]?.id ?? "");
  }, [productId, api]);
  const refreshAfterSave = useCallback(async () => { await refresh(); onSaved?.(); }, [refresh, onSaved]);
  async function retryCurrentFacts() {
    if (busy || factsReadLock.current || auth !== "ready" || !productId || data?.product.id === productId) return;
    factsReadLock.current = true; setReadingFacts(true); setBusy(true); setError("");
    try { await refresh(); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "当前型号事实暂时无法读取，请核对当前读取权限后重试。"); }
    finally { factsReadLock.current = false; setReadingFacts(false); setBusy(false); }
  }
  useEffect(() => {
    let active = true;
    if (productId) api<Data>(`v1/products/${productId}/workspace`).then((next) => {
      if (active) { setData(next); setSourceId(next.sources[0]?.id ?? ""); setStatement(""); setQuote(""); }
    }).catch((e) => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [productId, api]);
  useEffect(() => {
    if (!data || data.product.id !== productId || (!data.originals.some((item) => item.security?.state === "scanning" || (item.status === "uploaded" && ["not_scanned", "clean"].includes(item.security?.state ?? ""))) && !data.works.some((item) => ["accepted", "running"].includes(item.status)))) return;
    const timer = setInterval(() => { void refresh().catch(() => undefined); }, 2500);
    return () => clearInterval(timer);
  }, [data, productId, refresh]);
  useEffect(() => {
    if (!storageKey) return;
    let active = true;
    void Promise.resolve().then(() => {
      if (!active) return;
      try {
        const saved = JSON.parse(localStorage.getItem(storageKey) ?? "{}");
        setDraft(saved.draft ?? emptyDraft); setPending(saved.pending ?? null);
      } catch { setDraft(emptyDraft); setPending(null); }
    });
    return () => { active = false; };
  }, [storageKey]);
  useEffect(() => { if (confirmation) dialog.current?.showModal(); }, [confirmation]);

  function updateDraft(next: Draft) {
    setDraft(next);
    try { if (storageKey) localStorage.setItem(storageKey, JSON.stringify({ draft: next, pending })); } catch { /* Optional local storage does not block online work. */ }
  }
  function savePending(next: Pending | null) {
    setPending(next);
    try { if (storageKey) localStorage.setItem(storageKey, JSON.stringify({ draft, pending: next })); } catch { /* Preserve the in-memory original request. */ }
  }
  async function mutate(path: string, body: unknown, success: string) {
    setBusy(true); setError(""); setNotice("");
    savePending({ path, body });
    try {
      await api(path, body); savePending(null);
      await load(); await refreshAfterSave(); if (path === "v1/products") setNewProduct(false); setNotice(success);
    } catch (e) {
      const failure = e as Error & { code?: string; status?: number };
      if (failure.status && failure.status < 500) savePending(null);
      setError(failure.message);
    } finally { setBusy(false); }
  }
  function command(operation: string, payload: unknown, revision = data?.product.revision ?? 1, sourceRead = true) {
    return { command_id: crypto.randomUUID(), idempotency_key: crypto.randomUUID(), operation, product_id: productId, expected_revision: revision, payload, source_read_set: sourceRead && source ? [{ artifact_id: source.id, expected_revision: source.revision }] : [] };
  }
  function chooseLine(number: number, text: string) { setLine(number); setQuote(text); setStatement(text); }
  function closeConfirmation() {
    dialog.current?.close();
    setConfirmation(null);
    confirmationTrigger.current?.focus();
  }
  async function preview(operation: string, subject: string, trigger: HTMLElement) {
    confirmationTrigger.current = trigger;
    setBusy(true); setError("");
    try {
      const path = `receipts/${subject}/revert-preview`;
      const value = await api<Omit<Confirmation, "subject" | "operation">>(`v1/products/${productId}/${path}`, {});
      setConfirmation({ ...value, subject, operation });
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }



  useEffect(() => {
    if (!onPaiContext) return;
    onPaiContext({ categoryId, productId, projectId: projectId || undefined, sources: data?.product.id === productId ? data.sources : [] });
    return () => onPaiContext(null);
  }, [onPaiContext, categoryId, productId, projectId, data]);

  return <>
    <WorkspaceExperience embeddedPanel={embeddedPanel} categoryId={categoryId} projectId={projectId} auth={auth} session={session} products={products} productId={productId} data={data} locked={busy || !!pending} onProductChange={setProductId} onCreateProduct={() => setNewProduct(!newProduct)} api={api}>
      <div className="workspace-alerts">
      {pending && !error && <div role="status" className="panel mt-5"><p>有一项原操作等待核对回执，重试会沿用同一请求。</p><Button variant="outline" className="mt-3" disabled={busy} onClick={() => void mutate(pending.path, pending.body, "原操作已取得回执。")}>重试原操作</Button></div>}
      {error && <div role="alert" className="panel mt-5 border-destructive"><p>{error}</p>{pending && <Button className="mt-3" variant="outline" disabled={busy} onClick={() => void mutate(pending.path, pending.body, "原操作已取得回执。")}>重试原操作</Button>}</div>}
      {notice && <p role="status" className="mt-4">{notice}</p>}
      {busy && <p role="status" className="mt-4 subtle">{readingFacts ? "正在读取当前型号事实…" : "正在核对服务回执…"}</p>}
      {auth === "ready" && productId && (!data || data.product.id !== productId) && (error || readingFacts) && <section className="panel mt-5"><p className="subtle">{readingFacts ? "正在按当前身份和型号读取事实；此次只读，不提交业务操作。" : "当前型号事实尚未取得。可按当前身份明确重试读取，不改变授权、草稿或原操作。"}</p><Button type="button" variant="outline" className="mt-3" disabled={busy || readingFacts} onClick={() => void retryCurrentFacts()}>重试读取当前事实</Button></section>}
      </div>
      {auth === "loading" ? <p role="status">正在载入你的工作…</p> : auth === "signed_out" ? <div className="panel mx-auto mt-12 max-w-lg">
        <p className="subtle">独立新工程 · 合成预览</p><h1 className="mt-3 text-2xl font-semibold">从一份型号资料开始</h1>
        <p className="my-5">登记原文、定位依据、保存事实，再查看实际工作结果。此环境只用于合成资料演练。</p>
        <Button disabled={busy} onClick={async () => { setBusy(true); setError(""); try { await api("local-session", {}); await load(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } }}>进入本地合成环境</Button>
      </div> : <>
        {newProduct && <form className="panel mb-5" onSubmit={(e) => { e.preventDefault(); void mutate("v1/products", { name, purpose, idempotency_key: crypto.randomUUID() }, "型号范围已建立。"); }}><h2 className="mb-4 font-semibold">建立型号范围</h2><label>型号名称<input required minLength={2} maxLength={160} value={name} onChange={(e) => setName(e.target.value)} /></label><label>真实用途<textarea required minLength={3} maxLength={1000} value={purpose} onChange={(e) => setPurpose(e.target.value)} /></label><div className="flex gap-2"><Button disabled={busy || !!pending}>建立型号</Button><Button type="button" variant="outline" disabled={busy || !!pending} onClick={() => setNewProduct(false)}>取消</Button></div></form>}
        {session && embeddedPanel === undefined && <WorkspacePanel key={`models:${session.principal_id}:${categoryId}`} name="accounting"><div className="space-y-6"><ConnectedModelSettings api={transport} /><ConnectedProviderAgreements api={transport} principalId={session.principal_id} categoryId={categoryId} /><ConnectedAgentBudgets api={transport} principalId={session.principal_id} categoryId={categoryId} /><ConnectedAgentSkills api={transport} principalId={session.principal_id} categoryId={categoryId} /><ConnectedMcpManagement api={transport} principalId={session.principal_id} categoryId={categoryId} /></div></WorkspacePanel>}
        {data && data.product.id === productId && <>
          <WorkspacePanel key={`definition:${session?.principal_id}:${productId}`} name="definition">{session && <ProductDefinition compact={embeddedPanel !== undefined} key={`${session.principal_id}:${productId}`} product={data.product} principalId={session.principal_id} sources={data.sources} api={api} onSaved={refreshAfterSave} onAccessDenied={() => {
            setData(null); setProducts([]); setProductId(""); setDraft(emptyDraft); setSourceId(""); setQuote(""); setStatement("");
            setError("当前权限需重新核对，资料正文已隐藏。请刷新型号列表后继续。");
          }} />}</WorkspacePanel>
          <WorkspacePanel key={`variants:${session?.principal_id}:${productId}`} name="variants">{session && <><ProductVariants key={`variant:${session.principal_id}:${productId}`} product={data.product} principalId={session.principal_id} sources={data.sources} api={api} onSaved={refreshAfterSave} /><ProductPlatforms product={data.product} categoryId={categoryId} principalId={session.principal_id} api={api} onSaved={refreshAfterSave} /></>}</WorkspacePanel>
          <WorkspacePanel key={`plan:${session?.principal_id}:${productId}`} name="plan">{session && <div className="space-y-6"><ProjectPlanning key={`project:${session.principal_id}:${productId}:${projectId}`} categoryId={categoryId} projectId={projectId} product={data.product} principalId={session.principal_id} api={api} onSaved={refreshAfterSave} />{projectId && <ProjectWork api={api} categoryId={categoryId} productId={productId} projectId={projectId} principalId={session.principal_id} productRevision={data.product.revision} onRefresh={refresh}/>}</div>}</WorkspacePanel>
          <WorkspacePanel key={`build:${session?.principal_id}:${productId}`} name="build">{session && <div className="space-y-6"><BuildPreparation projectId={projectId} key={`build:${session.principal_id}:${productId}`} product={data.product} principalId={session.principal_id} api={api} onSaved={refreshAfterSave} />{embeddedPanel === undefined && <><ManufacturingPreparation projectId={projectId} key={`manufacturing-preparation:${session.principal_id}:${productId}`} product={data.product} principalId={session.principal_id} api={api} onSaved={refreshAfterSave} /><ManufacturingPublication categoryId={categoryId} projectId={projectId} product={data.product} principalId={session.principal_id} api={api} onSaved={refreshAfterSave} />{projectId && <><NativePilots categoryId={categoryId} projectId={projectId} product={data.product} principalId={session.principal_id} api={api} onSaved={refreshAfterSave} /><ReleasePackages categoryId={categoryId} projectId={projectId} product={data.product} principalId={session.principal_id} api={api} onSaved={refreshAfterSave} /><ReleaseExceptions categoryId={categoryId} projectId={projectId} product={data.product} principalId={session.principal_id} api={api} onSaved={refreshAfterSave} /><ExternalHandoffs categoryId={categoryId} projectId={projectId} product={data.product} principalId={session.principal_id} api={api} onSaved={refreshAfterSave} /></>}</>}</div>}</WorkspacePanel>
          <WorkspacePanel name="manufacturing">{session && <ManufacturingPreparation projectId={projectId} product={data.product} principalId={session.principal_id} api={api} onSaved={refreshAfterSave} />}</WorkspacePanel>
          <WorkspacePanel name="publication">{session && <ManufacturingPublication categoryId={categoryId} projectId={projectId} product={data.product} principalId={session.principal_id} api={api} onSaved={refreshAfterSave} />}</WorkspacePanel>
          <WorkspacePanel name="pilots">{session && <NativePilots categoryId={categoryId} projectId={projectId} product={data.product} principalId={session.principal_id} api={api} onSaved={refreshAfterSave} />}</WorkspacePanel>
          <WorkspacePanel name="packages">{session && <ReleasePackages categoryId={categoryId} projectId={projectId} product={data.product} principalId={session.principal_id} api={api} onSaved={refreshAfterSave} />}</WorkspacePanel>
          <WorkspacePanel name="exceptions">{session && <ReleaseExceptions categoryId={categoryId} projectId={projectId} product={data.product} principalId={session.principal_id} api={api} onSaved={refreshAfterSave} />}</WorkspacePanel>
          <WorkspacePanel name="external">{session && <ExternalHandoffs categoryId={categoryId} projectId={projectId} product={data.product} principalId={session.principal_id} api={api} onSaved={refreshAfterSave} />}</WorkspacePanel>
          <WorkspacePanel key={`start:${session?.principal_id}:${productId}`} name="start">{session && <BuildStart projectId={projectId} key={`build-start:${session.principal_id}:${productId}`} product={data.product} principalId={session.principal_id} api={api} onSaved={refreshAfterSave} />}</WorkspacePanel>
          <WorkspacePanel key={`execution:${session?.principal_id}:${productId}`} name="execution">{session && <BuildExecution projectId={projectId} key={`execution:${session.principal_id}:${productId}`} product={data.product} principalId={session.principal_id} api={api} onSaved={refreshAfterSave} />}</WorkspacePanel>
          <WorkspacePanel key={`supply:${session?.principal_id}:${productId}`} name="supply">{session && <BuildSupply projectId={projectId} key={`supply:${session.principal_id}:${productId}`} product={data.product} principalId={session.principal_id} api={api} onSaved={refreshAfterSave} />}</WorkspacePanel>
          <WorkspacePanel key={`cost:${session?.principal_id}:${productId}`} name="cost">{session && <BuildCost projectId={projectId} key={`cost:${session.principal_id}:${productId}`} product={data.product} principalId={session.principal_id} api={api} onSaved={refreshAfterSave} />}</WorkspacePanel>
          <WorkspacePanel key={`verification:${session?.principal_id}:${productId}`} name="verification">{session && <BuildVerification projectId={projectId} key={`verification:${session.principal_id}:${productId}`} product={data.product} principalId={session.principal_id} api={api} onSaved={refreshAfterSave} />}</WorkspacePanel>
          <WorkspacePanel key={`professional:${session?.principal_id}:${productId}`} name="professional">{session && <VerificationProfessional projectId={projectId} key={`professional:${session.principal_id}:${productId}`} product={data.product} principalId={session.principal_id} api={api} onSaved={refreshAfterSave} />}</WorkspacePanel>
          <WorkspacePanel key={`handoff:${session?.principal_id}:${productId}`} name="handoff">{session && <BuildHandoff projectId={projectId} key={`handoff:${session.principal_id}:${productId}`} product={data.product} principalId={session.principal_id} api={api} onSaved={refreshAfterSave} />}</WorkspacePanel>
          <WorkspacePanel key={`launch:${session?.principal_id}:${productId}`} name="launch">{session && <BuildLaunch projectId={projectId} key={`launch:${session.principal_id}:${productId}`} product={data.product} principalId={session.principal_id} api={api} onSaved={refreshAfterSave} />}</WorkspacePanel>
          <WorkspacePanel key={`results:${session?.principal_id}:${productId}`} name="results">{session && <BuildResults projectId={projectId} key={`results:${session.principal_id}:${productId}`} product={data.product} principalId={session.principal_id} api={api} onSaved={refreshAfterSave} />}</WorkspacePanel>
          <WorkspacePanel key={`quality:${session?.principal_id}:${productId}:${projectId}`} name="quality">{session && <div className="space-y-6"><BuildQualityLoop projectId={projectId} key={`quality:${session.principal_id}:${productId}:${projectId}`} product={data.product} principalId={session.principal_id} api={api} onSaved={refreshAfterSave} />{embeddedPanel === undefined && <><BuildQualityFollowup projectId={projectId} key={`quality-followup:${session.principal_id}:${productId}:${projectId}`} product={data.product} principalId={session.principal_id} api={api} onSaved={refreshAfterSave} /><BuildChangeOrders projectId={projectId} key={`change-orders:${session.principal_id}:${productId}:${projectId}`} product={data.product} principalId={session.principal_id} api={api} onSaved={refreshAfterSave} /></>}</div>}</WorkspacePanel>
          <WorkspacePanel name="followup">{session && <BuildQualityFollowup projectId={projectId} product={data.product} principalId={session.principal_id} api={api} onSaved={refreshAfterSave} />}</WorkspacePanel>
          <WorkspacePanel name="changes">{session && <BuildChangeOrders projectId={projectId} product={data.product} principalId={session.principal_id} api={api} onSaved={refreshAfterSave} />}</WorkspacePanel>
          <WorkspacePanel key={`field:${session?.principal_id}:${productId}:${projectId}`} name="field">{session && <FieldFeedback api={api} categoryId={categoryId} product={data.product} principalId={session.principal_id} projectId={projectId || null} onSaved={refreshAfterSave}/>}</WorkspacePanel>
          <WorkspacePanel key={`accounting:${session?.principal_id}:${productId}`} name="accounting">{session && <ModelAccounting key={`accounting:${session.principal_id}:${productId}`} product={data.product} principalId={session.principal_id} api={api} onSaved={refreshAfterSave} />}</WorkspacePanel>
          <WorkspacePanel key={`originals:${session?.principal_id}:${productId}`} name="originals"><OriginalFiles key={productId} product={data.product} originals={data.originals} api={api} onSaved={refreshAfterSave} /></WorkspacePanel>
          <WorkspacePanel key={`lifecycle:${session?.principal_id}:${productId}`} name="lifecycle">{session && <OriginalLifecycle key={`lifecycle:${session.principal_id}:${productId}`} productId={productId} productRevision={data.product.revision} api={api} onCommitted={refreshAfterSave} />}</WorkspacePanel>
          <WorkspacePanel key={`sources:${session?.principal_id}:${productId}`} name="sources">
          {session && <KnowledgeExperience api={api} categoryId={categoryId} product={data.product} principalId={session.principal_id} projectId={projectId || null} onSaved={refreshAfterSave}/>}
          <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
            <div className="space-y-6">
              <section className="panel"><div className="mb-5 flex items-center gap-2"><FileText className="text-primary" /><h2 className="font-semibold">原始资料</h2><span className="subtle ml-auto">{data.sources.length} 份</span></div>
                {data.sources.length > 0 && <><label>查看资料<select value={sourceId} onChange={(e) => { setSourceId(e.target.value); setQuote(""); setStatement(""); setVisibility("private"); }}>{data.sources.map((s) => <option key={s.id} value={s.id}>{s.title}</option>)}</select></label>{source && <div className="mb-5 rounded-lg border border-border p-3"><p className="subtle mb-2">{source.source_label} · {source.visibility === "private" ? "私人来源" : source.visibility === "audience" ? "指定评审人可见" : "品类共享"} · {source.status === "active" ? "有效" : "已撤回"}</p><p className="subtle mb-3">选择一行作为事实依据</p><div className="max-h-80 overflow-auto">{sourceLines(source.content).map((text, index) => <button type="button" key={index} className="source-line" aria-pressed={line === index + 1 && quote === text} disabled={!text.trim() || source.status !== "active"} onClick={() => chooseLine(index + 1, text)}><span className="subtle w-5 shrink-0">{index + 1}</span><span>{text || " "}{originalLocation(source, index + 1) && <small className="subtle block">{originalLocation(source, index + 1)}</small>}</span></button>)}</div></div>}</>}
                <details><summary className="cursor-pointer font-medium">登记另一份资料</summary><form className="mt-4" onSubmit={(e) => { e.preventDefault(); void mutate("v1/commands", command("evidence.artifact.register", draft, undefined, false), "原文已保存，来源可查。"); }}>
                  <label>资料名称<input required maxLength={200} value={draft.title} onChange={(e) => updateDraft({ ...draft, title: e.target.value })} /></label>
                  <label>来源说明<input required maxLength={200} placeholder="谁提供的，或来自哪里" value={draft.source_label} onChange={(e) => updateDraft({ ...draft, source_label: e.target.value })} /></label>
                  <label>原文<textarea required maxLength={200000} rows={5} value={draft.content} onChange={(e) => updateDraft({ ...draft, content: e.target.value })} /></label>
                  <label>或导入 UTF-8 文本<input type="file" accept=".txt,.md,text/plain,text/markdown" onChange={async (e) => { const file = e.target.files?.[0]; if (!file) return; if (file.size > 200000 || !/\.(txt|md)$/i.test(file.name)) { setError("当前只接收 200KB 以内的 UTF-8 txt/md 文本。"); return; } const bytes = await file.arrayBuffer(); try { const content = new TextDecoder("utf-8", { fatal: true }).decode(bytes); if (content.includes("\u0000")) throw new Error(); updateDraft({ ...draft, title: draft.title || file.name, content }); } catch { setError("无法按 UTF-8 文本读取此文件。"); } }} /></label>
                  <label>资料受众<select value={draft.visibility} onChange={(e) => updateDraft({ ...draft, visibility: e.target.value })}><option value="private">仅我可见</option><option value="category">品类授权成员</option></select></label><p className="subtle mb-3">未提交草稿保存在本机。可直接登记文字，也可在“原件”视图保留并处理 PDF、XLSX。</p><Button disabled={busy || !!pending}>登记来源</Button>
                </form></details>
              </section>

            </div>
            <div className="space-y-6">
              <section className="panel"><h2 className="mb-4 font-semibold">登记来源事实</h2><form onSubmit={(e) => { e.preventDefault(); void mutate("v1/commands", command("evidence.claim.record", { artifact_id: source?.id, line, quote, statement, nature: "extracted", availability, visibility }), "事实已登记，实际回执已返回。"); }}>
                <label>原文引用 · 第 {line} 行<textarea required maxLength={4000} value={quote} onChange={(e) => setQuote(e.target.value)} placeholder="先选择一行原文" /></label>
                <label>要保留的事实<textarea required maxLength={4000} value={statement} onChange={(e) => setStatement(e.target.value)} /></label>
                <div className="grid gap-3 sm:grid-cols-2"><label>信息状态<select value={availability} onChange={(e) => setAvailability(e.target.value)}><option value="known">已知信息</option><option value="unknown">未知 / 待确认</option><option value="conflicted">存在冲突</option></select></label><label>结果受众<select value={visibility} onChange={(e) => setVisibility(e.target.value)}><option value="private">仅我可见</option><option value="category" disabled={source?.visibility !== "category"}>品类授权成员</option></select></label></div>
                <Button disabled={busy || !!pending || !source || !quote.trim() || source.status !== "active"}>登记事实</Button>
              </form><div className="mt-6 space-y-4">{data.claims.length === 0 && <p className="subtle">尚无事实记录。每条记录都需要准确原文定位。</p>}{data.claims.map((c) => {
                const receipt = data.receipts.find((r) => r.subject_id === c.id && r.operation === "evidence.claim.record" && r.requester_id === session?.principal_id);
                return <article key={c.id} className="border-t border-border pt-4"><div className="flex gap-2"><CheckCircle className="mt-1 shrink-0 text-primary" /><p className="min-w-0 break-words font-medium">{c.statement}</p></div><p className="subtle mt-2">{c.status === "reverted" ? "已撤回 · 历史保留" : c.source_status !== "active" ? "来源已失效" : { known: "已知", unknown: "待确认", conflicted: "冲突" }[c.availability]} · 原文第 {c.line} 行</p><blockquote className="my-3 break-words border-l-2 border-border pl-3 text-sm">{c.quote}</blockquote>{c.status === "active" && receipt && <Button variant="ghost" disabled={busy || !!pending} onClick={(event) => void preview("ai.run.revert", receipt.id, event.currentTarget)}><ArrowCounterClockwise />查看撤回范围…</Button>}</article>;
              })}</div></section>

            </div>
          </div>
          </WorkspacePanel>
          <WorkspacePanel key={`activity:${session?.principal_id}:${productId}`} name="activity">{projectId && session ? <ProjectActivity api={api} scope={{categoryId, productId, projectId, principalId: session.principal_id}}/> : <section className="panel"><h2 className="mb-4 font-semibold">实际活动</h2>{data.receipts.length === 0 && <p className="subtle">暂无活动。</p>}<ol className="space-y-4">{data.receipts.map((r) => <li key={r.id}><p>{operationNames[r.operation] ?? "记录已更新"}</p><p className="subtle"><time dateTime={r.created_at}>{new Date(r.created_at).toLocaleString()}</time> · {r.operation === "evidence.original.parse" ? "资料处理" : r.operation === "ai.work.state.update" ? "系统状态" : r.writer_id === r.requester_id ? "人员操作" : "受控 AI 操作"}</p><details className="subtle mt-1"><summary className="cursor-pointer">查看回执</summary><p className="break-all">{r.id}</p></details></li>)}</ol></section>}</WorkspacePanel>
        </>}
      </>}
    </WorkspaceExperience>
    {confirmation && <dialog ref={dialog} aria-labelledby="confirmation-title" onCancel={(event) => { event.preventDefault(); closeConfirmation(); }}><h2 id="confirmation-title" className="text-lg font-semibold">确认此次操作</h2><p className="my-4 break-words">{confirmation.statement}</p><p className="mb-5">{confirmation.effect}</p><div className="flex justify-end gap-2"><Button variant="outline" onClick={closeConfirmation}>返回</Button><Button disabled={busy} onClick={() => { const c = confirmation; closeConfirmation(); void mutate("v1/commands", command(c.operation, { receipt_id: c.subject, confirmation_token: c.confirmation_token }, c.expected_revision, false), c.operation === "ai.run.revert" ? "事实已撤回，历史保留。" : "工作已取消，已发生的动作保留。"); }}>确认{confirmation.operation === "ai.run.revert" ? "撤回" : "取消"}</Button></div></dialog>}
  </>;
}
