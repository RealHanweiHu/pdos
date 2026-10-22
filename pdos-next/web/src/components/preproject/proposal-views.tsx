"use client";

import { useId } from "react";
import { Button } from "@/components/ui/button";
import { numericValueText } from "@/lib/spec-bound-values";
import { ProposalSourceInspector } from "./proposal-source-inspector";
import { isProposalViewResponse, matchesProposalDocument, proposalViewNames } from "./proposal-view-contracts";
import type { ProposalViewDocument, ProposalViewName, ProposalViewResponse, ViewComparisonGroup, ViewMaturity, ViewObservation, ViewPositioningGroup, ViewSubject, ViewSubjectRef, ViewUnknown } from "./proposal-view-contracts";
import styles from "./proposal-document.module.css";

const labels: Record<string, string> = {
  measured: "实测", observed: "实测", claimed: "宣传", vendor_claimed: "宣传", inferred: "推断", unknown: "未知",
  known: "已知", conflicted: "冲突", not_applicable: "不适用", confirmed: "人工确认", ai_draft: "AI 草稿", expert_pending: "待专家确认",
  target: "目标", decided: "具名决定", computed: "计算结果",
  open: "待答复", answered: "已答复", carried: "已转入项目", retail: "零售价", wholesale: "批发价",
  item_status_unknown: "规格状态未知", item_status_expert_pending: "待专家确认",
  availability_unknown: "信息未知", availability_conflicted: "信息存在冲突",
  unit_missing: "缺少单位", condition_missing: "缺少工况", price_missing: "缺少价格",
  source_unavailable: "来源不可用", source_missing: "缺少来源", parameter_version_unavailable: "参数版本不可用",
  price_amount_unknown: "价格金额未知", price_currency_unknown: "币种未知", price_basis_unknown: "价格口径未知", price_date_unknown: "价格日期未知",
  numeric_point_unavailable: "没有可绘制的数值", plot_value_unrepresentable: "原值超出绘图精度或范围，仅保留原始文本。", plot_range_unrepresentable: "数值跨度超出绘图范围，仅保留原始文本。", plot_evidence_unknown: "性质未知，不绘制坐标。", unmapped_parameter: "尚未映射到字典参数", value_type_mismatch: "值类型不一致", enum_value_unmapped: "枚举值尚未映射",
  unmapped_feature_text: "功能叙述尚未映射到字典参数", price_source_unavailable: "价格来源不可用", feature_source_unavailable: "功能叙述来源不可用",
};
const text = (value: unknown): string => value === null || value === undefined ? "未提供" : typeof value === "object" ? JSON.stringify(value) : String(value);
const testConditions = (value: unknown): string => value === null || value === undefined || (Array.isArray(value) && value.length === 0)
  ? "未提供测试条件" : `测试条件：${Array.isArray(value) ? value.map(text).join("；") : text(value)}`;
const subjectLabel = (subject: ViewSubjectRef, subjects: ViewSubject[]) => subjects.find(row => row.id === subject.id && row.type === subject.type)?.label ?? `${subject.type} · ${subject.id}`;

function Reasons({ reasons }: { reasons: string[] }) {
  return reasons.length > 0 ? <ul className="list-inside list-disc text-sm text-muted-foreground">{reasons.map((reason, index) => <li key={index}>{labels[reason] ?? reason}</li>)}</ul> : null;
}

function Observation({ observation }: { observation: ViewObservation }) {
  const value = observation.availability === "unknown" ? "未知"
    : observation.availability === "not_applicable" ? "不适用"
    : typeof observation.value === "boolean" ? observation.value ? "有" : "无"
    : observation.value ?? observation.text_value ?? numericValueText(null, observation.lower, observation.upper);
  return <div className="space-y-2">
    <p className="font-medium">{String(value)}</p>
    <p className="text-xs text-muted-foreground">{observation.evidence_label ?? labels[observation.evidence_kind] ?? observation.nature ?? observation.evidence_kind} · {labels[observation.availability] ?? observation.availability}</p>
    {!observation.comparable && <p className="text-sm">不可比</p>}
    <Reasons reasons={observation.reasons} />
    <ProposalSourceInspector sources={observation.source_refs} />
  </div>;
}

