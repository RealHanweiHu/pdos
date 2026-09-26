"use client";

import { RiskFollowUp } from "./risk-follow-up";
import { useState } from "react";
import Link from "next/link";
import { isRecord, responseBody } from "@/components/workspace-api";
import { Button } from "@/components/ui/button";

type Kind = "task" | "initialization" | "meeting" | "gate" | "handoff";
type Page = {
  groups: { kind: Kind; label: string; count: number | null; readable: boolean; has_references: boolean }[];
  kind: Kind; offset: number; next_offset: number | null; blocks_undo: boolean;
  items: { id: string; target_id: string; title: string; status: string; href: string }[];
};
const statuses: Record<string, string> = { todo: "待开始", in_progress: "进行中", blocked: "受阻", done: "已完成", skipped: "已跳过", pending_approval: "待批准", completed: "已完成", open: "待处理", resolved: "已处理", carried: "已承接", submitted: "交接包已提交" };
function parse(value: unknown): Page {
  if (!isRecord(value) || !Array.isArray(value.groups) || !Array.isArray(value.items) || typeof value.kind !== "string" ||
    typeof value.offset !== "number" || (value.next_offset !== null && typeof value.next_offset !== "number") || typeof value.blocks_undo !== "boolean" ||
    !value.groups.every(g => isRecord(g) && typeof g.kind === "string" && typeof g.label === "string" && (g.count === null || typeof g.count === "number") && typeof g.readable === "boolean" && typeof g.has_references === "boolean") ||
    !value.items.every(i => isRecord(i) && typeof i.id === "string" && typeof i.target_id === "string" && typeof i.title === "string" && typeof i.status === "string" && typeof i.href === "string" && i.href.startsWith("/projects?"))) throw new Error("业务引用数据不完整，请刷新重试");
  return value as Page;
}
export function RiskBusinessReferences({ projectId, riskId }: { projectId: string; riskId: string }) {
  const [page, setPage] = useState<Page | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState("");
  async function load(kind: Kind = "task", offset = 0) {
    setBusy(true); setError("");
    try {
      const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/risks/${encodeURIComponent(riskId)}/references?kind=${kind}&offset=${offset}`, { cache: "no-store", credentials: "same-origin" });
      const data = await responseBody(response);
      if (!response.ok) throw new Error(isRecord(data) && isRecord(data.detail) && typeof data.detail.message === "string" ? data.detail.message : "业务引用暂不可用");
      setPage(parse(data));
    } catch (e) { setError(e instanceof Error ? e.message : "读取失败"); }
    finally { setBusy(false); }
  }
  return <details className="mt-2 rounded-lg border p-3 text-xs" onToggle={event => { if (event.target === event.currentTarget && event.currentTarget.open && !page && !busy) void load(); }}>
    <summary className="cursor-pointer font-medium">查看风险的业务引用</summary>
    <div className="mt-3 space-y-3">
      <p className="text-muted-foreground">这里列出实际行动任务、初始化任务、会议议题、已完成阶段评审和任务交接遗留项。已有引用时保留风险及确认历史，在原记录修改事实、措施或按流程关闭，并核对相关工作。</p>
      {busy ? <p role="status">正在读取当前引用…</p> : null}
      {error ? <p role="alert" className="text-destructive">{error}</p> : null}
      <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void load(page?.kind)}>刷新引用</Button>
      <RiskFollowUp projectId={projectId} riskId={riskId} />
      {page ? <>
        <p>{page.blocks_undo ? "已有业务引用，不能将此风险退回草稿。" : "当前这些业务记录未发现引用；实际撤销时仍会再次核对。"}</p>
        <div className="flex flex-wrap gap-2">{page.groups.map(group => <Button key={group.kind} type="button" size="sm" variant={page.kind === group.kind ? "default" : "outline"} disabled={busy || !group.readable} onClick={() => void load(group.kind)}>{group.label} · {group.readable ? group.count : group.has_references ? "存在引用，需相应权限" : "无可读内容"}</Button>)}</div>
        <ul className="space-y-2">{page.items.map(item => <li key={item.id}><Link className="text-primary underline" href={item.href}>{item.title}</Link> · {statuses[item.status] ?? item.status}</li>)}</ul>
        {!page.items.length ? <p className="text-muted-foreground">本类当前无可展示记录。</p> : null}
        <div className="flex gap-2"><Button type="button" size="sm" variant="outline" disabled={busy || page.offset === 0} onClick={() => void load(page.kind, Math.max(0, page.offset - 50))}>上一页</Button><Button type="button" size="sm" variant="outline" disabled={busy || page.next_offset === null} onClick={() => void load(page.kind, page.next_offset ?? 0)}>下一页</Button></div>
        <p className="text-muted-foreground">每页最多50条；引用正在变化时可回到首页刷新。任务完成或会议结束不删除原引用。</p>
      </> : null}
    </div>
  </details>;
}
