"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowClockwise } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import type { ProposalViewDocument } from "./proposal-view-contracts";
import { ProposalSourceInspector } from "./proposal-source-inspector";
import { isProposalVoicesResponse, proposalVoiceQuotes, proposalVoicesPath, readProposalVoices, type ProposalVoiceEntry, type ProposalVoicesReader, type ProposalVoicesResponse } from "@/lib/proposal-voices";
import styles from "./proposal-voices.module.css";

type Props = { categoryId: string; proposalId: string; document: ProposalViewDocument; readVersion: number; reader?: ProposalVoicesReader };
const originLabels: Record<string, string> = { human: "人工记录", ai_draft: "AI 草稿", imported: "导入记录" };
const kindLabels: Record<string, string> = { section: "叙述", spec: "规格", option: "方案", question: "待决问题", risk: "风险", assumption: "假设", difference: "派生差异", commercial_target: "商业目标", decision_note: "取舍记录" };
const reasonLabels: Record<string, string> = {
  knowledge_unavailable: "固定声音记录不可读", knowledge_version_mismatch: "引用版本与声音记录不一致", knowledge_withdrawn: "声音记录已撤回",
  knowledge_current_unavailable: "声音当前状态不可读", source_unavailable: "底层来源不可读", evidence_link_inactive: "证据关联当前无效",
  evidence_link_target_mismatch: "证据关联与本案条目不一致", knowledge_reference_invalid: "声音引用身份不完整",
};

function Voice({ entry }: { entry: ProposalVoiceEntry }) {
  const quotes = proposalVoiceQuotes(entry);
  const changed = entry.current_version !== null && entry.current_version !== entry.version;
  return <article className={styles.voice}>
    <div className={styles.labelRow}><span>声音标签 / 摘要</span><h3>{entry.label}</h3></div>
    {quotes.map((source, index) => <blockquote key={index} className={styles.quote}><p>{source.quote}</p><cite>引用原文 · {String(source.type)} · v{String(source.version)}{typeof source.line === "number" && ` · 第 ${source.line} 行`}</cite></blockquote>)}
    {!quotes.length && <p className={styles.noQuote}>未提供可读原文片段。</p>}
    <div className={styles.meta}><span>{entry.source_platform || "来源平台未登记"}</span><span>{originLabels[entry.origin] ?? entry.origin}</span><span>固定 v{entry.version}</span><span>{entry.sample_size === null ? "登记样本数未知" : `登记样本 ${entry.sample_size}`}</span></div>
    {changed && <p className={styles.changed}>当前已更新至 v{entry.current_version}，本案继续引用固定 v{entry.version}。</p>}
    {entry.current_version === null && <p className={styles.changed}>当前版本未知，本案按已返回的固定引用展示。</p>}
    {entry.source_changes.length > 0 && <details className={styles.changeDetails}><summary>相关来源已有变化 · {entry.source_changes.length} 项</summary><pre>{JSON.stringify(entry.source_changes, null, 2)}</pre></details>}
    <div className={styles.associations}>
      {entry.used_in_context && <p>已作为本案上下文引用</p>}
      {entry.related_items.length > 0 && <><h4>明确关联条目</h4><ul>{entry.related_items.map(item => <li key={`${item.item_id}:${item.version}`}><span>{kindLabels[item.kind] ?? item.kind} · {item.label}</span><span>v{item.version}</span></li>)}</ul></>}
      {!entry.used_in_context && entry.related_items.length === 0 && <p>本案资料引用，未关联具体条目。</p>}
    </div>
    <details className={styles.sources}><summary>固定声音与来源详情</summary><dl className={styles.identity}><div><dt>声音编号</dt><dd>{entry.knowledge_id}</dd></div><div><dt>沿袭编号</dt><dd>{entry.lineage_id}</dd></div><div><dt>记录状态</dt><dd>{entry.status === "active" ? "当前可读" : entry.status}</dd></div></dl>{entry.related_items.length > 0 && <dl className={styles.identity}>{entry.related_items.map(item => <div key={`${item.item_id}:${item.version}`}><dt>关联条目 v{item.version}</dt><dd>{item.label}<code>{item.item_id}</code></dd></div>)}</dl>}<ProposalSourceInspector sources={entry.representative_refs} label="代表性来源"/><ProposalSourceInspector sources={entry.source_refs} label="来源引用"/></details>
  </article>;
}