function Unmapped({ observations, subjects = [] }: { observations: ViewObservation[]; subjects?: ViewSubject[] }) {
  if (!observations.length) return null;
  return <section className="space-y-3 rounded-lg border p-4"><h3 className="font-semibold">未映射条目</h3><p className="text-sm text-muted-foreground">以下条目保留原始名称，尚未对应规格字典。</p>
    {observations.map((observation, index) => <div key={`${observation.observation_id}:${index}`} className="space-y-2 border-t pt-3">
      <h4 className="text-sm font-medium">{observation.parameter ?? observation.key ?? observation.observation_id} · {subjectLabel(observation.subject, subjects)}</h4>
      <Observation observation={observation} />
    </div>)}
  </section>;
}

function Unknowns({ unknowns, subjects = [] }: { unknowns: ViewUnknown[]; subjects?: ViewSubject[] }) {
  if (!unknowns.length) return null;
  return <section className="space-y-2 rounded-lg border p-4"><h3 className="font-semibold">未知或不可用</h3>{unknowns.map((row, index) => <div key={index}><p className="text-sm">{row.label ?? subjectLabel(row.subject, subjects)}</p>{row.observation_id && <p className="break-all text-xs text-muted-foreground">观察编号：{row.observation_id}{row.price_index !== undefined ? ` · 价格记录索引：${row.price_index}` : ""}</p>}<Reasons reasons={row.reasons} />{row.source_refs !== undefined && <ProposalSourceInspector sources={row.source_refs} />}</div>)}</section>;
}

function UnmappedFeatures({ subjects }: { subjects: ViewSubject[] }) {
  return <>{subjects.filter(subject => subject.unmapped_features?.length).map(subject => <section key={`${subject.type}:${subject.id}`} className="space-y-3 rounded-lg border p-4"><h3 className="font-semibold">{subject.label} · 未映射功能叙述</h3>{subject.unmapped_features!.map(feature => <div key={feature.item_id} className="space-y-2"><p className="whitespace-pre-wrap text-sm">{feature.text === null || feature.availability === "unknown" ? "来源不可用，暂不展示功能叙述。" : feature.text}</p><Reasons reasons={feature.reasons} /><ProposalSourceInspector sources={feature.source_refs} /></div>)}</section>)}</>;
}

function ComparisonTable({ groups, subjects, features }: { groups: ViewComparisonGroup[]; subjects: ViewSubject[]; features: boolean }) {
  if (!groups.length) return <p className="text-sm text-muted-foreground">当前提案暂无可展示的{features ? "功能配置" : "规格对标"}分组。请核对条目是否已映射规格字典，并补充参数版本、单位和工况；缺失值仍保留为未知。</p>;
  return <div className="overflow-x-auto rounded-lg border"><table className="w-full min-w-[36rem] text-left text-sm">
    <caption className="p-3 text-left text-muted-foreground">{features ? "明确映射到字典的功能；未提供的值显示未知。" : "按参数版本、单位和工况分别展示，不合并不同口径。"}</caption>
    <thead><tr className="border-b bg-muted/40"><th scope="col" className="p-3">参数与口径</th>{subjects.map(subject => <th key={`${subject.type}:${subject.id}`} scope="col" className={`p-3 ${subject.type === "competitor" ? "text-muted-foreground" : "text-primary"}`}>{subject.label}</th>)}</tr></thead>
    <tbody>{groups.map((group, index) => <tr key={index} className="border-b last:border-b-0">
      <th scope="row" className="min-w-48 space-y-2 p-3 align-top font-normal"><p className="font-semibold">{group.parameter.name} · v{group.parameter_version}</p><p className="text-xs text-muted-foreground">{group.unit ?? "单位未提供"} · {group.condition_note ?? "工况未提供"}</p><p className="text-xs text-muted-foreground">{testConditions(group.test_conditions)}</p><p className="text-xs">样本 {group.sample_count} · 可比 {group.comparable_count} · 未知 {group.unknown_count}</p><Reasons reasons={group.separation_reasons} /></th>
      {subjects.map(subject => {
        const observations = group.observations.filter(row => row.subject.id === subject.id && row.subject.type === subject.type);
        return <td key={`${subject.type}:${subject.id}`} className="min-w-52 space-y-4 p-3 align-top">{observations.length ? observations.map((observation, itemIndex) => <Observation key={`${observation.observation_id}:${itemIndex}`} observation={observation} />) : <p className="text-muted-foreground">未知 · 未提供观察记录</p>}</td>;
      })}
    </tr>)}</tbody>
  </table></div>;
}

