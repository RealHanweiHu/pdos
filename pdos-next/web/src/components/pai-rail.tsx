"use client";

import { useMemo, useState } from "react";
import { Sparkle, X } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { browserApi } from "@/lib/browser-api";
import { categoryTransport } from "@/lib/category-transport";
import { Xiaopai } from "@/components/xiaopai";
import { PersonalXiaopai } from "@/components/category-create/personal-xiaopai";
import type { CreatedCategory } from "@/components/category-create/contracts";

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
  const transport = useMemo(() => categoryId ? categoryTransport(categoryId, browserApi) : null, [categoryId]);
  const inContext = paiContext?.categoryId === categoryId ? paiContext : null;
  const focusRunId = focusRun && focusRun.categoryId === categoryId ? focusRun.runId : undefined;
  const scope = `${categoryId}:${focusRunId ?? ""}`;
  const composeOpen = compose.scope === scope && compose.open;

  return <aside className="workspace-pai-rail" aria-label="小Pai 工作栏" hidden={!open}>
    <div className="workspace-pai-rail-header">
      <Sparkle size={18} className="text-primary" aria-hidden="true"/>
      <div className="min-w-0 flex-1">
        <p className="truncate font-semibold">小Pai</p>
        <p className="subtle truncate">{categoryId ? `当前品类：${categoryName || "已选品类"}` : "个人工作（跨品类）"}</p>
      </div>
      <Button size="icon" variant="ghost" aria-label="关闭小Pai 工作栏" onClick={onClose}><X/></Button>
    </div>
    <div className="workspace-pai-rail-body">
      {expectedProjectId && inContext?.projectId !== expectedProjectId ? <p role="status" className="subtle">正在核对项目范围，请等待项目资料读取完成。</p> : transport
        ? <Xiaopai key={`rail:${session.principal_id}:${categoryId}:${inContext?.projectId ?? ""}`} api={transport} categoryId={categoryId} principalId={session.principal_id} projectId={inContext?.projectId} projectName={inContext?.projectName} productId={inContext?.productId ?? ""} sources={inContext?.sources ?? []} composeOpen={composeOpen} onComposeChange={next => setCompose({ scope, open: next })} initialRunId={focusRunId} />
        : <PersonalXiaopai key={`rail-personal:${session.principal_id}`} onCreated={onCreated} initialRunId={focusRun && !focusRun.categoryId ? focusRun.runId : undefined} />}
    </div>
  </aside>;
}
