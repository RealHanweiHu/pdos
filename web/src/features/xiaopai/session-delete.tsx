"use client";

import { useEffect, useRef, useState } from "react";
import { Trash } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { deletedSummary, deletionPath, validDeleted, validPreview, type SessionDeleted, type SessionDeletionPreview } from "@/lib/session-deletion";
import styles from "./session-delete.module.css";

type Api = <T>(path: string, body?: unknown) => Promise<T>;

/**
 * Confirmation for deleting one own Session (P121 第 8 项). The server's preview says
 * what goes now, what expires later and what stays; this panel shows it before the
 * owner confirms, and the same request key is reused if the result is unknown.
 */
export function SessionDeleteConfirm({ api, categoryId, sessionId, title, disabled = false, onCancel, onDeleted }: {
  api: Api; categoryId: string | null; sessionId: string; title: string; disabled?: boolean;
  onCancel: () => void; onDeleted: (result: SessionDeleted) => void;
}) {
  const path = deletionPath(categoryId, sessionId);
  const [state, setState] = useState<{ path: string; preview?: SessionDeletionPreview; error?: string }>({ path });
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState("");
  const [attempt, setAttempt] = useState(0);
  const requestKey = useRef<string | null>(null);
  const panel = useRef<HTMLElement | null>(null);
  useEffect(() => {
    let live = true;
    void api<unknown>(path).then(value => {
      if (!live) return;
      if (!validPreview(value, sessionId)) setState({ path, error: "删除前的核对结果无法读取，请重试。" });
      else setState({ path, preview: value });
    }).catch(error => {
      if (!live) return;
      setState({ path, error: (error as { status?: number }).status === 404 ? "会话不存在或已删除。" : "删除前的核对结果暂不可读，请重试。" });
    });
    return () => { live = false; };
  }, [api, path, sessionId, attempt]);
  const preview = state.path === path ? state.preview : undefined;
  const loadError = state.path === path ? state.error : undefined;
  // The panel may open above a long thread or below the fold of the list: bring it into view,
  // again once the preview has filled it in.
  const shown = preview ? "preview" : loadError ? "error" : "loading";
  useEffect(() => { panel.current?.scrollIntoView?.({ block: "nearest" }); }, [shown]);
  async function confirm() {
    if (!preview || preview.blocked || busy || disabled) return;
    setBusy(true); setFailure("");
    requestKey.current ??= crypto.randomUUID();
    try {
      const result = await api<unknown>(path, { request_key: requestKey.current });
      if (!validDeleted(result, sessionId)) throw new Error("删除结果无法核对，请刷新会话列表确认。");
      requestKey.current = null;
      onDeleted(result);
    } catch (error) {
      const status = (error as { status?: number }).status;
      // A definite refusal starts over; an unknown result keeps the same request key.
      if (status !== undefined && status < 500) { requestKey.current = null; setAttempt(value => value + 1); }
      setFailure(status === 409 ? (error as Error).message || "这个会话还有进行中的运行，请先停止或等它结束再删除。"
        : status === 404 ? "会话不存在或已删除，请刷新会话列表。"
        : status !== undefined && status < 500 ? (error as Error).message || "未能删除，请重试。"
        : "删除结果尚未确认。再点一次会用同一个请求核对，不会重复删除。");
    } finally { setBusy(false); }
  }
  return <section ref={panel} className={styles.panel} role="group" aria-label={`删除会话：${title}`}>
    <h3><Trash size={13} aria-hidden="true"/>删除这个会话？</h3>
    <p className={styles.title} title={title}>{title}</p>
    {!preview && !loadError && <p role="status">正在核对会清除和保留的内容…</p>}
    {loadError && <p role="alert">{loadError}</p>}
    {preview && <>
      <ul>
        <li>{preview.notice.now}</li>
        <li>{preview.notice.by_retention}</li>
        <li>{preview.notice.kept}</li>
      </ul>
      <p className={styles.counts}>{previewSummary(preview)}</p>
      {preview.blocked && <p role="alert">{preview.blocked.message}</p>}
    </>}
    {failure && <p role="alert">{failure}</p>}
    <div className={styles.actions}>
      <Button type="button" size="sm" variant="destructive" disabled={disabled || busy || !preview || !!preview.blocked} onClick={() => void confirm()}>{busy ? "正在删除…" : "删除会话"}</Button>
      <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={onCancel}>取消</Button>
      {loadError && <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => setAttempt(value => value + 1)}>重新核对</Button>}
    </div>
  </section>;
}

function previewSummary(preview: SessionDeletionPreview) {
  const { will_remove: gone, kept } = preview;
  return `这个会话有 ${kept.runs} 次运行。将清除情景记录 ${gone.episodes} 条、未采纳的记忆提议 ${gone.candidates} 条；保留运行记录 ${kept.runs} 次、操作回执 ${kept.receipts} 条${kept.adopted_notes ? `、已采纳的记忆条目 ${kept.adopted_notes} 条` : ""}。`;
}

/** Shown once after a deletion: the same three parts the confirmation showed. */
export function SessionDeletedNotice({ result, onDismiss }: { result: SessionDeleted; onDismiss: () => void }) {
  return <section className={styles.panel} role="status" aria-label="会话已删除">
    <h3>会话已删除</h3>
    <p className={styles.counts}>{deletedSummary(result)}</p>
    <ul>
      <li>{result.notice.by_retention}</li>
      <li>{result.notice.kept}</li>
    </ul>
    <div className={styles.actions}><Button type="button" size="sm" variant="ghost" onClick={onDismiss}>知道了</Button></div>
  </section>;
}
