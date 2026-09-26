"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord } from "@/components/workspace-api";

const buckets = {
  requirements_without_spec: "需求尚无关联规格", key_specs_unverified: "关键规格缺少验证路径",
  failed_verification: "关联测试存在失败", retest_needed: "规格更新后需要复测",
};
export function SpecVerificationCoverage({ projectId }: { projectId: string }) {
  const [data, setData] = useState<Record<string, Record<string, unknown>[]> | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  async function load() {
    setBusy(true); setError(null);
    try {
      const response = await fetch(`/api/projects/${projectId}/product-engineering/spec-coverage`, { cache: "no-store" });
      const value: unknown = await response.json();
      if (!response.ok || !isRecord(value) || Object.keys(buckets).some(key => !Array.isArray(value[key]))) throw new Error("验证缺口暂不可用，请重新读取");
      setData(Object.fromEntries(Object.keys(buckets).map(key => [key, (value[key] as unknown[]).filter(isRecord)])));
    } catch (e) { setError(e instanceof Error ? e.message : "验证缺口暂不可用"); }
    finally { setBusy(false); }
  }
  return <details className="rounded-md border p-3" onToggle={event => { if (event.currentTarget.open && !data && !busy) void load(); }}>
    <summary className="cursor-pointer text-sm font-medium">需求与规格验证缺口</summary>
    <div className="mt-3 space-y-3 text-sm">
      <p className="text-xs text-muted-foreground">按当前项目已登记的需求、规格和关联测试计算；四类缺口可能重叠，空列表不代表整个产品验证通过。</p>
      {data && <div className="grid gap-3 sm:grid-cols-2">{Object.entries(buckets).map(([key, label]) => <section key={key} className="rounded-md border p-3"><h4 className="font-medium">{label} · {data[key].length}</h4><ul className="mt-2 space-y-1 text-xs">{data[key].map(item => <li key={String(item.id)}>{key === "requirements_without_spec" ? <span>{String(item.code)} · {String(item.title)}</span> : <a className="text-primary underline" href={`/projects?project=${projectId}&tab=engineering#spec-${String(item.id)}`}>{String(item.code)} · {String(item.title)}</a>}</li>)}</ul>{!data[key].length && <p className="mt-1 text-xs text-muted-foreground">当前登记资料未发现此类缺口。</p>}</section>)}</div>}
      {error && <p role="alert" className="text-destructive">{error}</p>}
      <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void load()}>刷新验证缺口</Button>
    </div>
  </details>;
}