export function ProposalVoices(props: Props) {
  const identity = props.document;
  const key = JSON.stringify([props.categoryId, props.proposalId, identity.proposal_id, identity.revision, identity.document_digest, identity.submission_id, identity.document_mode, props.readVersion]);
  return <ScopedProposalVoices key={key} {...props}/>;
}

function ScopedProposalVoices({ categoryId, proposalId, document, reader = readProposalVoices }: Props) {
  const [data, setData] = useState<ProposalVoicesResponse | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const generation = useRef(0);
  const { proposal_id, revision, document_digest, submission_id, document_mode } = document;
  useEffect(() => {
    const controller = new AbortController(), own = ++generation.current;
    void (async () => {
      if (proposal_id !== proposalId) throw new Error("当前提案身份不一致，请刷新文档后重新读取声音。");
      const value = await reader(proposalVoicesPath(categoryId, proposalId), controller.signal);
      if (controller.signal.aborted || generation.current !== own) return;
      if (!isProposalVoicesResponse(value, categoryId, { proposal_id, revision, document_digest, submission_id, document_mode })) throw new Error("声音结果与当前提案文档不一致，或资料不完整，请刷新后重试。");
      setData(value); setError("");
    })().catch(failure => { if (!controller.signal.aborted && generation.current === own) { setData(null); setError((failure as Error).message); } });
    return () => controller.abort();
  }, [categoryId, proposalId, reader, proposal_id, revision, document_digest, submission_id, document_mode, attempt]);
  function refresh() { generation.current++; setData(null); setError(""); setAttempt(value => value + 1); }

  return <section className={styles.panel} aria-label="本案用户声音">
    <header className={styles.header}><h2>与本案直接相关的声音</h2><span>{data ? `${data.counts.entries} 条可读${data.counts.unavailable_entries ? ` · ${data.counts.unavailable_entries} 条引用无法核对` : ""}` : "固定声音引用与关联条目"}</span><Button type="button" size="xs" variant="ghost" onClick={refresh} aria-label="刷新本案声音"><ArrowClockwise size={12} aria-hidden="true"/></Button></header>
    {error ? <div className={styles.notice} role="alert"><p>{error}</p><Button type="button" size="xs" variant="outline" onClick={refresh}>重新读取本案声音</Button></div> : !data ? <p className={styles.notice} role="status">正在读取当前提案明确引用的声音…</p> : <>
      <p className={styles.document}>提案第 {data.document.revision} 版 · {["frozen", "submission"].includes(data.document.document_mode) ? "提交固定副本" : "当前文档"}</p>
      {data.entries.map(entry => <Voice key={`${entry.knowledge_id}:${entry.version}`} entry={entry}/>)}
      {data.entries.length === 0 && <p className={styles.notice}>{data.unavailable.length > 0 ? "未取得可读的声音记录；部分知识引用当前无法核对。" : "本案没有明确的声音引用。"}</p>}
      {data.unavailable.length > 0 && <section className={styles.unavailable} aria-label="无法核对的知识引用"><h3>无法核对的知识引用</h3>{data.unavailable.map((item, index) => <article key={`${item.reference.id}:${item.reference.version}:${index}`}><p><span>知识引用</span><code>{item.reference.id ?? "编号未提供"}</code><span>{item.reference.version === undefined ? "版本未提供" : `v${item.reference.version}`}</span></p><ul>{item.reasons.map(reason => <li key={reason}>{reasonLabels[reason] ?? reason}</li>)}</ul></article>)}</section>}
      <p className={styles.asOf}>资料读取于 <time dateTime={data.as_of}>{new Date(data.as_of).toLocaleString()}</time></p>
    </>}
  </section>;
}
