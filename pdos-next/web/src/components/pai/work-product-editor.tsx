"use client";

import { useEffect, useRef, useState } from "react";
import { Check, PencilSimple, X } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { PaiMobileWorkspaceSwitch } from "@/components/pai-conversation";
import { browserApi } from "@/lib/browser-api";
import { reviseWorkProduct, type WorkProduct, type WorkProductApi } from "@/lib/work-products";
import styles from "./work-product-editor.module.css";

type Pending = { requestKey: string; title: string; body: string };

function markdownCells(line: string) {
  const cells = line.split("|").map(cell => cell.trim().replace(/<br\/?>/g, "\n"));
  if (cells[0] === "") cells.shift();
  if (cells.at(-1) === "") cells.pop();
  return cells;
}
function markdownSeparator(cells: string[]) {
  return cells.every(cell => /^[-:\s]+$/.test(cell));
}

function Body({ product }: { product: WorkProduct }) {
  if (product.kind === "table") {
    const lines = product.body.split("\n").filter(line => line.includes("|"));
    const cells = lines.map(markdownCells);
    const [header = [], ...rows] = cells;
    return <div className={styles.tableScroll}><table><thead><tr>{header.map((cell, index) => <th key={index}>{cell}</th>)}</tr></thead><tbody>{rows.filter(row => !markdownSeparator(row)).map((row, index) => <tr key={index}>{row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}</tr>)}</tbody></table></div>;
  }
  return <div className={styles.document}>{product.body.split("\n").map((line, index) => line.startsWith("### ") ? <h4 key={index}>{line.slice(4)}</h4> : line.startsWith("## ") ? <h3 key={index}>{line.slice(3)}</h3> : line.startsWith("# ") ? <h2 key={index}>{line.slice(2)}</h2> : line ? <p key={index}>{line}</p> : null)}</div>;
}

export function WorkProductEditor({ product, original, open, onClose, onSaved, onReload, onUnavailable, onMobileChat, api = browserApi }: {
  product: WorkProduct;
  original?: WorkProduct | null;
  open: boolean;
  onClose: () => void;
  onSaved: (product: WorkProduct) => void;
  onReload: (product: WorkProduct) => Promise<WorkProduct | null>;
  onUnavailable: () => void;
  onMobileChat?: () => void;
  api?: WorkProductApi;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(product.title);
  const [body, setBody] = useState(product.body);
  const [pending, setPending] = useState<Pending | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const storageKey = `pdos-next:work-product:${product.id}:${product.revision}`;
  useEffect(() => { if (open) dialog.current?.show(); else dialog.current?.close(); }, [open]);
  useEffect(() => {
    let active = true;
    void Promise.resolve().then(() => {
      if (!active) return;
      try {
        const saved = JSON.parse(sessionStorage.getItem(storageKey) ?? "null");
        if (saved && typeof saved.requestKey === "string" && typeof saved.title === "string" && typeof saved.body === "string") {
          setPending(saved); setTitle(saved.title); setBody(saved.body);
        }
      } catch { /* The editor remains available in memory. */ }
    });
    return () => { active = false; };
  }, [storageKey]);
  function clearPending() {
    setPending(null);
    try { sessionStorage.removeItem(storageKey); } catch { /* Server history remains authoritative. */ }
  }
  async function save() {
    if (busy) return;
    setBusy(true); setError("");
    const request = pending ?? { requestKey: crypto.randomUUID(), title: title.trim(), body: body.trim() };
    try {
      if (!request.title || !request.body) throw new Error("成果标题和正文不能为空。");
      setPending(request);
      try { sessionStorage.setItem(storageKey, JSON.stringify(request)); } catch { throw new Error("本机存储失败，尚未发送保存请求。请恢复后重试。"); }
      const updated = await reviseWorkProduct(api, product, request.title, request.body, request.requestKey);
      clearPending(); onSaved(updated); setEditing(false);
      requestAnimationFrame(() => heading.current?.focus());
    } catch (failure) {
      const status = (failure as { status?: number }).status;
      if (status === 409) {
        clearPending();
        const latest = await onReload(product);
        if (latest && latest.root_id === product.root_id && latest.revision > product.revision) {
          onSaved(latest); setEditing(true);
          setError(`成果已更新到 v${latest.revision}。你的修改仍保留，请核对后再次保存。`);
          return;
        }
      }
      if (status === 401 || status === 403) { clearPending(); onUnavailable(); }
      else if (status && status >= 400 && status < 500 && status !== 408 && status !== 429) clearPending();
      setError(failure instanceof Error ? failure.message : "保存结果待核对，原请求已保留。");
    } finally { setBusy(false); }
  }
  return <dialog ref={dialog} className="candidate-editor material-workspace" aria-label={`${product.kind === "table" ? "表格" : "文档"}成果编辑区`} onCancel={event => { event.preventDefault(); onClose(); }}>
    <header className="candidate-editor-heading"><div><h3 ref={heading} tabIndex={-1}>{product.title}</h3><p className="subtle">{product.kind === "table" ? "表格" : "文档"} · v{product.revision} · {product.origin === "ai_draft" ? "AI 原文" : "人工修订"}</p></div><PaiMobileWorkspaceSwitch view="chat" onClick={onMobileChat ?? onClose} /><Button size="sm" variant="ghost" aria-label="收起成果" onClick={onClose}><X size={16}/></Button></header>
    <div className={`candidate-editor-body ${styles.editor}`}>
      {error && <p role="alert">{error}</p>}
      {pending && <div className={styles.recovery}><p>保存结果待核对，原请求已保留。再次提交只会核对同一请求。</p><Button size="sm" variant="outline" disabled={busy} onClick={() => void save()}>核对原保存请求</Button></div>}
      {product.source_currentness === "updated" && <p role="status" className="subtle">来源资料已更新，保留当前成果；引用其中事实前请重新核对。</p>}
      {editing ? <div className={styles.form}><label>成果标题<input aria-label="成果标题" value={title} disabled={busy} onChange={event => setTitle(event.target.value)} maxLength={200}/></label><label>成果正文<textarea aria-label="编辑成果内容" value={body} disabled={busy} onChange={event => setBody(event.target.value)} maxLength={200000}/></label><div className={styles.actions}><Button size="sm" variant="ghost" disabled={busy} onClick={() => { setTitle(product.title); setBody(product.body); setEditing(false); }}>取消</Button><Button size="sm" disabled={busy} onClick={() => void save()}><Check size={14}/>保存修改</Button></div></div>
        : <><div className={styles.toolbar}><span>仅你可见 · 未发布到项目</span><Button size="sm" variant="ghost" disabled={busy} onClick={() => setEditing(true)}><PencilSimple size={14}/>继续编辑</Button></div><Body product={product}/>{original && original.body !== product.body && <details className={styles.original}><summary>查看原 AI 内容</summary><Body product={original}/></details>}</>}
    </div>
  </dialog>;
}
