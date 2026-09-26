import { obj, rows, text, type Row } from "@/components/quality/fmea-sources";
const states: Record<string, string> = { hold: "暂缓", approved: "通过", rejected: "退回", conditional: "有条件通过", pending: "待办理", preparing: "准备中", reviewing: "评审中", not_applicable: "不适用", cancelled: "已取消", draft: "草稿", erp_handoff: "已转执行" };
const slots: Record<string, string> = { product: "产品", engineering: "工程", quality: "品质" };
const time = (value: unknown) => value ? new Date(text(value)).toLocaleString() : "未记录";
export function CustomerSignatureSummary({ value }: { value: Row }) {
  const summary = obj(value), status = text(summary.status);
  return <section aria-label="客户可见原签核摘要" className="space-y-1 rounded-md bg-muted/30 p-3 text-sm">
    <h6 className="font-medium">{text(summary.type)} · {text(summary.reference)}</h6>
    <p>原状态：{states[status] ?? status}</p>
    {summary.type === "Gate" ? <><p>原轮次：{summary.round == null ? "未记录" : text(summary.round)}</p>{rows(summary.signoffs).length ? rows(summary.signoffs).map((s, index) => <p key={index}>{slots[text(s.specialty)] ?? text(s.specialty)}席：{states[text(s.status)] ?? text(s.status)} · 签核时间：{time(s.signed_at)}</p>) : <p>未记录本轮签核，不推定通过。</p>}</> : <><p>原 ECR 状态：{states[text(summary.ecr_status)] ?? text(summary.ecr_status)}</p><p>ECR 批准时间：{time(summary.ecr_approved_at)}</p><p>ECN 生效裁决时间：{time(summary.effectivity_decided_at)}</p></>}
  </section>;
}