// Normalize decimal spelling only, without converting the authoritative value to Number.
function decimalIdentity(value: string): string | null {
  const parts = /^([+-]?)(\d+)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/.exec(value.trim());
  if (!parts) return null;
  const fraction = parts[3] ?? "";
  const digits = (parts[2] + fraction).replace(/^0+/, "");
  if (!digits) return "0";
  const trailing = digits.match(/0+$/)?.[0].length ?? 0;
  const exponent = BigInt(parts[4] ?? "0") - BigInt(fraction.length) + BigInt(trailing);
  return `${parts[1] === "-" ? "-" : ""}${trailing ? digits.slice(0, -trailing) : digits}e${exponent}`;
}

function plotNumber(value: string): number | null {
  const numeric = Number(value);
  const original = decimalIdentity(value);
  // Reject overflow, underflow and decimal digits lost in the display conversion.
  return Number.isFinite(numeric) && original !== null && original === decimalIdentity(String(numeric)) ? numeric : null;
}

function PositioningFacet({ group }: { group: ViewPositioningGroup }) {
  const identity = useId();
  // Coordinates are scaled for display only. All grouping and comparisons belong to the server.
  const records = group.points.map((point, index) => {
    const nx = plotNumber(point.x), ny = plotNumber(point.y);
    const reasons = [
      ...(point.evidence_kind === "unknown" ? ["plot_evidence_unknown"] : []),
      ...(nx === null || ny === null ? ["plot_value_unrepresentable"] : []),
    ];
    return { ...point, index, nx, ny, reasons };
  });
  const numeric = records.flatMap(point => point.reasons.length || point.nx === null || point.ny === null ? [] : [{ ...point, nx: point.nx, ny: point.ny }]);
  const bounds = numeric.reduce((range, point) => ({
    minX: Math.min(range.minX, point.nx), maxX: Math.max(range.maxX, point.nx),
    minY: Math.min(range.minY, point.ny), maxY: Math.max(range.maxY, point.ny),
  }), { minX: Infinity, maxX: -Infinity, minY: Infinity, maxY: -Infinity });
  const { minX, maxX, minY, maxY } = bounds;
  const rangeUnsupported = numeric.length > 0 && (!Number.isFinite(maxX - minX) || !Number.isFinite(maxY - minY));
  const points = rangeUnsupported ? [] : numeric;
  const coordinate = (value: number, minimum: number, maximum: number, start: number, length: number) => minimum === maximum ? start + length / 2 : start + (value - minimum) / (maximum - minimum) * length;
  const price = group.price_context;
  return <section className="space-y-3 rounded-lg border p-4">
    <h3 className="font-semibold">{group.parameter?.name ?? group.parameter_id} v{group.parameter_version} · {group.unit ?? "单位未提供"} · {group.condition_note ?? "工况未提供"}</h3>
    {group.test_conditions !== undefined && <p className="text-xs text-muted-foreground">{testConditions(group.test_conditions)}</p>}
    <p className="text-sm text-muted-foreground">{price.currency ?? "币种未提供"} · {labels[price.basis ?? ""] ?? price.basis ?? "价格口径未提供"} · {price.as_of ?? "日期未提供"} · {labels[price.channel ?? ""] ?? price.channel ?? "渠道未提供"} · {price.region ?? "地区未提供"}</p>
    <p className="text-xs text-muted-foreground">含税：{price.includes_tax === null ? "未知" : price.includes_tax ? "是" : "否"} · 含运费：{price.includes_shipping === null ? "未知" : price.includes_shipping ? "是" : "否"} · 样本 {group.sample_count}</p>
    {points.length > 0 ? <svg viewBox="0 0 560 290" role="img" aria-labelledby={`${identity}-title ${identity}-description`} className="w-full text-muted-foreground">
      <title id={`${identity}-title`}>同口径价格与参数定位</title><desc id={`${identity}-description`}>横轴价格，纵轴参数值。实测实心，宣传空心，推断虚线；详细数值与来源列于图后。</desc>
      <path d="M60 20 V240 H540" fill="none" stroke="currentColor" />
      <text x="60" y="260" fontSize="11" fill="currentColor">{text(minX)}</text><text x="535" y="260" fontSize="11" textAnchor="end" fill="currentColor">{text(maxX)}</text>
      <text x="52" y="235" fontSize="11" textAnchor="end" fill="currentColor">{text(minY)}</text><text x="52" y="30" fontSize="11" textAnchor="end" fill="currentColor">{text(maxY)}</text>
      <text x="300" y="283" fontSize="12" textAnchor="middle" fill="currentColor">价格（{price.currency ?? "币种未提供"}）</text>
      {points.map(point => <a key={point.index} href={`#${identity}-source-${point.index}`} aria-label={`${point.label}：价格 ${point.x}，参数 ${point.y}，查看来源`} onClick={() => {
        const detail = document.getElementById(`${identity}-source-${point.index}`);
        if (detail instanceof HTMLDetailsElement) detail.open = true;
      }}>
        {["observed", "measured", "claimed", "vendor_claimed", "inferred"].includes(point.evidence_kind)
          ? <circle cx={coordinate(point.nx, minX, maxX, 75, 445)} cy={coordinate(point.ny, minY, maxY, 225, -190)} r="6" className={point.subject.type === "competitor" ? "text-muted-foreground" : "text-primary"} fill={["observed", "measured"].includes(point.evidence_kind) ? "currentColor" : "var(--background)"} stroke="currentColor" strokeWidth="2" strokeDasharray={point.evidence_kind === "inferred" ? "3 2" : undefined}><title>{`${point.label} · ${point.x} / ${point.y} · ${labels[point.evidence_kind] ?? point.nature ?? point.evidence_kind}`}</title></circle>
          : <rect x={coordinate(point.nx, minX, maxX, 75, 445) - 5} y={coordinate(point.ny, minY, maxY, 225, -190) - 5} width="10" height="10" className={point.subject.type === "competitor" ? "text-muted-foreground" : "text-primary"} fill="currentColor"><title>{`${point.label} · ${labels[point.evidence_kind] ?? point.nature ?? point.evidence_kind}`}</title></rect>}
      </a>)}
    </svg> : <p className="text-sm text-muted-foreground">此分组没有可绘制的已知坐标。</p>}
    {points.length !== group.points.length && <p className="text-sm text-muted-foreground">部分记录为未知或未提供有效坐标，仅保留来源详情。</p>}
    <ul className="space-y-3">{records.map((point, index) => <li key={index} className="space-y-2"><p className="break-words text-sm [overflow-wrap:anywhere]">{point.label} · 价格 {point.x} · 参数 {point.y} · {labels[point.evidence_kind] ?? point.nature ?? point.evidence_kind}</p><Reasons reasons={[...point.reasons, ...(rangeUnsupported && point.reasons.length === 0 ? ["plot_range_unrepresentable"] : [])]} /><ProposalSourceInspector id={`${identity}-source-${index}`} sources={point.source_refs} /></li>)}</ul>
  </section>;
}

