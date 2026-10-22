"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowClockwise, CheckCircle, SealCheck } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { mpReading, mpRecord, mpRevision, mpStatus, mpUuid, type MpVersion } from "@/components/manufacturing-preparation/manufacturing-preparation-contract";
import type { Project, ProjectList } from "@/lib/project-plan-view";
import { newPublicationCommand, publicationVersion, runPublicationRequest, validPublicationCommand, type PublicationApi, type PublicationPending, type PublicationPrepared, type PublicationReceipt, type PublicationVersion } from "./publication-contract";

type Props = { categoryId: string; projectId?: string; product: { id: string; revision: number }; principalId: string; api: PublicationApi; onSaved: () => void | Promise<void> };
type Local = { project: string; baseline: string; reason: string; previous: Pick<PublicationVersion, "id" | "revision"> | null; pending: PublicationPending | null; receipt: PublicationReceipt | null };
const blank = (project = ""): Local => ({ project, baseline: "", reason: "", previous: null, pending: null, receipt: null });

function Content({ body }: { body: Record<string, unknown> }) {
  const baseline = mpRecord(body.baseline_snapshot) ? body.baseline_snapshot : {};
  const process = mpRecord(body.process_snapshot) ? body.process_snapshot : {};
  const title = mpRecord(baseline.input) && typeof baseline.input.title === "string" ? baseline.input.title : "固定制造基线";
  const docs = Array.isArray(body.documents) ? body.documents : [];
  const declaration = mpRecord(body.declaration) ? body.declaration : {};
  return <div className="space-y-3 text-sm">{typeof declaration.reason === "string" && <p>发布说明：{declaration.reason}</p>}<dl className="grid gap-3 sm:grid-cols-2"><div><dt className="subtle">基线内容</dt><dd>{title}</dd></div><div><dt className="subtle">固定制造配置</dt><dd>{typeof process.name === "string" ? process.name : "名称未取得"} · v{String(process.revision ?? "未知")}</dd></div><div><dt className="subtle">地点</dt><dd>{typeof process.site === "string" ? process.site : "尚未声明"}</dd></div><div><dt className="subtle">产线</dt><dd>{typeof process.line === "string" ? process.line : "尚未声明"}</dd></div></dl><details><summary>本版固定工序资料（{docs.length}份）</summary><ul className="mt-3 space-y-2">{docs.map((raw, i) => { const d = mpRecord(raw) ? raw : {}, b = mpRecord(d.body) ? d.body : {}, p = mpRecord(b.input) ? b.input : {}; return <li key={i}>{String(d.operation_key ?? "工序")} · {d.kind === "work_instruction" ? "作业指引" : "控制计划"} · {typeof p.title === "string" ? p.title : "固定资料"} v{String(d.revision ?? "未知")}</li>; })}</ul></details><p className="subtle">发布固定本版内容。资源资格、本轮准备度及制造放行分别核对；未知项会保留。</p></div>;
}

