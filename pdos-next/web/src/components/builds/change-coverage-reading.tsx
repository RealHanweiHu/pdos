"use client";

import { GitBranch, WarningCircle } from "@phosphor-icons/react";
import { readChangeCoverage, type CoverageReadingInput } from "../../lib/change-coverage-reading";

export function ChangeCoverageReading(props: CoverageReadingInput) {
  const reading = readChangeCoverage(props), snapshot = reading.snapshot;
  const count = (value: number | null) => value === null ? "待核对" : String(value);
  return <section aria-label="固定图八项覆盖阅读" className="min-w-0 space-y-3 rounded-lg border border-border p-4">
    <header>
      <h3 className="flex items-center gap-2 text-sm font-medium"><GitBranch aria-hidden className="shrink-0" />固定图覆盖</h3>
      <p className="mt-1 break-words text-sm opacity-70">{count(reading.nodeCount)} 个固定对象 · {count(reading.edgeCount)} 条已列依赖 · {snapshot.current && !snapshot.expired ? "服务器标记当前" : "历史或待重核"}{snapshot.synthetic ? " · 合成演练" : ""}</p>
      <p className="mt-1 text-xs opacity-70">列明数量只说明固定图范围；批准、放行与真实资格由各自办理记录确定。</p>
    </header>
    {reading.needsReview && <div role="status" className="rounded-lg border border-amber-600/40 p-3 text-sm text-amber-800 dark:text-amber-300"><p className="flex items-center gap-2 font-medium"><WarningCircle aria-hidden className="shrink-0" />待核对</p><ul className="mt-1 list-inside list-disc space-y-1">{reading.issues.map(issue => <li key={issue}>{issue}</li>)}</ul></div>}
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">服务器固定图中每个对象的八项范围声明及对应影响 UNKNOWN 数量</caption>
        <thead className="border-b border-border text-xs opacity-70"><tr><th scope="col" className="py-2 pr-3 font-medium">影响范围</th><th scope="col" className="px-2 py-2 font-medium">已列明</th><th scope="col" className="px-2 py-2 font-medium">有据不适用</th><th scope="col" className="px-2 py-2 font-medium">UNKNOWN</th><th scope="col" className="px-2 py-2 font-medium">待核对</th><th scope="col" className="py-2 pl-2 font-medium">影响缺项</th></tr></thead>
        <tbody>{reading.facets.map(facet => <tr key={facet.facet} className="border-b border-border last:border-0"><th scope="row" className="py-2 pr-3 font-normal">{facet.label}</th><td className="px-2 py-2 tabular-nums">{count(facet.listed)}</td><td className="px-2 py-2 tabular-nums">{count(facet.notApplicable)}</td><td className="px-2 py-2 tabular-nums">{count(facet.unknown)}</td><td className="px-2 py-2 tabular-nums">{count(facet.needsReview)}</td><td className="py-2 pl-2 tabular-nums">{facet.impactUnknown === null ? "未核对" : facet.impactUnknown}</td></tr>)}</tbody>
      </table>
    </div>
    <p className="text-xs opacity-70">影响缺项保留服务器核对中的缺边等 UNKNOWN；覆盖已列明不会消除这些缺项。</p>
    {reading.applicability.length > 0 && <details><summary className="cursor-pointer text-sm">范围与后续路径适用依据（{reading.applicability.length}）</summary><ul className="mt-2 space-y-3 text-sm">{reading.applicability.map((value, index) => <li key={index} className="break-words"><p>{value.objectLabel} → {value.targets.join(" / ")} · {value.status === "not_applicable" ? "有据不适用" : value.status === "applicable" ? "适用" : "UNKNOWN"}</p><p>{value.reason}</p><p className="mt-1 break-all text-xs opacity-70">固定原文：{value.source}</p></li>)}</ul></details>}
    {reading.impact.status === "not_assessed" ? <p className="text-sm opacity-70">UNKNOWN · 所选固定图尚无对应影响核对。</p> : reading.impact.status === "needs_review" ? <p className="text-sm opacity-70">UNKNOWN · 对应影响核对待核对，不能补为零缺项。</p> : reading.impact.unknowns.length ? <details><summary className="cursor-pointer text-sm">对应影响 UNKNOWN（{reading.impact.unknowns.length}）</summary><ul className="mt-2 space-y-2 text-sm">{reading.impact.unknowns.map((unknown, index) => <li key={index} className="break-words"><span className="font-medium">{unknown.label}</span>{unknown.objectLabel ? ` · ${unknown.objectLabel}` : " · 固定图范围"}：{unknown.reason}</li>)}</ul></details> : <p className="text-sm opacity-70">对应影响核对未列缺项；结论仅限此固定图及来源范围。</p>}
    <details><summary className="cursor-pointer text-xs opacity-70">固定图身份与期限</summary><dl className="mt-2 space-y-2 text-xs"><div><dt className="opacity-70">固定图</dt><dd className="break-all font-mono">{snapshot.id ?? "待核对"} · v{snapshot.revision ?? "待核对"}</dd></div><div><dt className="opacity-70">核对时点</dt><dd className="break-words">{snapshot.capturedAt ?? "待核对"}</dd></div><div><dt className="opacity-70">固定快照有效至</dt><dd className="break-words">{snapshot.expiresAt ?? "待核对"}{snapshot.expired ? " · 已到期或期限待核对" : ""}</dd></div><div><dt className="opacity-70">服务器固定摘要</dt><dd className="break-all font-mono">{snapshot.hash ?? "服务器摘要未在读取中提供"}</dd></div></dl></details>
  </section>;
}
