"use client";

import { isRecord } from "@/components/workspace-api";

const labels: Record<string, string> = {
  "quality.prepare_capa": "品质待审建议整理",
  "engineering.trace_impact": "引用关系追踪",
  "change.prepare_work_package": "待审建议整理",
};

export function ChangeToolReceipts({ value }: { value: unknown }) {
  if (!isRecord(value)) return null;
  const entries = Object.entries(value).filter(([key, row]) => labels[key] && isRecord(row));
  if (!entries.length) return null;
  return <details className="rounded-md border p-2 text-xs">
    <summary className="cursor-pointer">实际处理步骤</summary>
    <div className="mt-2 space-y-2">{entries.map(([key, raw]) => {
      if (!isRecord(raw)) return null;
      const state = raw.status === "completed" ? "已完成" : raw.status === "partial" ? "已处理，覆盖有限" : "未完成";
      return <div key={key}>
        <p>{labels[key]} · {state}{typeof raw.shown_count === "number" && ` · ${raw.shown_count} ${key === "engineering.trace_impact" ? "条实际关系" : "份待审建议"}`}</p>
        {typeof raw.created_at === "string" && <p className="text-muted-foreground">{new Date(raw.created_at).toLocaleString("zh-CN")}</p>}
        {Array.isArray(raw.missing) && raw.missing.length > 0 && <ul className="list-disc pl-4">{raw.missing.map((item, i) => <li key={i}>{String(item)}</li>)}</ul>}
        {raw.status === "failed" && <p>请核对原资料和候选内容；本次处理回执已保留。</p>}
      </div>;
    })}</div>
  </details>;
}
