"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowClockwise, DownloadSimple, FileText, ShieldCheck, UploadSimple, WarningCircle } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { journalStateNames, originalActions, originalReason, originalScope, originalTime, parseStateNames, safeOriginalFailure, scanReplyNames, scanStateNames, securityFor, validWithdrawPreview, withdrawCommand, type OriginalApi, type OriginalFile, type OriginalPending, type WithdrawPreview } from "@/lib/original-security";

type Props = { product: { id: string; revision: number }; originals: OriginalFile[]; api: OriginalApi; onSaved: () => Promise<void> };
type PreviewState = { value: WithdrawPreview; scope: string };
function OriginalStatus({ original }: { original: OriginalFile }) {
  const security = securityFor(original), scan = security.scan;
  return <div className="space-y-3 text-sm [&_*]:min-w-0">
    <dl className="grid gap-3 sm:grid-cols-2">
      <div><dt className="subtle">扫描安全</dt><dd className="mt-1 [overflow-wrap:anywhere]">{scanStateNames[security.state]}</dd></div>
      <div><dt className="subtle">文字解析</dt><dd className="mt-1">{parseStateNames[original.status] ?? "解析状态待核对"}{original.parse_code === "OCR_REQUIRED" && " · OCR 尚未接入"}{original.parse_code === "PARTIAL_TEXT" && " · 部分页缺少文字，需另行核对"}</dd></div>
      <div><dt className="subtle">来源有效性</dt><dd className="mt-1">{security.epoch === 0 ? "当前来源状态尚未取得" : security.source_state === "withdrawn" ? "已撤回 · 禁止新的业务引用" : "来源未撤回 · 使用仍需核对扫描与权限"}{original.artifact_id && "；已有定位派生资料"}</dd></div>
      <div><dt className="subtle">字节生命周期</dt><dd className="mt-1">{security.lifecycle.disposition === "active" ? "原件登记为保留状态" : security.lifecycle.disposition === "quarantined" ? "字节已隔离 · 与扫描结论分开记录" : "字节位置待核对 · 不代表已删除"}<span className="subtle block mt-1">{journalStateNames[security.lifecycle.journal_state] ?? "上传与字节记录需核对"}</span></dd></div>
    </dl>
    {security.reasons.length > 0 && <ul className="space-y-1">{[...new Set(security.reasons)].map(reason => <li key={reason} className="flex items-start gap-2"><WarningCircle className="mt-0.5 shrink-0 text-primary"/><span className="[overflow-wrap:anywhere]">{originalReason(reason)}</span></li>)}</ul>}
    <details><summary className="cursor-pointer font-medium">扫描回执与原件保护</summary><div className="mt-3 space-y-3">
      {scan ? <dl className="grid gap-3 sm:grid-cols-2"><div><dt className="subtle">实际扫描服务</dt><dd className="[overflow-wrap:anywhere]">{scan.scanner}</dd></div><div><dt className="subtle">引擎版本</dt><dd className="[overflow-wrap:anywhere]">{scan.engine_version}</dd></div><div><dt className="subtle">规则版本</dt><dd className="[overflow-wrap:anywhere]">{scan.rules_version}</dd></div><div><dt className="subtle">政策版本</dt><dd className="[overflow-wrap:anywhere]">{scan.policy_version}</dd></div><div><dt className="subtle">扫描请求记录</dt><dd>{originalTime(scan.requested_at)}</dd></div><div><dt className="subtle">实际完成记录</dt><dd>{originalTime(scan.completed_at)}</dd></div></dl> : <p className="subtle">尚无真实扫描回执；未视为扫描通过。</p>}
      {scan && <p>最近请求的真实回执：{scanReplyNames[scan.status] ?? "结果待核对"}。</p>}{scan?.error_code && <p>{originalReason(scan.error_code)}</p>}
      <p>原件已登记并受保护；解析失败也不构成孤儿文件。本安全面板不执行物理删除或存储迁移；访问隔离与恢复须在原件保留区另行核对。</p>
      {security.lifecycle.protection_reasons.length > 0 && <ul className="space-y-1">{[...new Set(security.lifecycle.protection_reasons)].map(reason => <li key={reason}>{originalReason(reason)}</li>)}</ul>}
      <p className="subtle">解析文字不等于安全扫描。撤回只改变来源有效性，字节、派生资料与历史决定保留。</p>
    </div></details>
  </div>;
}

