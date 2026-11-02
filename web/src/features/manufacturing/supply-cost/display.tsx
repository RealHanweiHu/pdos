import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import type { BasisView, CalculationIssue, ReadState, SourceRef } from "./types";
import { quantity } from "./presentation";

export function Panel({ title, children, note }: { title: string; children: ReactNode; note?: string }) {
  return <section className="panel space-y-4" aria-label={title}><header><h2 className="text-base font-semibold">{title}</h2>{note && <p className="subtle mt-1">{note}</p>}</header>{children}</section>;
}
export function ReadStatus({ status = "ready", error, onRetry }: ReadState) {
  return <>{status === "unconnected" && <p className="subtle" role="status">主线接口待接入，当前没有业务结果。</p>}{status === "loading" && <p className="subtle" role="status">正在读取固定版本…</p>}{error && <div className="space-y-2"><p role="alert" className="text-sm text-destructive break-words">{error}</p>{onRetry && <Button type="button" variant="outline" onClick={() => { void onRetry(); }}>重新读取</Button>}</div>}</>;
}
export function Issues({ issues, title = "缺项与冲突" }: { issues: CalculationIssue[]; title?: string }) {
  if (!issues.length) return null;
  return <details className="rounded-lg border border-border p-3"><summary className="cursor-pointer font-medium text-sm">{title} · {issues.length}</summary><ul className="mt-3 space-y-2">{issues.map((item, index) => <li className="break-words text-sm" key={`${item.code}:${item.path}:${index}`}><p>{item.message}</p><p className="subtle">{item.path} · {item.code}</p></li>)}</ul></details>;
}
export function Source({ source }: { source: SourceRef }) {
  return <span className="break-words text-xs">{source.source_id} · v{source.version} · {source.state === "current" ? "来源当前" : "来源待重核"}</span>;
}
export function Basis({ basis }: { basis: BasisView }) {
  return <dl className="grid gap-x-5 gap-y-2 text-sm sm:grid-cols-2"><div><dt className="subtle">固定 Build</dt><dd className="break-words">{basis.build.build_id} · v{basis.build.ref.version} · {quantity(basis.build.quantity, basis.build.product_unit)}</dd></div><div><dt className="subtle">固定 BOM</dt><dd><Source source={basis.bom.ref}/></dd></div><div className="sm:col-span-2"><dt className="subtle">固定工程配置</dt><dd><Source source={basis.bom.engineering_configuration}/></dd></div></dl>;
}
