"use client";

import { useMemo, useState } from "react";
import { ArrowsInSimple, ArrowsOutSimple, Sparkle, X } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { browserApi } from "@/lib/browser-api";
import { categoryTransport } from "@/lib/category-transport";
import { Xiaopai } from "@/components/xiaopai";
import { PersonalXiaopai } from "@/components/category-create/personal-xiaopai";
import type { CreatedCategory } from "@/components/category-create/contracts";
import styles from "./pai-conversation.module.css";

export type PaiSource = { id: string; title: string; revision: number; status: string };
export type PaiContext = { categoryId: string; productId: string; projectId?: string; projectName?: string; sources: PaiSource[] };

/** 小Pai 常驻右侧工作栏（v1.1 §6）：品类上下文内为品类小Pai，否则为个人小Pai。 */
export function PaiRail({ open, onClose, categoryId, categoryName, paiContext, focusRun, session, onCreated, expectedProjectId }: {
  open: boolean; onClose: () => void;
  categoryId: string; categoryName: string;
  paiContext: PaiContext | null;
  expectedProjectId?: string;
  focusRun: { runId: string; categoryId: string } | null;
  session: { name: string; principal_id: string };
  onCreated: (category: CreatedCategory) => void;
}) {
  const [compose, setCompose] = useState<{ scope: string; open: boolean }>({ scope: "", open: false });
  const [expanded, setExpanded] = useState(false);
  const transport = useMemo(() => categoryId ? categoryTransport(categoryId, browserApi) : null, [categoryId]);
  const inContext = paiContext?.categoryId === categoryId ? paiContext : null;
  const focusRunId = focusRun && focusRun.categoryId === categoryId ? focusRun.runId : undefined;
  const scope = `${categoryId}:${focusRunId ?? ""}`;
  const composeOpen = compose.scope === scope && compose.open;

  return <aside className={`workspace-pai-rail ${styles.rail}${expanded ? ` ${styles.expanded}` : ""}`} aria-label={expanded ? "小Pai 对话工作区" : "小Pai 工作栏"} hidden={!open}>
    <div className={`workspace-pai-rail-header ${styles.railHeader}`}>
      <Sparkle size={18} className="text-primary" aria-hidden="true"/>
      <div className={styles.railTitle}><strong>小Pai</strong><span aria-hidden="true">/</span><p>{categoryId ? categoryName || "当前品类" : "个人工作"}</p></div>
      <Button size="icon" variant="ghost" aria-label={expanded ? "缩回小Pai 工作栏" : "展开小Pai 对话工作区"} aria-pressed={expanded} onClick={() => setExpanded(value => !value)}>{expanded ? <ArrowsInSimple /> : <ArrowsOutSimple />}</Button>
      <Button size="icon" variant="ghost" aria-label="关闭小Pai 工作栏" onClick={onClose}><X/></Button>
    </div>
    <div className={`workspace-pai-rail-body ${styles.railBody}`}>
      {expectedProjectId && inContext?.projectId !== expectedProjectId ? <p role="status" className="subtle">正在核对项目范围，请等待项目资料读取完成。</p> : transport
        ? <Xiaopai key={`rail:${session.principal_id}:${categoryId}:${inContext?.projectId ?? ""}`} api={transport} categoryId={categoryId} categoryName={categoryName} principalId={session.principal_id} productId={inContext?.productId ?? ""} projectId={inContext?.projectId} projectName={inContext?.projectName} sources={inContext?.sources ?? []} composeOpen={composeOpen} onComposeChange={next => setCompose({ scope, open: next })} initialRunId={focusRunId} onBackground={onClose} />
        : <PersonalXiaopai key={`rail-personal:${session.principal_id}`} principalId={session.principal_id} onCreated={onCreated} initialRunId={focusRun && !focusRun.categoryId ? focusRun.runId : undefined} onBackground={onClose} />}
    </div>
  </aside>;
}
