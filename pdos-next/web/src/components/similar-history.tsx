"use client";

import { useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { ArrowSquareOut, Sparkle } from "@phosphor-icons/react";
import { Button } from "./ui/button";
import { SimilarHistoryPaiContext } from "./similar-history-pai";
import { similarHistoryPath, type SimilarHistoryAction, type SimilarHistoryCard, type SimilarHistoryFeedback, type SimilarHistoryView } from "@/lib/similar-history";
import styles from "./similar-history.module.css";

type Api = <T>(path: string, body?: unknown) => Promise<T>;
const kinds = { issue: "质量问题", capa: "CAPA", change: "变更" };
const statuses: Record<string, string> = { open: "待分诊", triaged: "已分诊", actioning: "措施办理中", awaiting_verification: "待有效性复核", closed: "已关闭", draft: "草稿", analysis: "影响核对中", implementing: "实施中", verifying: "待复验", completed: "已完成登记" };

type SimilarHistoryProps = { api: Api; productId: string; versionId: string; onMerge?: (card: SimilarHistoryCard, element: HTMLElement) => void | Promise<void>; mergeAvailable?: (card: SimilarHistoryCard) => boolean } & ({ issueId: string; changeId?: never } | { changeId: string; issueId?: never });

export function SimilarHistory(props: SimilarHistoryProps) {
  return <SimilarHistoryReading key={`${props.productId}:${props.changeId ? "change" : "issue"}:${props.changeId ?? props.issueId}:${props.versionId}`} {...props}/>;
}
export function SimilarHistoryLayout({ children, history }: { children: ReactNode; history: ReactNode }) {
  if (!history) return <>{children}</>;
  return <div className={styles.layout}><div className={styles.columns}><div className={styles.detail}>{children}</div>{history}</div></div>;
}
function SimilarHistoryReading({ api, productId, issueId, changeId, versionId, onMerge, mergeAvailable }: SimilarHistoryProps) {
  const [reading, setReading] = useState<SimilarHistoryView | null>(null), [error, setError] = useState(""), [attempt, setAttempt] = useState(0);
  const [hidden, setHidden] = useState<string[]>([]), [notice, setNotice] = useState(""), [pending, setPending] = useState<SimilarHistoryFeedback | null>(null), [busy, setBusy] = useState(false);
  const mounted = useRef(true), lock = useRef(false), openPai = useContext(SimilarHistoryPaiContext);
  const change = changeId !== undefined;
  const path = similarHistoryPath(productId, (changeId ?? issueId)!, change ? "change" : "issue");
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    let active = true;
    void api<SimilarHistoryView>(`${path}?version_id=${versionId}`).then(value => { if (active) { setReading(value); setError(""); } }).catch(failure => { if (active) { setReading(null); setError(failure instanceof Error ? failure.message : "相似历史暂不可读。"); } });
    return () => { active = false; };
  }, [api, path, versionId, attempt]);
  async function record(card: SimilarHistoryCard, action: SimilarHistoryAction, original?: SimilarHistoryFeedback) {
    if (change && action === "merge_prepared") return false;
    if (lock.current || (pending && !original)) return false;
    lock.current = true; setBusy(true); setNotice("");
    const body: SimilarHistoryFeedback = original ?? { version_id: versionId, candidate_kind: card.kind, candidate_source_id: card.source_id, candidate_revision: card.source_revision, action, request_key: crypto.randomUUID() };
    setPending(body);
    try {
      await api(`${path}/feedback`, body);
      if (mounted.current) { setPending(null); if (action === "not_relevant") setHidden(old => [...old, `${card.kind}:${card.source_id}`]); }
      return true;
    } catch (failure) {
      if (mounted.current) {
        const status = (failure as { status?: number }).status ?? 0;
        if ([401, 403, 409].includes(status)) {
          setPending(null); setReading(null);
          setError(status === 409 ? "候选已变化，请重新查找后选择。" : "当前访问不可用，已隐藏原相似记录。");
        }
        setNotice(failure instanceof Error ? failure.message : "反馈尚未记录，可重试原请求。");
      }
      return false;
    } finally { lock.current = false; if (mounted.current) setBusy(false); }
  }
  return <aside className={styles.panel} aria-label="相似历史">
    <header><h3>相似历史</h3><Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => { setReading(null); setPending(null); setNotice(""); setError(""); setAttempt(n => n + 1); }}>重新查找</Button></header>
    <p className={styles.note}>仅供查找经验，相似不代表重复、已验证或适用于当前问题。</p>
    {error ? <p role="alert">{error}</p> : !reading ? <p role="status">正在查找本人可读的历史…</p> : <>
      {reading.coverage.status === "partial" && <p role="status" className={styles.note}>部分可读资料尚未完成索引或依据复核；以下只列当前已找到的记录。</p>}
      {!reading.items.length && <p className={styles.note}>当前没有找到可读的相似历史。</p>}
      {!!reading.items.length && reading.items.every(card => hidden.includes(`${card.kind}:${card.source_id}`)) && <p className={styles.note}>已收起本次标记为不相关的记录。</p>}
      <SimilarHistoryCards items={reading.items} hidden={hidden} busy={busy} pending={!!pending} anchorLabel={change ? "当前变更" : "当前问题"}
        mergeAvailable={!change && onMerge ? mergeAvailable : undefined}
        onAction={(card, action, element) => { void record(card, action).then(saved => { if (saved && action === "merge_prepared" && element) void onMerge?.(card, element); }); }}
        onPai={openPai ? card => openPai({ anchor: reading.anchor, candidate: card }) : undefined}/>
      <p className={styles.meta}>查找于 {new Date(reading.as_of).toLocaleString("zh-CN")}</p>
    </>}
    {notice && <p role="alert">{notice}{pending ? " 原反馈请求已保留，可重试。" : ""}</p>}
    {pending && !busy && reading && <Button type="button" size="sm" variant="outline" onClick={event => {
      const card = reading.items.find(row => row.kind === pending.candidate_kind && row.source_id === pending.candidate_source_id);
      const element = event.currentTarget;
      if (card) void record(card, pending.action, pending).then(saved => { if (saved && pending.action === "merge_prepared" && mergeAvailable?.(card)) void onMerge?.(card, element); });
    }}>重试记录原反馈</Button>}
  </aside>;
}