export function ManufacturingPublication(props: Props) {
  return <PublicationPanel key={`${props.categoryId}:${props.principalId}:${props.product.id}:${props.projectId ?? ""}`} {...props}/>;
}
function PublicationPanel({ categoryId, projectId = "", product, principalId, api, onSaved }: Props) {
  const key = `pdos-manufacturing-publication-v1:${categoryId}:${principalId}:${product.id}:${projectId}`;
  const [local, setLocal] = useState<Local>(() => blank(projectId));
  const current = useRef(local), alive = useRef(false), request = useRef(0), locked = useRef(false);
  const [projects, setProjects] = useState<Project[]>([]), [baselines, setBaselines] = useState<MpVersion[]>([]), [versions, setVersions] = useState<PublicationVersion[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [preview, setPreview] = useState<PublicationPrepared | null>(null), [fixed, setFixed] = useState<PublicationVersion | null>(null);
  const [busy, setBusy] = useState(false), [reading, setReading] = useState(true), [notice, setNotice] = useState(""), [failed, setFailed] = useState(true), [denied, setDenied] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const save = useCallback((next: Local) => { try { localStorage.setItem(key, JSON.stringify(next)); } catch { setNotice("本机无法保存原请求，请恢复浏览器存储后再办理；本次尚未提交。"); throw new Error("原请求未能持久保留，不能继续提交。"); } current.current = next; setLocal(next); }, [key]);
  function saveFromEvent(next: Local) {
    try { save(next); return true; } catch { return false; }
  }
  const failure = useCallback((error: unknown) => {
    if ([401, 403].includes(mpStatus(error) ?? 0)) {
      let storageCleared = true;
      try { localStorage.removeItem(key); } catch { storageCleared = false; }
      current.current = blank(projectId); setLocal(current.current); setProjects([]); setBaselines([]); setVersions([]); setFixed(null); setPreview(null); setDenied(true);
      setNotice(storageCleared ? "当前访问不可用，已清除本机私有材料。已保存记录仍可在恢复访问后查询。" : "当前访问不可用，页面私有材料已清除；浏览器存储暂无法清理，请恢复存储后清除本机记录。");
    } else setNotice(error instanceof Error ? error.message : "当前无法完成读取，请重试。");
  }, [key, projectId]);
  const refresh = useCallback(async () => {
    const epoch = ++request.current; setReading(true); setFailed(true);
    try {
      const context = await api<ProjectList>(`v1/products/${product.id}/projects`);
      if (!Array.isArray(context.items) || !context.items.every(p => mpUuid(p.id) && typeof p.name === "string")) throw new Error("项目读取不完整，请重试。");
      const selection = current.current.project;
      let selected: MpVersion[] = [], published: PublicationVersion[] = [], nextCursor: string | null = null;
      if (selection) {
        const [raw, history] = await Promise.all([api<unknown>(`v1/products/${product.id}/manufacturing-preparations?project_id=${selection}`), api<unknown>(`v1/products/${product.id}/manufacturing-publications?project_id=${selection}`)]);
        const preparation = mpReading(raw, selection);
        if (!preparation || !mpRecord(history) || history.schema_version !== "pdos-manufacturing-publication-v1" || !Array.isArray(history.versions) || !history.versions.every(v => publicationVersion(v, selection))) throw new Error("本项目固定资料或发布记录读取不完整，请重试。");
        selected = preparation.versions.filter(v => v.kind === "manufacturing_baseline"); published = history.versions;
        if (!mpRecord(history.history_page) || !(history.history_page.next_cursor === null || typeof history.history_page.next_cursor === "string")) throw new Error("发布历史分页信息不完整。");
        nextCursor = history.history_page.next_cursor;
      }
      if (!alive.current || epoch !== request.current) return;
      setProjects(context.items); setBaselines(selected); setVersions(published); setCursor(nextCursor); setFailed(false);
    } catch (error) { if (alive.current && epoch === request.current) failure(error); }
    finally { if (alive.current && epoch === request.current) setReading(false); }
  }, [api, product.id, failure]);
  useEffect(() => {
    alive.current = true;
    void Promise.resolve().then(async () => {
      if (!alive.current) return;
      try {
        const value: unknown = JSON.parse(localStorage.getItem(key) ?? "null");
        if (mpRecord(value)) {
          const previous = value.previous === undefined || value.previous === null ? null : mpRecord(value.previous) && mpUuid(value.previous.id) && mpRevision(value.previous.revision) ? { id: value.previous.id, revision: value.previous.revision } : undefined;
          if (previous !== undefined && typeof value.project === "string" && (!projectId || value.project === projectId) && typeof value.baseline === "string" && typeof value.reason === "string" && (value.pending === null || (mpRecord(value.pending) && ["inputs", "preview", "execute"].includes(String(value.pending.stage)) && validPublicationCommand(value.pending.command) && value.pending.command.category_id === categoryId && value.pending.command.product_id === product.id && value.pending.command.payload.project_id === value.project && value.pending.command.payload.baseline.id === value.baseline && value.pending.command.payload.reason === value.reason && value.pending.command.payload.previous_id === (previous?.id ?? null) && value.pending.command.payload.expected_previous_revision === (previous?.revision ?? null) && (value.pending.stage === "execute" ? !!value.pending.command.payload.approval_token : value.pending.command.payload.approval_token === undefined))) && (value.receipt === null || (mpRecord(value.receipt) && value.receipt.operation === "npi.manufacturing_baseline.publish" && value.receipt.subject_type === "manufacturing_publication" && mpUuid(value.receipt.id) && mpUuid(value.receipt.subject_id))) && !(value.pending && value.receipt)) save({ ...value, previous } as Local);
        }
      } catch { /* Unreadable or foreign-scope storage is not a valid request. */ }
      await refresh();
    });
    return () => { alive.current = false; request.current += 1; };
  }, [key, projectId, categoryId, product.id, refresh, save]);
  useEffect(() => { if (preview) dialog.current?.showModal(); else dialog.current?.close(); }, [preview]);
  async function run(waiting: PublicationPending) {
    if (locked.current || denied) return;
    locked.current = true; setBusy(true); setNotice("");
    try {
      const result = await runPublicationRequest(api, waiting, principalId, next => save({ ...current.current, pending: next }), () => alive.current);
      if (!result || !alive.current) return;
      if (result.stage === "preview") { setPreview(result.prepared); return; }
      save({ ...current.current, pending: null, receipt: result.receipt }); setPreview(null);
      setNotice("这版制造基线已具名发布，可回读固定内容。资产资格和制造放行仍分别核对。");
      await refresh(); await onSaved();
    } catch (error) { if (alive.current) { if (waiting.stage === "execute" && ![401, 403].includes(mpStatus(error) ?? 0)) setNotice("保存结果尚未核实。请保留原请求，核对后再继续。"); else failure(error); } }
    finally { locked.current = false; if (alive.current) setBusy(false); }
  }
  function start() {
    const baseline = baselines.find(v => v.id === local.baseline);
    if (!baseline || baseline.project_id !== local.project || locked.current || denied || preview || failed || reading || local.pending || local.receipt || !local.reason.trim()) return;
    const previous = local.previous ? versions.find(v => v.id === local.previous!.id && v.revision === local.previous!.revision && v.project_id === local.project && v.is_current) ?? null : null;
    if (local.previous && !previous) { setNotice("所选前版已不是当前发布，请明确选择当前版继续。"); return; }
    const command = newPublicationCommand(categoryId, product.id, product.revision, baseline, local.reason, previous);
    const next = { ...current.current, pending: { stage: "inputs" as const, command }, receipt: null }; if (!saveFromEvent(next)) return; void run(next.pending);
  }
  function continueFrom(version: PublicationVersion) {
    if (locked.current || denied || reading || failed || preview || current.current.pending || version.project_id !== current.current.project || !version.is_current || !versions.some(v => v.id === version.id && v.revision === version.revision && v.is_current && v.project_id === current.current.project)) return;
    const selected = current.current.baseline || baselines.find(v => v.id === version.baseline.id && v.revision === version.baseline.revision)?.id || "";
    if (!saveFromEvent({ ...current.current, previous: { id: version.id, revision: version.revision }, baseline: selected, receipt: null })) return;
    setFixed(null); setPreview(null); setNotice("");
  }
  function confirm() {
    if (!preview || local.pending?.stage !== "preview") return;
    const expires = preview.expires_at;
    if (expires !== null && Date.parse(expires) <= Date.now()) { setNotice("具名材料所声明的期限已到，请取消后重新核对。"); setPreview(null); return; }
    const next = { ...current.current, pending: { stage: "execute" as const, command: preview.command } }; if (!saveFromEvent(next)) return; setPreview(null); void run(next.pending);
  }
  async function readFixed(version: PublicationVersion) {
    if (locked.current) return;
    locked.current = true; setBusy(true); setFixed(null);
    try { const found = await api<unknown>(`v1/products/${product.id}/manufacturing-publications/${version.id}?revision=${version.revision}`); if (!alive.current) return; if (!publicationVersion(found, local.project) || found.id !== version.id || found.revision !== version.revision) throw new Error("回读身份不匹配，请刷新发布记录。"); setFixed(found); }
    catch (error) { if (alive.current) failure(error); }
    finally { locked.current = false; if (alive.current) setBusy(false); }
  }
  async function moreHistory() {
    if (!cursor || locked.current || denied) return;
    const project = current.current.project, originalCursor = cursor;
    locked.current = true; setBusy(true);
    try {
      const value = await api<unknown>(`v1/products/${product.id}/manufacturing-publications?project_id=${project}&history_cursor=${encodeURIComponent(originalCursor)}`);
      if (!alive.current || current.current.project !== project) return;
      if (!mpRecord(value) || !Array.isArray(value.versions) || !value.versions.every(v => publicationVersion(v, project)) || !mpRecord(value.history_page) || !(value.history_page.next_cursor === null || typeof value.history_page.next_cursor === "string") || value.history_page.next_cursor === originalCursor) throw new Error("历史分页未能继续，请刷新后重试。");
      const additional = value.versions;
      setVersions(previous => [...previous, ...additional.filter(v => !previous.some(p => p.id === v.id))]);
      setCursor(value.history_page.next_cursor);
    } catch (error) { if (alive.current) failure(error); }
    finally { locked.current = false; if (alive.current) setBusy(false); }
  }
  const disabled = busy || reading || denied;
  const previousUnavailable = !!local.previous && !local.pending && !local.receipt && !failed && !reading && !versions.some(v => v.id === local.previous!.id && v.revision === local.previous!.revision && v.project_id === local.project && v.is_current);
  return <section aria-label="制造基线正式发布" className="min-w-0 space-y-4 rounded-lg border border-border p-4 [overflow-wrap:anywhere]">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="flex items-center gap-2 text-lg font-semibold"><SealCheck size={20}/>制造基线发布</h2><p className="subtle">固定本轮工艺和资料，由有权本人核对并具名发布。</p></div><Button variant="outline" size="sm" disabled={disabled} onClick={() => void refresh()}><ArrowClockwise/>刷新发布资料</Button></div>
    {notice && <p role="status" className="text-sm">{notice}</p>}
    {local.receipt && <p className="flex items-center gap-2 text-sm"><CheckCircle size={18}/>已取得第{local.receipt.subject_revision}版发布回执。<span className="subtle">{local.receipt.id}</span></p>}
    <div className="grid gap-3 sm:grid-cols-2"><label className="space-y-2 text-sm"><span>项目</span><select value={local.project} disabled={disabled || !!local.pending || !!projectId} onChange={e => { if (!saveFromEvent(blank(e.target.value))) return; setFixed(null); void refresh(); }}><option value="">请选择项目</option>{projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label><label className="space-y-2 text-sm"><span>固定制造基线</span><select value={local.baseline} disabled={disabled || failed || !!local.pending} onChange={e => { if (!saveFromEvent({ ...local, baseline: e.target.value, receipt: null })) return; setFixed(null); }}><option value="">请选择已保存的基线</option>{baselines.map(b => <option key={b.id} value={b.id}>{b.title} · v{b.revision}{b.is_current ? "" : "（历史固定版）"}</option>)}</select></label></div>
    <label className="block space-y-2 text-sm"><span>本次发布说明</span><textarea value={local.reason} maxLength={2000} disabled={disabled || !!local.pending} onChange={e => { saveFromEvent({ ...local, reason: e.target.value, receipt: null }); }}/></label>
    {local.previous && (local.receipt ? <p className="text-sm">已续接固定发布 v{local.previous.revision}，成功发布 v{local.receipt.subject_revision}。</p> : <p className="text-sm">将续接固定发布 v{local.previous.revision}，生成 v{local.previous.revision + 1}。可选择本项目另一版固定制造基线，原发布内容保留。</p>)}
    {previousUnavailable && <p role="status" className="text-sm">所选前版已不是当前发布，请明确选择当前版继续。</p>}
    <p className="subtle">本入口沿用所选基线的固定用途、地点和来源。尚未声明的资源要求、包装及反应计划保留为缺项，发布时会一并显示。</p>
    {local.pending ? <div className="flex flex-wrap gap-2"><Button disabled={disabled} onClick={() => void run(local.pending!)}>{local.pending.stage === "execute" ? "核对原保存请求" : "继续核对原请求"}</Button>{local.pending.stage !== "execute" && <Button variant="outline" disabled={disabled} onClick={() => { if (saveFromEvent({ ...local, pending: null })) setPreview(null); }}>取消本次核对</Button>}</div> : <Button disabled={disabled || failed || !!local.receipt || previousUnavailable || !local.baseline || !local.reason.trim()} onClick={start}>核对具名发布</Button>}
    {versions.length > 0 && <div className="space-y-2"><h3 className="font-medium">已发布的固定版本</h3>{versions.map(v => <div key={v.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border p-3 text-sm"><span>固定发布 v{v.revision} · {v.is_current ? "当前版" : "历史版"} · {v.source_status === "current" ? "来源已核对" : "依据待重核"}</span><div className="flex flex-wrap gap-2">{v.is_current && <Button variant="outline" size="sm" disabled={disabled || failed || !!local.pending || !!preview} onClick={() => continueFrom(v)}>从此版续接</Button>}<Button variant="outline" size="sm" disabled={disabled} onClick={() => void readFixed(v)}>回读固定内容</Button></div></div>)}</div>}
    {cursor && <Button variant="outline" disabled={disabled} onClick={() => void moreHistory()}>读取更早发布记录</Button>}
    {fixed && <div className="space-y-3 rounded-lg border border-border p-3"><h3 className="font-medium">固定发布 v{fixed.revision}</h3><Content body={fixed.body}/>{fixed.gaps.map((g, i) => <p className="text-sm" key={i}>{g.detail}</p>)}</div>}
    <dialog ref={dialog} className="w-[min(48rem,calc(100%-2rem))] max-h-[85vh] overflow-y-auto rounded-lg border border-border bg-background p-5 text-foreground shadow-xl" onCancel={() => setPreview(null)}>{preview && <div className="space-y-4"><h3 className="text-lg font-semibold">具名发布这版制造基线</h3>{preview.command.payload.previous_id && <p className="text-sm">本次续接固定发布 v{preview.command.payload.expected_previous_revision}，具名发布 v{preview.review.after.revision}；原版固定内容保留。</p>}{notice && <p role="status" className="text-sm">{notice}</p>}<p className="text-sm">{preview.review.effect}</p><Content body={preview.review.after.body}/><div className="space-y-2">{preview.review.gaps.map((g, i) => <p key={i} className="text-sm">{g.detail}</p>)}</div><div className="flex flex-wrap gap-2"><Button disabled={busy} onClick={confirm}>本人确认并具名发布</Button><Button variant="outline" disabled={busy} onClick={() => setPreview(null)}>返回核对</Button></div></div>}</dialog>
  </section>;
}