function Maturity({ data, people }: { data: ViewMaturity; people: { id: string; name: string }[] }) {
  return <div className="space-y-4">
    <p>{data.spec_count} 条关键规格 · {data.option_count} 个方案</p>
    <div className="grid gap-3 sm:grid-cols-2">{[["规格状态", data.item_status_counts], ["信息可用性", data.availability_counts]].map(([title, counts]) => <section key={String(title)} className="rounded-lg border p-4"><h3 className="mb-2 font-semibold">{String(title)}</h3><dl className="space-y-1">{Object.entries(counts).map(([key, count]) => <div key={key} className="flex justify-between gap-3"><dt>{labels[key] ?? key}</dt><dd>{count}</dd></div>)}</dl></section>)}</div>
    <section className="space-y-2 rounded-lg border p-4"><h3 className="font-semibold">提交前检查</h3><p className="text-sm">为什么值得做：{data.submission_checks.worth_it_present ? "已填写" : "待填写"}</p><p className="text-sm">替代方案：{data.submission_checks.alternative_or_reason_required ? "需填写没有替代方案的理由" : "已提供多个方案"}</p></section>
    <section className="space-y-3 rounded-lg border p-4"><h3 className="font-semibold">冻结前待完善 · {data.freeze_blockers.length} 条</h3><p className="text-xs text-muted-foreground">这里列出服务器返回的阻断项；此视图不执行冻结。</p>{data.freeze_blockers.map(item => <div key={`${item.item_id}:${item.version}`} className="space-y-2 border-t pt-3"><p className="font-medium">{text(item.content.parameter ?? item.content.key ?? item.item_id)} · v{item.version}</p>{item.blocker_reasons?.length ? <Reasons reasons={item.blocker_reasons} /> : <p className="text-sm">服务器尚未提供逐项原因。</p>}<ProposalSourceInspector sources={item.source_refs ?? []} /></div>)}</section>
    <section className="space-y-3 rounded-lg border p-4"><h3 className="font-semibold">待决问题</h3>{data.questions.length === 0 && <p className="text-sm text-muted-foreground">服务器未返回待决问题。</p>}{data.questions.map(item => <div key={`${item.item_id}:${item.version}`} className="space-y-1 border-t pt-3"><p>{text(item.content.question)}</p><p className="text-sm text-muted-foreground">负责人：{text(item.content.owner_name ?? people.find(person => person.id === item.content.owner_id)?.name ?? item.content.owner_id)} · 期限：{text(item.content.due_date)} · {labels[String(item.content.status)] ?? text(item.content.status)}</p></div>)}</section>
    <p className="text-xs text-muted-foreground">{data.guidance ?? "10–20 条关键规格仅作提示；不计算综合分。"}</p>
  </div>;
}