/** Shared presentation of server-projected facts; callbacks exist only for saved objects. */
export function SimilarHistoryCards({ items, hidden = [], busy, pending, anchorLabel, mergeAvailable, onAction, onPai }: {
  items: SimilarHistoryCard[];
  hidden?: string[]; busy?: boolean; pending?: boolean; anchorLabel: string;
  mergeAvailable?: (card: SimilarHistoryCard) => boolean;
  onAction?: (card: SimilarHistoryCard, action: SimilarHistoryAction, element?: HTMLElement) => void;
  onPai?: (card: SimilarHistoryCard) => void;
}) {
  return items.slice(0, 5).filter(card => !hidden.includes(`${card.kind}:${card.source_id}`)).map(card => <article key={`${card.kind}:${card.source_id}`} className={styles.card}>
    <div className={styles.meta}>{kinds[card.kind]} · {statuses[card.status] ?? "状态待核对"}</div><h4>{card.title}</h4>
    <p className={styles.meta}>{card.category} / {card.project} · 固定 v{card.source_revision}{card.is_current ? "" : " · 历史版本"}</p>
    <p className={styles.reason}>{card.reason}</p>
    <dl><div><dt>根因</dt><dd>{card.root_cause}</dd></div><div><dt>临时措施</dt><dd>{card.containment.join("；")}</dd></div><div><dt>{card.kind === "change" ? "变更措施" : "CAPA措施"}</dt><dd>{card.capa_actions.join("；")}</dd></div><div><dt>复验/有效性</dt><dd>{card.verification}</dd></div></dl>
    <details><summary>与{anchorLabel}的结构化差异</summary><dl>{card.differences.map(row => <div key={row.field}><dt>{row.field}</dt><dd>{row.status === "same" ? `相同 · ${row.current}` : row.status === "different" ? `当前：${row.current}；历史：${row.candidate}` : "未记录，不能据此判断相同"}</dd></div>)}</dl><p className={styles.note}>工况等未结构化条件需要另行核对。</p></details>
    <div className={styles.actions}>
      {card.object_url && <a href={card.object_url} target="_blank" rel="noopener noreferrer" onClick={onAction ? () => onAction(card, "opened") : undefined}>{card.object_label}<ArrowSquareOut size={12} aria-hidden="true"/></a>}
      {onAction && <Button type="button" variant="ghost" size="sm" disabled={busy || pending} onClick={() => onAction(card, "not_relevant")}>不相关</Button>}
      {onAction && card.kind === "issue" && card.can_prepare_merge && mergeAvailable?.(card) && <Button type="button" variant="outline" size="sm" disabled={busy || pending} onClick={event => onAction(card, "merge_prepared", event.currentTarget)}>标为重复，核对后确认</Button>}
      {onPai && <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={() => onPai(card)}><Sparkle size={13} aria-hidden="true"/>让小Pai看看</Button>}
    </div>
  </article>);
}
