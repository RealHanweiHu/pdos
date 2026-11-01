"use client";

import { useEffect, useRef, useState } from "react";
import { UploadSimple } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { createUploadIntent, paiUploadApi, readUploadReceipt, readUploadTarget, restoreUploadPointer, uploadOriginal } from "@/lib/pai-upload";
import type { PaiUploadApi, PaiUploadIntent, PaiUploadPointer, PaiUploadReceipt, PaiUploadScope, PaiUploadTarget } from "@/lib/pai-upload";
import { originalReason, parseStateNames, scanReplyNames, scanStateNames } from "@/lib/original-security";
import styles from "./file-upload.module.css";

type Props = { api: PaiUploadApi; uploadApi?: PaiUploadApi; scope: PaiUploadScope; disabled?: boolean };
const scopeKey = (scope: PaiUploadScope) => JSON.stringify([scope.principalId, scope.categoryId, scope.productId, scope.proposalId]);
const statusOf = (failure: unknown) => (failure as { status?: number } | null)?.status;
const message = (failure: unknown) => failure instanceof Error ? failure.message : "上传记录暂不可读，请保留原请求核对。";
const privateFailure = (failure: unknown) => [401, 403, 404].includes(statusOf(failure) ?? 0);
const memoryWarning = "原请求仅暂存在此页；刷新后可能无法自动恢复，请保留此页核对。";

/** Upload is independent from starting a Run. This panel never attaches or selects a source. */
export function FileUpload(props: Props) {
  const uploadApi = props.uploadApi ?? paiUploadApi;
  const [binding, setBinding] = useState({ api: props.api, uploadApi, revision: 0 });
  if (binding.api !== props.api || binding.uploadApi !== uploadApi) { setBinding({ api: props.api, uploadApi, revision: binding.revision + 1 }); return null; }
  return <ScopedFileUpload key={`${binding.revision}:${scopeKey(props.scope)}`} {...props} uploadApi={uploadApi} />;
}

function UploadReading({ value }: { value: PaiUploadReceipt }) {
  const original = value.original;
  if (value.state !== "committed") return <div className={styles.reading} role="status"><strong>{value.state === "reserved" ? "原请求已有上传准备记录，保存结果仍待核对。" : value.state === "abandoned" ? "服务器已记录该上传准备终止，未读到原件保存回执。" : "当前尚未观察到该原请求的保存回执。"}</strong><p>{value.state === "abandoned" ? "该准备记录已明确终止；核对后可另选文件。此页不会删除服务器记录。" : "这不表示上传失败。刷新只读取同一请求，不自动发起另一份上传。"}</p></div>;
  return <section className={styles.reading} aria-label="原件上传实际结果"><strong>已读回原件保存回执</strong>
    {original ? <><p>{original.title} · {original.filename} · 原件版本 v{original.revision}</p><p>解析：{parseStateNames[original.parse_status] ?? "状态待核对"}；扫描：{scanReplyNames[original.scan_status] ?? "状态待核对"}。</p><p>当前安全状态：{scanStateNames[original.security.state as keyof typeof scanStateNames] ?? "待核对"}；来源{original.security.source_state === "withdrawn" ? "已撤回" : "尚未撤回；是否可选择以当前校验为准"}。</p>{original.security.reasons.map(reason => <p key={reason}>{originalReason(reason)}</p>)}</> : <p>原件头当前不可读，仅展示已核对的保存回执。</p>}
    {value.source?.availability.available ? <p>已生成可用登记来源 v{value.source.artifact_revision}。请在“已登记来源”刷新后手动选择该固定版本；此文件尚未随新工作发送。</p> : <p>当前尚无可选择的可用登记来源。原件保存、解析与安全状态分别核对；不要把原件版本用作运行来源版本。</p>}
    <details className={styles.details}><summary>回执与固定标识</summary><p>回执 {value.receipt!.id}</p><p>原件 {value.receipt!.subject_id}</p>{original && <p>原件当前版本 {original.revision}；安全记录版本 {original.security.epoch}</p>}{value.source && <p>登记来源 {value.source.artifact_id} · v{value.source.artifact_revision}</p>}</details>
  </section>;
}