export function ProposalViews({ view, result, document: currentDocument, people = [], loading = false, error, onRetry, onViewChange }: {
  view: ProposalViewName; result: ProposalViewResponse | null; document: ProposalViewDocument;
  people?: { id: string; name: string }[];
  loading?: boolean; error?: string | null; onRetry?: () => void; onViewChange?: (view: ProposalViewName) => void;
}) {
  const current = isProposalViewResponse(result) && result.view === view && matchesProposalDocument(result, currentDocument);
  let content;
  if (loading) content = <p role="status">正在读取当前提案视图…</p>;
  else if (error) content = <p role="alert">{error}</p>;
  else if (!result || !current) content = <p role="status">当前提案版本的视图尚不可用，请重新读取。</p>;
  else if (result.view === "definition-maturity") content = <Maturity data={result.data} people={people} />;
  else if (result.view === "positioning") content = <div className="space-y-4"><p className="text-sm text-muted-foreground">实测实心 · 宣传空心 · 推断虚线 · 其他性质方形 · 我方橙色 · 竞品灰色。未知 {result.data.unknown_count} 条，不绘制坐标。</p>{result.data.groups.length === 0 && <p>当前提案暂无可绘制的定位分组。请核对已映射的参数、数值、单位和工况；未知值不会绘制成坐标。</p>}{result.data.groups.map((group, index) => <PositioningFacet key={`${result.document_digest}:${group.key}:${index}`} group={group} />)}<Unknowns unknowns={[...result.data.unknowns, ...(result.data.unavailable ?? [])]} /><Unmapped observations={result.data.unmapped} /></div>;
  else content = <div className="space-y-4"><ComparisonTable groups={result.data.groups} subjects={result.data.subjects} features={result.view === "feature-config"} /><Unmapped observations={result.data.unmapped} subjects={result.data.subjects} />{result.view === "feature-config" && <UnmappedFeatures subjects={result.data.subjects} />}<Unknowns unknowns={result.data.unavailable ?? []} subjects={result.data.subjects} /></div>;
  return <section className={styles.view} aria-label="提案视图">
    {onViewChange && <nav aria-label="切换提案视图" className={styles.tabs}>{(Object.keys(proposalViewNames) as ProposalViewName[]).map(name => <Button className={styles.viewChip} size="xs" key={name} type="button" variant={view === name ? "secondary" : "ghost"} aria-current={view === name ? "page" : undefined} onClick={() => onViewChange(name)}>{proposalViewNames[name]}</Button>)}</nav>}
    <h2 className={styles.viewTitle}>{proposalViewNames[view]}</h2>
    {current && !loading && !error && <p className="text-xs text-muted-foreground">提案第 {result!.revision} 版 · {["frozen", "submission"].includes(result!.document_mode) ? "提交固定副本" : "文档视图"}{result!.context_changes.length > 0 ? " · 相关资料已有变化，请核对来源。" : ""}</p>}
    {content}
    {!loading && (error || !current) && onRetry && <Button type="button" variant="outline" onClick={onRetry}>重新读取当前视图</Button>}
  </section>;
}
