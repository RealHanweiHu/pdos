import type { ProposalViewSource } from "./proposal-view-contracts";

const fieldNames: Record<string, string> = {
  type: "来源类型", kind: "来源类型", id: "来源编号", version: "引用版本",
  current_version: "当前版本", locator: "原文定位", quote: "引用片段",
  status: "来源状态", availability: "可用性", title: "标题", url: "原始地址",
  content_hash: "内容摘要", snapshot_id: "快照编号", claim_id: "事实编号",
  line: "原文行号", statement: "具名陈述",
};
const sourceTypes: Record<string, string> = {
  artifact: "原文材料", original: "原件", snapshot: "网页快照", knowledge: "品类知识",
  claim: "事实陈述", human: "具名人员", definition: "产品定义", parameter: "参数字典",
};

/** Render only the server's permitted reference. Never fetch or navigate a source URL. */
export function ProposalSourceInspector({ sources, label = "查看来源", id }: {
  sources: readonly ProposalViewSource[]; label?: string; id?: string;
}) {
  if (!sources.length) return <p id={id} className="text-xs text-muted-foreground">服务器未提供可读来源。</p>;
  return <details id={id} className="rounded-lg border p-3 text-sm">
    <summary className="cursor-pointer rounded-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring">{label}（{sources.length}）</summary>
    <ol className="mt-3 space-y-4">
      {sources.map((source, index) => <li key={index} className="space-y-2">
        <p className="text-xs text-muted-foreground">来源 {index + 1}</p>
        <dl className="grid gap-x-3 gap-y-1 sm:grid-cols-[7rem_minmax(0,1fr)]">
          {Object.entries(source).filter(([field, value]) => field !== "statement" || (value !== null && value !== undefined && value !== "")).map(([field, value]) => <div key={field} className="contents">
            <dt className="text-muted-foreground">{fieldNames[field] ?? field}</dt>
            <dd className="min-w-0 whitespace-pre-wrap break-words [overflow-wrap:anywhere]">{(field === "type" || field === "kind") && typeof value === "string" ? sourceTypes[value] ?? value : value === null || value === undefined ? "未提供" : typeof value === "object" ? JSON.stringify(value, null, 2) : String(value)}</dd>
          </div>)}
        </dl>
      </li>)}
    </ol>
  </details>;
}
