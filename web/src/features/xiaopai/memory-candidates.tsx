"use client";

import { useEffect, useState } from "react";
import { browserApi } from "@/lib/browser-api";
import { isCandidatesView, type Candidate, type CandidatesView } from "@/lib/personal-memory";
import { CandidateCard } from "@/features/settings/personal-memory";
import styles from "./pai-conversation.module.css";

type Api = <T>(path: string, body?: unknown) => Promise<T>;

/** 小Pai 在这次回答里提议记住的条目（P86 第 2 项）。只是提议：点“记住”才以你本人身份写入。 */
export function MemoryCandidates({ api, root, runId, status }: { api: Api; root: string; runId: string; status: string }) {
  const finished = status === "completed" || status === "partial";
  const [value, setValue] = useState<{ runId: string; items: Candidate[]; declined?: string } | null>(null);
  const [notice, setNotice] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!finished) return;
    let live = true;
    void api<CandidatesView>(`${root}/${runId}/memory-candidates`).then(result => {
      const mine = isCandidatesView(result) && result.run_id === runId;
      if (live) setValue({ runId, items: mine ? result.items : [], declined: mine ? result.declined?.note : undefined });
    }).catch(() => { if (live) setValue({ runId, items: [] }); });
    return () => { live = false; };
  }, [api, root, runId, finished, attempt]);
  const pending = value?.runId === runId ? value.items.filter(item => item.status === "pending") : [];
  // 小Pai 的回答写在服务器核对之前：提议被拒收时如实说明没有生成卡片（D531）。
  const declined = value?.runId === runId ? value.declined : undefined;
  if (!finished || (!pending.length && !notice && !declined)) return null;
  return <div className={styles.runDetails} aria-label="记忆提议">
    {pending.map(item => <CandidateCard key={item.candidate_id} api={browserApi} candidate={item} compact onDecided={text => { setNotice(text); setAttempt(n => n + 1); }}/>)}
    {declined && <p role="status" className={styles.lookupNote}>{declined}</p>}
    {notice && <p role="status" className={styles.lookupNote}>{notice} 可在“设置 › 个人偏好 › 我的记忆”里查看和修改。</p>}
  </div>;
}
