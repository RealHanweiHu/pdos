"use client";

import { useMemo, useState } from "react";
import { ArrowsInSimple, ArrowsOutSimple, X } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { browserApi } from "@/lib/browser-api";
import { categoryTransport } from "@/lib/category-transport";
import { Xiaopai } from "@/components/xiaopai";
import { PersonalXiaopai } from "@/components/category-create/personal-xiaopai";
import { ContextPicker, type SelectedPaiContext } from "@/components/pai/context-picker";
import type { MaterialContext } from "./category-material-editor";
import type { CreatedCategory } from "@/components/category-create/contracts";
import styles from "./pai-conversation.module.css";

export type PaiSource = { id: string; title: string; revision: number; status: string };
export type PaiContext = { categoryId: string; productId: string; projectId?: string; projectName?: string; sources: PaiSource[]; material?: MaterialContext };

/** 小Pai 常驻右侧工作栏（v1.1 §6）：品类上下文内为品类小Pai，否则为个人小Pai。 */
export function PaiRail({ open, onClose, categoryId, categoryName, paiContext, focusRun, session, onCreated, expectedProjectId, presetSkillKeys, standalone = false }: {
  standalone?: boolean;
  presetSkillKeys?: string[];
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
  const pageScope = `${session.principal_id}:${categoryId}:${expectedProjectId ?? paiContext?.projectId ?? ""}`;
  const [selection, setSelection] = useState<{ pageScope: string; value: SelectedPaiContext | null | undefined } | null>(null);
  const chosen = selection?.pageScope === pageScope ? selection.value : undefined;
  const selectedCategoryId = chosen === undefined ? categoryId : chosen?.categoryId ?? "";
  const selectedCategoryName = chosen === undefined ? categoryName : chosen?.categoryName ?? "";
  const transport = useMemo(() => selectedCategoryId ? categoryTransport(selectedCategoryId, browserApi) : null, [selectedCategoryId]);
  const inContext = chosen === undefined ? paiContext?.categoryId === categoryId ? paiContext : null : chosen ? { ...chosen, sources: [] } : null;
  const focusRunId = chosen === undefined && focusRun && focusRun.categoryId === categoryId ? focusRun.runId : undefined;
  const scope = `${selectedCategoryId}:${inContext?.projectId ?? ""}:${focusRunId ?? ""}`;
  const composeOpen = compose.scope === scope && compose.open;

  const contextControl = <ContextPicker key={pageScope} compact triggerLabel="修改对象" pageLabel={selectedCategoryId ? inContext?.projectName || selectedCategoryName || "当前品类" : "通用对话"} value={chosen} onChange={value => setSelection({ pageScope, value })}/>;
  const headerActions = <>{!standalone && <Button size="icon" variant="ghost" aria-label={expanded ? "缩回小Pai 工作栏" : "展开小Pai 对话工作区"} aria-pressed={expanded} onClick={() => setExpanded(value => !value)}>{expanded ? <ArrowsInSimple/> : <ArrowsOutSimple/>}</Button>}<Button size="icon" variant="ghost" aria-label="关闭小Pai 工作栏" onClick={onClose}><X/></Button></>;
  return <aside className={`workspace-pai-rail ${styles.rail}${expanded ? ` ${styles.expanded}` : ""}${standalone ? ` ${styles.standalone}` : ""}`} aria-label={expanded ? "小Pai 对话工作区" : "小Pai 工作栏"} hidden={!open}>
    <div className={`workspace-pai-rail-body ${styles.railBody}`}>
      {chosen === undefined && expectedProjectId && inContext?.projectId !== expectedProjectId ? <p role="status" className="subtle">正在核对项目范围，请等待项目资料读取完成。</p> : transport
        ? <Xiaopai fullPage={standalone || expanded} contextControl={contextControl} headerActions={headerActions} key={`rail:${session.principal_id}:${selectedCategoryId}:${inContext?.projectId ?? ""}`} api={transport} categoryId={selectedCategoryId} categoryName={selectedCategoryName} principalId={session.principal_id} productId={inContext?.productId ?? ""} projectId={inContext?.projectId} projectName={inContext?.projectName} sources={inContext?.sources ?? []} materialContext={inContext && "material" in inContext ? inContext.material : undefined} composeOpen={composeOpen} onComposeChange={next => setCompose({ scope, open: next })} initialRunId={focusRunId} onBackground={onClose} />
        : <PersonalXiaopai presetSkillKeys={presetSkillKeys} fullPage={standalone || expanded} contextControl={contextControl} headerActions={headerActions} key={`rail-personal:${session.principal_id}`} principalId={session.principal_id} onCreated={onCreated} initialRunId={chosen === undefined && focusRun && !focusRun.categoryId ? focusRun.runId : undefined} onBackground={onClose} />}
    </div>
  </aside>;
}