function ScopedFileUpload({ api, uploadApi, scope, disabled }: Props & { uploadApi: PaiUploadApi }) {
  const [open, setOpen] = useState(false), [restoring, setRestoring] = useState(true);
  const [target, setTarget] = useState<PaiUploadTarget | null>(null);
  const [pointer, setPointer] = useState<PaiUploadPointer | null>(null);
  const [reading, setReading] = useState<PaiUploadReceipt | null>(null);
  const [file, setFile] = useState<File | null>(null), [title, setTitle] = useState(""), [sourceLabel, setSourceLabel] = useState("");
  const [busy, setBusy] = useState(false), [hidden, setHidden] = useState(false), [journalInvalid, setJournalInvalid] = useState(false);
  const [error, setError] = useState(""), [notice, setNotice] = useState(""), [warning, setWarning] = useState("");
  const lifecycle = useRef(0), lock = useRef(false), input = useRef<HTMLInputElement | null>(null);
  const original = useRef<PaiUploadIntent | null>(null);
  const { principalId, categoryId, productId, proposalId } = scope;
  const storageKey = `pdos-next:pai-upload:${scopeKey(scope)}`;
  useEffect(() => {
    let active = true; const counter = lifecycle, own = counter.current;
    void Promise.resolve().then(async () => {
      let raw: string | null = null;
      try { raw = localStorage.getItem(storageKey); } catch { if (active) setWarning(memoryWarning); }
      if (!raw) return;
      let saved: unknown;
      try { saved = JSON.parse(raw); } catch { setJournalInvalid(true); throw new Error("本地原上传指针无法解析，未覆盖该记录。请核对原上下文中的上传记录。"); }
      const restored = await restoreUploadPointer(saved, { principalId, categoryId, productId, proposalId });
      if (!active || counter.current !== own) return;
      if (!restored || restored.metadata.visibility !== "private") { setJournalInvalid(true); throw new Error("本地原上传指针无法核对，未覆盖该记录。请先核对原上下文中的上传记录。"); }
      setPointer(restored); setOpen(true);
      const value = await readUploadReceipt(api, { principalId, categoryId, productId, proposalId }, restored);
      if (active && counter.current === own) { setReading(value); setHidden(false); }
    }).catch(failure => { if (active && counter.current === own) { setReading(null); setTarget(null); setHidden(privateFailure(failure)); setError(message(failure)); setOpen(true); } })
      .finally(() => { if (active && counter.current === own) setRestoring(false); });
    return () => { active = false; counter.current++; };
  }, [api, principalId, categoryId, productId, proposalId, storageKey]);

  function remember(value: PaiUploadPointer) {
    setPointer(value);
    try { localStorage.setItem(storageKey, JSON.stringify(value)); }
    catch { setWarning(memoryWarning); }
  }
  function clearFile() { setFile(null); if (input.current) input.current.value = ""; }
  async function loadTarget() {
    if (lock.current || restoring) return;
    lock.current = true; setBusy(true); setTarget(null); setError(""); const own = lifecycle.current;
    try { const value = await readUploadTarget(api, scope); if (lifecycle.current === own) { setTarget(value); setHidden(false); } }
    catch (failure) { if (lifecycle.current === own) { setTarget(null); setReading(null); clearFile(); setHidden(privateFailure(failure)); setError(message(failure)); } }
    finally { if (lifecycle.current === own) { lock.current = false; setBusy(false); } }
  }
  async function inspect() {
    if (!pointer || lock.current || restoring) return;
    lock.current = true; setBusy(true); setReading(null); setError(""); const own = lifecycle.current;
    try { const value = await readUploadReceipt(api, scope, pointer); if (lifecycle.current === own) { setReading(value); setHidden(false); if (value.state === "committed") { clearFile(); original.current = null; } } }
    catch (failure) { if (lifecycle.current === own) { setReading(null); setTarget(null); clearFile(); setHidden(privateFailure(failure)); setError(message(failure)); } }
    finally { if (lifecycle.current === own) { lock.current = false; setBusy(false); } }
  }
  function choose(selected: File | null) {
    if (disabled || busy || restoring || hidden || journalInvalid || !target?.authorization.can_write || reading?.state === "committed") return;
    if (selected && (!target.constraints.extensions.some(extension => selected.name.toLowerCase().endsWith(extension)) || selected.size < 1 || selected.size > target.constraints.max_bytes)) { clearFile(); setError("请选择非空 TXT、MD、PDF 或 XLSX 文件，且不超过 8 MiB。"); return; }
    setFile(selected); setError(""); setNotice(""); if (selected && !pointer) setTitle(selected.name);
  }
  async function submit() {
    if (disabled || lock.current || restoring || hidden || journalInvalid || !file || !target?.authorization.can_write || reading?.state === "committed") return;
    lock.current = true; setBusy(true); setError(""); setNotice(""); const own = lifecycle.current;
    try {
      if (pointer) {
        const latest = await readUploadReceipt(api, scope, pointer);
        if (lifecycle.current !== own) return;
        setReading(latest);
        if (latest.state === "committed") { clearFile(); original.current = null; setNotice("已读回同一上传的保存回执，未再次上传。"); return; }
        if (latest.state === "abandoned") throw new Error("服务器已终止原上传准备，请先核对该记录。此处不会自动建立另一份请求。");
      }
      const intent = await createUploadIntent(file, { title, sourceLabel, visibility: "private" }, target, pointer ?? undefined);
      if (lifecycle.current !== own) return;
      original.current = intent; remember(intent.pointer);
      // The library also hashes and validates the request asynchronously. Gate the actual transport call.
      const scopedPost: PaiUploadApi = (path, body) => lifecycle.current === own ? uploadApi(path, body) : Promise.reject(new Error("上传上下文已切换，未继续发送。"));
      const result = await uploadOriginal(scopedPost, scope, intent);
      if (lifecycle.current !== own) return;
      setReading(result.reading); setHidden(false); clearFile();
      if (result.reading.state === "committed") { original.current = null; setNotice("原件已保存并经原请求回读核对；尚未随任何工作发送。"); }
      else if (result.reading.state === "not_observed" && [400, 413, 415, 422].includes(statusOf(result.postError) ?? 0)) {
        setNotice("上传请求已被明确拒绝，且未观察到该请求的保存回执。可以重新选择文件。");
        setPointer(null); setReading(null); original.current = null; setTarget(null);
        try { localStorage.removeItem(storageKey); } catch { setWarning(memoryWarning); }
      } else { setNotice("原上传结果仍待核对。请保留原请求；若需重试，重新选择相同字节的文件。"); if (result.postError) { setError(message(result.postError)); if (privateFailure(result.postError)) { setHidden(true); setTarget(null); setReading(null); } } }
    } catch (failure) {
      if (lifecycle.current === own) { setReading(null); clearFile(); if (privateFailure(failure)) { setHidden(true); setTarget(null); } setError(message(failure)); setNotice((failure as { postResponseReceived?: boolean }).postResponseReceived ? "已收到上传响应，回读暂不可用。原请求仍保留，当前只核对原请求。" : original.current ? "原上传请求仍保留；当前只核对原请求，不自动再上传。" : "尚未重新上传，请核对文件与原请求。"); }
    } finally { if (lifecycle.current === own) { lock.current = false; setBusy(false); } }
  }
  function nextFile() {
    if (busy || restoring || !reading || !["committed", "abandoned"].includes(reading.state)) return;
    try { localStorage.removeItem(storageKey); } catch { setWarning(memoryWarning); }
    setPointer(null); setReading(null); original.current = null; clearFile(); setTitle(""); setSourceLabel(""); setTarget(null); setNotice("仅结束本页的回读指针，服务器原件与回执保留。");
  }
  const visiblePointer = !hidden && !(reading?.state === "committed" && reading.original === null) ? pointer : null;
  const canChoose = !disabled && !busy && !restoring && !hidden && !journalInvalid && !!target?.authorization.can_write && reading?.state !== "committed" && reading?.state !== "abandoned";
  return <div className={styles.upload}>
    <Button type="button" size="sm" variant="ghost" disabled={disabled || restoring} aria-expanded={open} onClick={() => { setOpen(value => !value); if (!open && !target && !pointer) void loadTarget(); }}><UploadSimple size={13} aria-hidden="true" />上传新文件</Button>
    {(file || pointer) && <p className={styles.hint}>{reading?.state === "committed" ? "已保存，尚未携带。" : "文件上传待核对，尚未携带。"}发送只使用“已登记来源”中手选的资料。</p>}
    {open && <section className={styles.panel} aria-label="上传新文件">
      <div className={styles.heading}><strong>上传新文件</strong><Button type="button" size="sm" variant="ghost" disabled={disabled || busy || restoring} onClick={() => void loadTarget()}>核对上传目标</Button></div>
      <p className={styles.hint}>归属：{productId ? "当前选择的型号" : "当前品类资料根"}。仅本人可见。{proposalId && `文件先保留在${productId ? "型号" : "品类"}资料中；提案客户输入需另行挂接。`}</p>
      <p className={styles.hint}>支持 TXT、MD、PDF、XLSX，非空且不超过 8 MiB。上传不启动工作，不会自动确认需求或作为工作依据。</p>
      {restoring && <p role="status">正在核对本地原请求…</p>}{busy && <p role="status">正在核对上传请求…</p>}{error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}{warning && <p role="status" className={styles.warning}>{warning}</p>}
      {hidden ? <p className={styles.hint}>当前身份或范围不可读，已隐藏原文件资料。原请求指针仍保留，请回到原上下文核对。</p> : <>
        {target && <details className={styles.details}><summary>上传归属标识</summary><p>品类 {categoryId}</p><p>{target.target.kind === "product" ? "型号" : "品类资料"} {target.target.id} · v{target.target.revision}</p>{proposalId && <p>提案 {proposalId}（未自动挂接文件）</p>}</details>}
        {target && <p className={styles.hint}>{target.authorization.can_write ? `已核对上传目标版本 v${target.target.revision}；保存时仍由服务器核对权限。` : "当前范围只有读取权限，不能上传新文件。"}</p>}
        {visiblePointer && <details className={styles.details}><summary>原上传请求 · 固定文件与范围</summary><p>{visiblePointer.metadata.filename} · {visiblePointer.metadata.title}</p><p>来源说明：{visiblePointer.metadata.source_label}</p><p>原目标：{visiblePointer.target.kind === "product" ? "型号" : "品类根"} {visiblePointer.target.id} · v{visiblePointer.metadata.expected_revision}</p><p>可见性：仅本人</p><p>请求 {visiblePointer.request_key}</p><p>文件 SHA256 {visiblePointer.file.content_hash}</p><p>请求摘要 {visiblePointer.request_digest}</p></details>}
        {reading && <UploadReading value={reading} />}
        {!journalInvalid && reading?.state !== "committed" && reading?.state !== "abandoned" && <>
          <div className={styles.drop} onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); if (event.dataTransfer.files.length !== 1) { setError("请一次选择一份文件。"); return; } choose(event.dataTransfer.files[0]); }}>
            <label>拖入文件，或选择{pointer ? "原文件（须为相同字节）" : "文件"}<input ref={input} type="file" accept=".txt,.md,.pdf,.xlsx" disabled={!canChoose} onChange={event => choose(event.target.files?.[0] ?? null)} /></label>
            {file && <p className={styles.hint}>待核对：{file.name} · {file.size} 字节，尚未携带。</p>}
          </div>
          {!pointer && <div className={styles.fields}><label>资料标题<input value={title} disabled={!canChoose} onChange={event => setTitle(event.target.value)} /></label><label>来源说明<input value={sourceLabel} disabled={!canChoose} onChange={event => setSourceLabel(event.target.value)} placeholder="例如：本人提供的客户规格原件" /></label></div>}
          <div className={styles.actions}><Button type="button" size="sm" disabled={!canChoose || !file || !pointer && (!title.trim() || !sourceLabel.trim())} onClick={() => void submit()}>{pointer ? "核对并重试原上传" : "本人确认上传"}</Button>{file && <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => { clearFile(); setNotice("本次不携带此文件；已有原上传请求如有仍保留核对。"); }}>本次不携带此文件</Button>}</div>
        </>}
      </>}
      {pointer && <Button type="button" size="sm" variant="outline" disabled={disabled || busy || restoring} onClick={() => void inspect()}>核对原上传记录</Button>}
      {!hidden && reading && ["committed", "abandoned"].includes(reading.state) && <Button type="button" size="sm" variant="ghost" disabled={disabled || busy} onClick={nextFile}>上传另一份文件</Button>}
      <p className={styles.hint}>上传中的文件尚未携带；你仍可发送新工作，发送只使用已登记来源中手选的资料。</p>
    </section>}
  </div>;
}
