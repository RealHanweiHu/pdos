import { locationLabel, rawSpec, type Context, type Research } from "./contracts";

const origins = { human_observation: "人工观察", ai_extraction: "AI 抽取", translation: "翻译候选", customer_input: "客户输入" };
export function SourcePackage({ research, context, unavailableReason }: {
  research: Research | null; context: Context; unavailableReason?: string;
}) {
  if (!research) return <section role="status" className="rounded-lg border p-4 text-sm">{unavailableReason ?? "来源权限待重核，暂不展示派生内容。"}</section>;
  const present = new Set(research.items.map(item => item.category));
  const missing = context.requiredCategories.filter(category => !present.has(category));
  return <section className="space-y-4 rounded-lg border p-4" aria-label="研究来源与观察">
    <div><h2 className="font-semibold">{research.title} · 来源包 v{research.revision}</h2>
      <p className="text-sm text-muted-foreground">{research.mode === "oem" ? "OEM 内部导入" : "无项目研究"} · {context.scopeLabel ?? "研究范围待绑定"} · 目标型号：{context.productLabel ?? "尚未绑定，可先研究"}</p></div>
    <p className="text-sm">完整性：{!context.requiredCategories.length ? "适用核对规则尚未绑定" : missing.length ? `仍缺 ${missing.join("、")}` : "本轮要求的资料类别已登记，仍需核对内容与冲突"}</p>
    <ul className="space-y-2 text-sm">{research.items.map((item, index) => <li key={`${item.source.artifact_id}-${index}`} className="rounded-lg border p-3">
      <div className="font-medium">{item.category} · v{item.source.expected_revision} · {locationLabel(item.source)}</div>
      <div className="break-all font-mono text-xs text-muted-foreground">Artifact {item.source.artifact_id}{item.source.original_version ? ` · 原件版本 ${item.source.original_version}` : ""}</div>
      <blockquote className="mt-2 whitespace-pre-wrap break-words border-l-2 pl-3">{item.source.quote}</blockquote>
    </li>)}</ul>
    {!research.observations.length && <p className="text-sm text-muted-foreground">尚无观察；来源包登记不表示规格已接受。</p>}
    {research.observations.map(entry => <article key={entry.observation.id} className="space-y-2 rounded-lg bg-muted/40 p-3 text-sm">
      <div className="flex flex-wrap gap-2"><strong>{entry.observation.key} · {entry.observation.statement}</strong><span>{origins[entry.observation.origin]}</span></div>
      <p>{entry.verification.status === "verified" ? "原字段对应已核对" : "人工候选 / 待原值核对"} · {entry.verification.reason}</p>
      <p>成熟度：{entry.verification.accepted_requirement ? "已接受需求（主线记录重核）" : "候选，尚未成为正式规格"}</p>
      {entry.observation.spec && <div className="space-y-1">
        <p className="font-mono">{rawSpec(entry.observation.spec)} · 允差 {entry.observation.spec.tolerance ?? "未知"}</p>
        <p>测试条件：{entry.observation.spec.test_conditions.join("；") || "未知"} · 方法：{entry.observation.spec.method ?? "未知"}</p>
        <p>适用范围：{entry.observation.spec.applicability ?? "未知"} · 验收准则：{entry.observation.spec.acceptance_criterion ?? "未知"}</p>
      </div>}
      <details><summary className="cursor-pointer py-2">原始观察与精确来源</summary><p className="whitespace-pre-wrap break-words">{entry.observation.raw_text}</p>
        <ul>{entry.observation.sources.map((source, index) => <li key={index}>{locationLabel(source)} · v{source.expected_revision}</li>)}</ul>
      </details>
    </article>)}
  </section>;
}