export function OriginalFiles(props: Props) { return <OriginalPanel key={props.product.id} {...props}/>; }
function OriginalPanel({ product, originals, api, onSaved }: Props) {
  const [file, setFile] = useState<File | null>(null), [label, setLabel] = useState(""), [visibility, setVisibility] = useState("private");
  const [pending, setPending] = useState<OriginalPending | null>(null), [preview, setPreview] = useState<PreviewState | null>(null), [withdrawId, setWithdrawId] = useState(""), [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const lock = useRef(false), alive = useRef(true), pendingRef = useRef<OriginalPending | null>(null), dialog = useRef<HTMLDialogElement>(null), trigger = useRef<HTMLElement | null>(null), fileInput = useRef<HTMLInputElement>(null);
  const selected = originals.find(original => original.id === withdrawId), previewOriginal = originals.find(original => original.id === preview?.value.command.payload.original_id);
  const currentPreview = preview && previewOriginal && preview.scope === originalScope(product, previewOriginal) ? preview : null;
  const editing = !busy && !pending && !currentPreview;
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => { if (currentPreview) { if (!dialog.current?.open) dialog.current?.showModal(); } else { dialog.current?.close(); if (preview) void Promise.resolve().then(() => { if (alive.current) { setPreview(null); setNotice("型号范围、来源状态或权限已变化；旧预览已废弃，请刷新后重新核对。"); } }); } }, [currentPreview, preview]);
  function waiting(value: OriginalPending | null) { pendingRef.current = value; setPending(value); }
  function closePreview() { if (lock.current) return; setPreview(null); dialog.current?.close(); trigger.current?.focus(); }
  async function refresh() { if (lock.current) return; lock.current = true; setBusy(true); setError(""); try { await onSaved(); } catch { if (alive.current) setError("列表读取暂未完成，请再次刷新；这不改变已保存的回执。"); } finally { lock.current = false; if (alive.current) setBusy(false); } }
  async function perform(makeRequest: () => OriginalPending | Promise<OriginalPending>, element?: HTMLElement) {
    if (lock.current) return; lock.current = true; setBusy(true); setError(""); setNotice(""); if (element) trigger.current = element;
    let attempted = false, committed = false;
    try {
      const request = await makeRequest(); waiting(request); attempted = true;
      if (request.stage === "preview") {
        const original = originals.find(value => value.id === request.command.payload.original_id); if (!original) throw new Error("原件当前不可读，保留原请求核对权限。");
        const scope = originalScope(product, original), result = await api<unknown>("v1/commands/preview", request.command);
        if (!validWithdrawPreview(result, request.command)) throw new Error("未取得完整且绑定原请求的预览，请按原请求核对。");
        if (!alive.current) return; waiting(null); setPreview({ value: result, scope });
      } else if (request.stage === "execute") {
        const receipt = await api<{ id: string; subject_id: string; subject_type: string }>("v1/commands", request.command);
        if (!receipt.id || receipt.subject_type !== "uploaded_original" || receipt.subject_id !== request.command.payload.original_id) throw new Error("尚未完整核对撤回回执。");
        committed = true; if (!alive.current) return; waiting(null); setPreview(null); dialog.current?.close(); setWithdrawId(""); setReason("");
        setNotice("来源撤回已记录。下载、解析与新的业务引用停止；原件字节和历史决定保留，依赖结果需重新核对。");
        await onSaved();
      } else if (request.stage === "scan") {
        await api(`v1/products/${product.id}/originals/${request.originalId}/scan`, request.request);
        committed = true; if (!alive.current) return; waiting(null); setNotice("扫描请求已取得回执，请以刷新后的实际扫描状态为准；这不授予生产使用资格。"); await onSaved();
      } else {
        await api(`v1/products/${product.id}/originals`, request.request);
        committed = true; if (!alive.current) return; waiting(null); setFile(null); if (fileInput.current) fileInput.current.value = ""; setNotice("原件已保存。扫描与解析分别核对；尚未取得有效扫描回执时不能下载。"); await onSaved();
      }
    } catch (failure) {
      if (!alive.current) return;
      if (committed) setError("操作已保存，但最新列表暂未取得。请刷新核对，不必重新提交已完成操作。");
      else if (!attempted) setError(failure instanceof Error ? failure.message : "请核对文件和填写内容。");
      else { const failed = safeOriginalFailure(failure); setError(failed.message); if ([400, 401, 403, 404, 409, 422].includes(failed.status ?? 0)) { waiting(null); setPreview(null); dialog.current?.close(); } else if (pendingRef.current?.stage === "execute") { setPreview(null); dialog.current?.close(); } }
    } finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  function upload(element: HTMLElement) { void perform(async () => {
    if (pendingRef.current) return pendingRef.current;
    if (!file || !label.trim()) throw new Error("请选择原件并说明来源。");
    if (!file.size || file.size > 8_388_608 || !/\.(txt|md|pdf|xlsx)$/i.test(file.name)) throw new Error("请使用 8MB 以内的 UTF-8 文本、PDF 或 XLSX。");
    const bytes = new Uint8Array(await file.arrayBuffer()); let binary = "";
    for (let offset = 0; offset < bytes.length; offset += 8192) binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
    return { stage: "upload", request: { filename: file.name, title: file.name, source_label: label.trim(), visibility, content_base64: btoa(binary), expected_revision: product.revision, idempotency_key: crypto.randomUUID() } };
  }, element); }
  function scan(original: OriginalFile, element: HTMLElement) { void perform(() => { if (!originalActions(original).scan) throw new Error("当前无法扫描此原件，请刷新核对权限与状态。"); return { stage: "scan", originalId: original.id, request: { expected_epoch: securityFor(original).epoch, idempotency_key: crypto.randomUUID() } }; }, element); }
  function prepareWithdraw(element: HTMLElement) { void perform(() => { if (!selected) throw new Error("请选择当前可读原件。"); return { stage: "preview", command: withdrawCommand(product, selected, reason, crypto.randomUUID(), crypto.randomUUID()) }; }, element); }
  return <section className="panel mb-6 min-w-0 [&_*]:min-w-0">
    <div className="flex flex-wrap items-start justify-between gap-3"><h2 className="flex items-center gap-2 font-semibold"><FileText/>原件、安全与来源状态</h2><Button variant="outline" size="sm" disabled={busy} onClick={() => void refresh()}><ArrowClockwise/>刷新状态</Button></div>
    <p className="subtle my-3">UTF-8 文本、PDF、XLSX，最大 8MB。扫描、解析、来源有效性和字节保留分别记录；当前仅用于合成验证，尚未完成生产资格认定，OCR 尚未接入。</p>
    {error && <p role="alert" className="my-3 text-sm text-destructive [overflow-wrap:anywhere]">{error}</p>}{notice && <p role="status" className="my-3 text-sm [overflow-wrap:anywhere]">{notice}</p>}
    {pending && <div className="mb-4 space-y-3 rounded-lg border border-primary p-3"><p className="text-sm">{pending.stage === "upload" ? "原上传结果待核对；本页暂存相同文件和请求，未把文件字节长期存入本机。核对完成前请保留此页面。" : pending.stage === "scan" ? "扫描请求结果待核对；不会另造一次扫描请求。" : "来源撤回请求结果待核对；核对完成前保留原请求与原因。"}</p><Button variant="outline" disabled={busy} onClick={() => void perform(() => pending)}>核对原{pending.stage === "upload" ? "上传" : pending.stage === "scan" ? "扫描" : pending.stage === "preview" ? "预览" : "撤回"}请求</Button></div>}
    <details><summary className="cursor-pointer font-medium">上传并保留资料原件</summary><form className="mt-4" onSubmit={event => { event.preventDefault(); upload(event.currentTarget); }}><fieldset disabled={!editing}>
      <label>文件<input ref={fileInput} type="file" accept=".txt,.md,.pdf,.xlsx" required onChange={event => setFile(event.target.files?.[0] ?? null)}/></label>
      <label>来源说明<input value={label} required maxLength={200} onChange={event => setLabel(event.target.value)} placeholder="谁提供的，或来自哪里"/></label>
      <label>资料受众<select value={visibility} onChange={event => setVisibility(event.target.value)}><option value="private">仅我可见</option><option value="category">品类授权成员</option></select></label>
      <Button type="submit"><UploadSimple/>保存原件</Button><p className="subtle mt-3">保存不等于扫描通过；文件本身不写入本机长期草稿。未知回执先核对原请求。</p>
    </fieldset></form></details>
    <div className="mt-5 space-y-4">{originals.map(original => { const actions = originalActions(original), security = securityFor(original); return <article key={original.id} className="space-y-4 rounded-lg border border-border p-3 sm:p-4">
      <div><h3 className="font-medium [overflow-wrap:anywhere]">{original.title}</h3><p className="subtle mt-1 [overflow-wrap:anywhere]">{original.filename} · {(original.byte_count / 1024).toFixed(1)} KB{original.visibility && ` · ${original.visibility === "private" ? "仅本人" : original.visibility === "audience" ? "指定评审人" : "品类授权成员"}`}</p>{original.source_label && <p className="mt-1 text-sm whitespace-pre-wrap [overflow-wrap:anywhere]">来源：{original.source_label}</p>}</div>
      <OriginalStatus original={original}/><div className="flex flex-wrap gap-2">
        <Button variant="outline" disabled={!editing || !actions.scan} onClick={event => scan(original, event.currentTarget)}><ShieldCheck/>{security.scan ? "重新请求扫描" : "请求扫描"}</Button>
        {actions.download && editing ? <a className="inline-flex min-h-9 items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm text-primary [overflow-wrap:anywhere]" href={`/api/v1/products/${product.id}/originals/${original.id}/download`}><DownloadSimple/>下载原件</a> : <Button variant="outline" disabled><DownloadSimple/>下载 · 当前不可用</Button>}
        <Button variant="outline" disabled={!editing || !actions.withdraw} onClick={() => { setWithdrawId(original.id); setReason(""); setError(""); }}>撤回来源 · 先核对影响</Button>
      </div>{security.source_state === "withdrawn" && <p className="text-sm">来源已失效，历史内容与决定保留；依赖的准备、供给、成本和验证结果需重新核对。</p>}
    </article>; })}{!originals.length && <p className="subtle">暂无当前可读原件。保存后可分别核对扫描和解析状态。</p>}</div>
    {selected && <form className="mt-5 rounded-lg border border-border p-4" onSubmit={event => { event.preventDefault(); prepareWithdraw(event.currentTarget); }}><h3 className="font-semibold [overflow-wrap:anywhere]">撤回来源：{selected.title}</h3><p className="subtle my-3">停止将此原件作为当前依据；原件字节与历史保留。先读取服务器预览，再一次确认。</p><fieldset disabled={!editing || !originalActions(selected).withdraw}><label>具名撤回原因<textarea required minLength={3} maxLength={2000} value={reason} onChange={event => setReason(event.target.value)}/></label><div className="flex flex-wrap gap-2"><Button type="submit">核对来源失效影响</Button><Button type="button" variant="outline" onClick={() => setWithdrawId("")}>取消准备</Button></div></fieldset></form>}
    <dialog ref={dialog} className="!w-[min(640px,calc(100vw-32px))] max-h-[90vh] overflow-auto" onCancel={event => { event.preventDefault(); if (!busy) closePreview(); }}>
      {currentPreview && <div className="min-w-0 space-y-4 [&_*]:min-w-0"><h3 className="text-lg font-semibold">一次确认：撤回原件来源</h3><p className="font-medium [overflow-wrap:anywhere]">{currentPreview.value.review.before.title}</p><p className="text-sm whitespace-pre-wrap [overflow-wrap:anywhere]">{currentPreview.value.review.effect}</p><dl className="space-y-3 text-sm"><div><dt className="subtle">来源有效性</dt><dd>当前有效 → 已撤回；停止下载、解析与新的业务引用。</dd></div><div><dt className="subtle">原件与历史</dt><dd>字节、既有派生资料和历史决定保留，不执行物理删除。</dd></div><div><dt className="subtle">本次具名原因</dt><dd className="whitespace-pre-wrap [overflow-wrap:anywhere]">{currentPreview.value.review.after.reason}</dd></div></dl><p className="subtle">依据变化后，依赖结果需重新核对。确认有效至 {originalTime(currentPreview.value.expires_at)}；范围变化会废弃此预览。</p><div className="flex flex-wrap justify-end gap-2"><Button variant="outline" disabled={busy || !!pending} onClick={closePreview}>返回编辑</Button><Button disabled={busy || !!pending} onClick={() => { if (Date.parse(currentPreview.value.expires_at) <= Date.now()) { closePreview(); setError("预览已过期，请重新核对当前来源影响。"); return; } void perform(() => ({ stage: "execute", command: currentPreview.value.command })); }}>确认撤回此次来源</Button></div></div>}
    </dialog>
  </section>;
}
