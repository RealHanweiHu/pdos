"use client";

import { EmailExtractionNotice } from "@/components/ai/email-extraction-notice";
import { useState } from "react";
import { IssueSourceCorrection } from "./issue-source-correction";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

export function IssueIntakeSource({ projectId, issueId }: { projectId: string; issueId: string }) {
  const [items, setItems] = useState<Record<string, unknown>[] | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  async function load() {
    setBusy(true); setError(null);
    try {
      const response = await fetch(`/api/projects/${projectId}/issues/${issueId}/intake-sources`, { cache: "no-store" });
      const value: unknown = await responseBody(response).catch(() => null);
      if (!response.ok || !isRecord(value) || !Array.isArray(value.items) || !value.items.every(isRecord)) throw new Error("导入来源暂不可用，请稍后重试");
      setItems(value.items);
    } catch (e) { setError(e instanceof Error ? e.message : "读取未完成"); } finally { setBusy(false); }
  }
  return <details className="rounded-md border p-3" onToggle={e => { if (e.currentTarget.open && items === null && !busy) void load(); }}>
    <summary className="cursor-pointer text-xs font-medium">问题清单导入来源</summary>
    <div className="mt-3 space-y-3"><Button size="sm" variant="outline" disabled={busy} onClick={() => void load()}>刷新来源</Button>
      {items?.length === 0 && <p className="text-xs text-muted-foreground">此问题没有问题清单导入记录。</p>}
      {items?.map(item => {
        const source = isRecord(item.source_snapshot) ? item.source_snapshot : {}, row = isRecord(source.row) ? source.row : {}, original = isRecord(row.original) ? row.original : {}, created = isRecord(item.created_snapshot) ? item.created_snapshot : {};
        return <article key={String(item.id)} className="space-y-2 text-xs">
          <p className={item.on_this_issue === false ? "font-medium text-destructive" : "font-medium"}>{item.on_this_issue === false ? item.state === "withdrawn" ? "此来源关联已撤回，保留历史" : "此来源已改关联其他问题，保留历史" : "当前有效来源关联"} · 处理版本 {String(item.revision ?? 0)}</p>
          {item.on_this_issue === false && typeof item.current_issue_href === "string" && item.current_issue_href.startsWith("/projects?") && <a className="text-primary underline" href={item.current_issue_href}>查看当前关联问题</a>}
          <p className="font-medium">{String(source.filename ?? "原问题清单")} · {String(item.locator)}</p>
          <p>由 {String(item.confirmed_by)} 于 {new Date(String(item.created_at)).toLocaleString("zh-CN")} {item.link_kind === "linked" ? "确认关联已有问题" : "确认录入"}</p>
          <p>许可依据：{String(source.permission_basis ?? "未记录")}<br/>使用目的：{String(source.purpose ?? "未记录")}</p>
          <p>历史编号：{String(row.external_ref ?? "未提供")} · 历史状态：{String(row.historical_state ?? "未提供")}（不代表当前状态）</p>
          {item.link_kind === "linked" && <p>关联依据：{String(item.reuse_reason ?? "未记录")}</p>}
          <p>{item.link_kind === "linked" ? "关联时标题" : "登记时标题"}：{String(created.title ?? "未记录")} · {item.link_kind === "linked" ? `关联时原状态：${String(created.status)}` : "初始状态：开放"}</p>
          <p className="break-all">文件摘要：{String(item.source_sha256)}</p>
          {typeof item.document_href === "string" && item.document_href.startsWith("/projects?") && <a className="text-primary underline" href={item.document_href}>打开项目原件</a>}
          {isRecord(source.additional_documents) && Object.entries(source.additional_documents).map(([key, doc]) => isRecord(doc) && <p key={key}><a className="text-primary underline" href={String(doc.href)}>引用原件：{String(doc.filename)}</a> · {String(doc.sha256)}</p>)}
          <EmailExtractionNotice metadata={source.extraction_metadata}/>
          <details><summary className="cursor-pointer">逐字段原值及原文位置</summary><dl className="mt-2 space-y-2">{Object.entries(original).map(([key, value]) => { if (!isRecord(value)) return null; return <div key={key}><dt className="font-medium">{String(value.cell)}</dt><dd className="whitespace-pre-wrap break-words">{String(value.value ?? "") || "空"}</dd></div>; })}</dl></details>
          <IssueSourceCorrection projectId={projectId} sourceId={String(item.id)} onChanged={load}/>
          <p className="text-muted-foreground">此处保留录入时的来源与原值。问题后续修改、验证和关闭均以当前办理记录为准；来源行不会因后续修改而重写。</p>
        </article>;
      })}
      {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
    </div>
  </details>;
}
