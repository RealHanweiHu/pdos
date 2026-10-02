"use client";

import { useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Entry = { id: number; created_at: string; actor_user_id: string; action: string; before_snapshot: Record<string, unknown> | null; after_snapshot: Record<string, unknown>; context: Record<string, unknown> };
const actions: Record<string, string> = { "project.handoff.prepare": "提交交接", "project.handoff.accept": "确认接收", "project.handoff.return": "退回补充" };
export function ProjectHandoffHistory({ projectId, itemKey }: { projectId: string; itemKey: string }) {
  const [items, setItems] = useState<Entry[]>([]), [cursor, setCursor] = useState<number | null>(null);
  const [opened, setOpened] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState("");
  async function load(before?: number) {
    setBusy(true); setError("");
    try {
      const response = await fetch(`/api/projects/${projectId}/completion/handoff/${itemKey}/history${before ? `?before_id=${before}` : ""}`, { cache: "no-store" });
      const body = await responseBody(response);
      if (!response.ok || !isRecord(body) || !Array.isArray(body.items) || !(body.next_before_id === null || typeof body.next_before_id === "number")) throw new Error("交接历史暂不可用，请重试");
      const rows = body.items.map((v: unknown): Entry => {
        if (!isRecord(v) || typeof v.id !== "number" || typeof v.created_at !== "string" || typeof v.actor_user_id !== "string" || typeof v.action !== "string" || !isRecord(v.after_snapshot) || !isRecord(v.context) || !(v.before_snapshot === null || isRecord(v.before_snapshot))) throw new Error("交接历史记录不完整");
        return { id: v.id, created_at: v.created_at, actor_user_id: v.actor_user_id, action: v.action, before_snapshot: v.before_snapshot, after_snapshot: v.after_snapshot, context: v.context };
      });
      setItems(old => before ? [...old, ...rows.filter(row => !old.some(item => item.id === row.id))] : rows); setCursor(body.next_before_id); setOpened(true);
    } catch (e) { setError(e instanceof Error ? e.message : "交接历史读取失败"); }
    finally { setBusy(false); }
  }
  return <section className="space-y-2 text-sm" aria-label="交接办理历史"><Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => opened ? setOpened(false) : void load()}>{opened ? "收起办理历史" : "查看历次交接与接收"}</Button>{error ? <p role="alert" className="text-destructive">{error}</p> : null}{opened && <>
    <p className="text-xs text-muted-foreground">以下为当时办理记录；是否满足结项条件以当前清单为准。</p>
    {!items.length && <p>暂无办理历史。</p>}
    {items.map(item => {
      const details = isRecord(item.context.handoff_details) ? item.context.handoff_details : null;
      const people = details && isRecord(details.people) ? details.people : {};
      const person = (id: unknown) => typeof id === "string" ? (typeof people[id] === "string" ? String(people[id]) : `成员 ${id}（原姓名未保存）`) : "未指定";
      const document = details && isRecord(details.document) ? details.document : null;
      const before = item.before_snapshot, after = item.after_snapshot;
      const manifest = details && isRecord(details.business_sources) ? details.business_sources : null;
      const sources = manifest && Array.isArray(manifest.groups) ? manifest.groups.filter(isRecord) : [];
      return <article key={item.id} className="space-y-1 rounded-md border p-2"><p>{actions[item.action] ?? item.action} · {new Date(item.created_at).toLocaleString("zh-CN")} · {person(item.actor_user_id)}</p><p>接收人：{person(after.receiver_user_id)}</p>
        {before && before.receiver_user_id !== after.receiver_user_id ? <p>原接收人：{person(before.receiver_user_id)}</p> : null}
        {details && typeof details.receiver_change_reason === "string" ? <p className="whitespace-pre-wrap">换人原因：{details.receiver_change_reason}</p> : null}
        <p className="whitespace-pre-wrap">办理说明：{typeof after.note === "string" ? after.note : "原记录未提供"}</p>
        {before && typeof before.note === "string" && before.note !== after.note ? <p className="whitespace-pre-wrap text-muted-foreground">办理前说明：{before.note}</p> : null}
        <p>原文档：{document && typeof document.filename === "string" ? document.filename : String(after.document_id ?? "未保存")}</p>
        {typeof after.document_id === "string" && /^[0-9a-f-]{36}$/.test(after.document_id) ? <Link className="text-primary underline" href={`/projects?project=${projectId}&tab=documents&entity_id=${after.document_id}`}>查看原文档</Link> : null}
        {document && typeof document.sha256 === "string" ? <p className="break-all text-xs text-muted-foreground">原文件摘要：{document.sha256}</p> : null}
        {manifest ? <details className="text-xs"><summary className="cursor-pointer">办理时固定的业务依据 · {sources.length} 类</summary>
          <p className="my-1 text-muted-foreground">以下为办理当时的记录数量与校验摘要，原结论保留；当前变化见交接清单。</p>
          {sources.map((source, index) => <div key={typeof source.key === "string" ? source.key : index} className="space-y-1 border-l pl-2 py-1"><p>{typeof source.label === "string" ? source.label : "业务依据"} · {typeof source.count === "number" ? source.count : "未知"} 条</p><p className="break-all font-mono text-muted-foreground">{typeof source.digest === "string" ? source.digest : "未保存摘要"}</p></div>)}
        </details> : <p className="text-xs text-muted-foreground">此历史记录未保存业务依据明细，不能用当前资料代替当时依据。</p>}
        {!details ? <p className="text-xs text-muted-foreground">旧记录仅保留原办理内容，未保存当时姓名与文件摘要。</p> : null}
      </article>;
    })}
    {cursor !== null && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void load(cursor)}>加载更早记录</Button>}
  </>}</section>;
}
