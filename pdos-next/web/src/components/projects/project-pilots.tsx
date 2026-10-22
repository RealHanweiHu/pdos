"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { readProjectPilots } from "@/lib/project-pilots";
import type { ProjectPilotApi, ProjectPilotPage, ProjectPilotScope } from "@/lib/project-pilots";
import { nativeCountFields, nativeCountNames } from "@/lib/native-pilots";
import type { NativeGap, NativePilotItem } from "@/lib/native-pilots";
import styles from "./project-pilots.module.css";

type Props = ProjectPilotScope & { api: ProjectPilotApi; readVersion: number };
type Page = { cursor?: string };
type Row = Record<string, unknown>;
type Observation = NativePilotItem["observations"][number];
const record = (value: unknown): Row => value !== null && typeof value === "object" && !Array.isArray(value) ? value as Row : {};
const rows = (value: unknown): unknown[] => Array.isArray(value) ? value : [];
const original = (value: unknown) => value === null ? "未知（原值为空）" : typeof value === "string" || typeof value === "number" ? String(value) : "未提供";
const sourceState = (value: string) => value === "current" ? "来源当前可核" : "来源需重核";
const cohortName = (value: unknown) => value === "entire_lot" ? "整批（entire_lot）" : value === "fixed_sampled_subset" ? "固定抽样子集（fixed_sampled_subset）" : original(value);
const outcomes: Record<string, string> = { pass: "通过", fail: "失败", unknown: "未知", unprocessed: "未加工", good: "合格", scrap: "报废", rework_pending: "返工待定", undecided: "未决" };

export function ProjectPilots(props: Props) {
  return <ScopedPilots key={JSON.stringify([props.principalId, props.categoryId, props.productId, props.projectId, props.readVersion])} {...props} />;
}

function ScopedPilots({ api, categoryId, productId, projectId, principalId }: Props) {
  const [page, setPage] = useState<Page>({});
  const [reading, setReading] = useState<{ api: ProjectPilotApi; page: Page; data: ProjectPilotPage | null; error: string } | null>(null);
  const [selection, setSelection] = useState<{ api: ProjectPilotApi; page: Page; id: string } | null>(null);
  const live = useRef<{ api: ProjectPilotApi; page: Page } | null>(null);
  useLayoutEffect(() => {
    const input = { api, page };
    live.current = input;
    return () => { if (live.current === input) live.current = null; };
  }, [api, page]);
  useEffect(() => {
    let active = true;
    const isCurrent = () => active && live.current?.api === api && live.current.page === page;
    void readProjectPilots(api, { categoryId, productId, projectId, principalId }, page.cursor).then(value => {
      if (isCurrent()) setReading({ api, page, data: value, error: "" });
    }).catch(failure => {
      if (isCurrent()) setReading({ api, page, data: null, error: failure instanceof Error ? failure.message : "本页试产记录与原始统计未完整取得。" });
    });
    return () => { active = false; };
  }, [api, categoryId, productId, projectId, principalId, page]);
  const current = reading?.api === api && reading.page === page ? reading : null;
  const data = current?.data ?? null, error = current?.error ?? "";
  const selected = selection?.api === api && selection.page === page ? data?.items.find(item => item.pilot.id === selection.id) : undefined;
  const refresh = () => setPage({ cursor: page.cursor });
  return <section className={styles.panel} aria-label="本项目试产记录与原始统计">
    <header className={styles.heading}><h2>试产记录与原始统计</h2><Button type="button" size="xs" variant="outline" onClick={refresh}>刷新本页试产记录</Button></header>
    {error ? <div className={styles.notice} role="alert"><p>试产记录暂不可读：{error}</p><div className={styles.actions}><Button type="button" size="xs" variant="outline" onClick={refresh}>重新读取本页试产记录</Button>{page.cursor !== undefined && <Button type="button" size="xs" variant="outline" onClick={() => setPage({})}>回首页</Button>}</div></div> : !data ? <p className={styles.notice} role="status">正在读取本项目试产记录与原始统计…</p> : <>
      <p className={styles.note}>本页返回 {data.items.length} 条可读试产记录，非项目总数。选择后展开本页已返回的固定资料和全部可读观察。</p>
      {data.items.length ? <div className={styles.scroll} role="region" aria-label="本页可选试产记录" tabIndex={0}><table className={styles.table}><thead><tr><th>用途 / 固定记录</th><th>原准备 / 当前链</th><th>本页观察 / 来源</th><th>查看</th></tr></thead><tbody>{data.items.map(item => <tr key={item.pilot.id} data-selected={selected === item}><td><strong>{item.pilot.details.purpose}</strong><small>{item.pilot.id}</small></td><td>原准备 v{item.pilot.revision}<small>当前链 v{item.current.revision} · epoch {item.current.epoch}</small></td><td>{item.observations.length} 条观察<small>{sourceState(item.pilot.source_status)}</small></td><td><Button type="button" size="xs" variant={selected === item ? "secondary" : "outline"} aria-label={`展开试产记录 ${item.pilot.id}`} aria-pressed={selected === item} onClick={() => setSelection({ api, page, id: item.pilot.id })}>展开本页记录</Button></td></tr>)}</tbody></table></div> : <p className={styles.notice}>本页没有可展示的试产记录，不据此判断整个项目没有试产记录或观察。</p>}
      <div className={styles.pagination}><Button type="button" size="xs" variant="outline" disabled={page.cursor === undefined} onClick={() => setPage({})}>回首页</Button><Button type="button" size="xs" variant="outline" disabled={data.nextCursor === null} onClick={() => { if (data.nextCursor) setPage({ cursor: data.nextCursor }); }}>下一页试产记录</Button><span>{data.nextCursor ? "仍有下一页，不合并为全部记录。" : "本页未提供下一页位置。"}</span></div>
      {!selected && data.items.length > 0 && <p className={styles.notice}>请选择一条试产记录查看本页已返回内容。</p>}
      {selected && <PilotReading key={selected.pilot.id} item={selected} />}
      <p className={styles.foot}>本读集保留资格未知（unknown）、启动授权为否（false）、制造放行为空（null）。记录、缺项或统计值不构成成熟度、资源资格、真实试模或放行结论。</p>
    </>}
  </section>;
}

function PilotReading({ item }: { item: NativePilotItem }) {
  const root = item.pilot, details = root.details, material = record(root.material.pilot), engineering = record(material.engineering_configuration);
  return <section className={styles.reading} aria-label={`已选试产 ${root.id}`}>
    <h3>{details.purpose}</h3><p className={styles.context}>固定原准备 v{root.revision} · 当前链 v{item.current.revision} · epoch {item.current.epoch} · {sourceState(root.source_status)}</p>
    <Basis value={details.basis} />
    <dl className={styles.facts}><div><dt>固定产品定义</dt><dd><FixedReference value={engineering.definition} /></dd></div><div><dt>固定制造基线</dt><dd><FixedReference value={details.manufacturing_baseline} /></dd></div><div><dt>固定产线引用</dt><dd><FixedReference value={details.line} /></dd></div><div><dt>原准备保存时点</dt><dd>{original(record(root).created_at)}</dd></div></dl>
    <details className={styles.details}><summary>原准备统计声明与保存缺项</summary><StatisticsBasis value={root.statistics_basis} /><Gaps values={root.gaps} /><Source value={details.source} label="原准备固定依据" /></details>
    <details className={styles.details}><summary>原准备、当前指针与回执标识</summary><dl className={styles.identities}><div><dt>固定原准备</dt><dd>{root.id} · v{root.revision}</dd></div><div><dt>最新观察指针</dt><dd>{item.current.latest_observation_id ?? "原值为空，未指向观察"}</dd></div><div><dt>原准备回执</dt><dd>{root.receipt_id}</dd></div><div><dt>原准备记录属主</dt><dd>{original(record(root).owner_id)}</dd></div></dl></details>
    <h4 className={styles.subheading}>原始观察与更正链</h4><p className={styles.context}>每条观察分别保留；更正不作为新增投入，不跨观察求和、平均或重算比例。</p>
    {item.observations.length ? item.observations.map(observation => <ObservationReading key={observation.id} value={observation} latest={observation.id === item.current.latest_observation_id} />) : <p className={styles.context}>本条已返回记录未含原始观察；原准备不代表已开工。</p>}
  </section>;
}

function Basis({ value }: { value: unknown }) {
  const basis = record(value);
  return <dl className={styles.facts}>{([ ["build", "固定 Build"], ["lot", "固定批次"], ["actual_configuration", "固定实际配置"], ["engineering_configuration", "实际工程配置"], ["process_revision", "实际制造工艺"] ] as const).map(([key, label]) => <div key={key}><dt>{label}</dt><dd><FixedReference value={basis[key]} /></dd></div>)}<div><dt>原计量单位</dt><dd>{original(basis.unit)}</dd></div></dl>;
}

function StatisticsBasis({ value }: { value: unknown }) {
  if (value === null) return <p>原准备未提供统计声明（原值为空），不补统计范围。</p>;
  const basis = record(value);
  return <><dl className={styles.facts}>{([ ["statistics_basis_key", "统计口径键"], ["site", "声明地点"], ["window_start", "窗口原起点"], ["window_end", "窗口原终点"], ["original_timezone", "声明原时区"], ["criterion_text", "本 Pilot 判据原文"], ["minimum_sample", "声明最小样本"], ["operation_key", "工序键"] ] as const).map(([key, label]) => <div key={key}><dt>{label}</dt><dd className={styles.prose}>{original(basis[key])}</dd></div>)}<div><dt>声明成员范围</dt><dd>{cohortName(basis.cohort_mode)}</dd></div><div><dt>声明固定判据</dt><dd>{original(basis.criterion_id)} · v{original(basis.criterion_revision)}</dd></div></dl><ReferenceSet value={basis.samples} label="声明样本引用" /><Source value={basis.source} label="统计声明固定依据" /></>;
}

function ObservationReading({ value, latest }: { value: Observation; latest: boolean }) {
  const { record: raw, projection } = value, scope = record(raw.scope), observed = record(raw.observed), metrics = record(projection?.metrics);
  return <article className={styles.observation} aria-label={`试产观察 ${value.id}`}><div className={styles.recordHeading}><h4>观察记录 v{value.revision}</h4><span>{latest ? "当前指针所指观察" : "保留观察"} · {sourceState(value.source_status)}</span></div>
    <p className={styles.context}>本条绑定 Pilot 预期 v{raw.expected_pilot_revision}；{raw.previous_observation_id === null ? "首条原始观察，无前驱。" : "更正续记，原观察仍保留。"}</p>
    <dl className={styles.facts}><div><dt>观察发生原时点</dt><dd><time dateTime={original(observed.occurred_at)}>{original(observed.occurred_at)}</time></dd></div><div><dt>观察原时区</dt><dd>{original(observed.original_timezone)}</dd></div><div><dt>观察生效原时点</dt><dd>{original(observed.effective_at)}</dd></div><div><dt>观察保存原时点</dt><dd>{original(record(value).created_at)}</dd></div><div><dt>原统计窗口</dt><dd>{original(scope.window_start)} — {original(scope.window_end)}</dd></div><div><dt>原记录性质</dt><dd>{scope.nature === "synthetic" ? "合成（synthetic）" : scope.nature === "real" ? "真实（real，原记录字段）" : original(scope.nature)}</dd></div></dl>
    {raw.previous_observation_id !== null && <p className={styles.prose}>原更正原因：{original(raw.correction_reason)}</p>}
    <Counts value={raw.counts} label="原批次计数" />
    {raw.units.length > 0 && <UnitOutcomes value={raw.units} />}
    <h5 className={styles.subheading}>服务器原统计投影</h5>{projection === null ? <p className={styles.context}>本观察投影为空，未提供良率结论；不补零，不以记录分数或其他观察替代。</p> : <><Rates value={metrics} /><details className={styles.details}><summary>服务器投影计数与原诊断</summary><Counts value={projection.counts} label="服务器投影计数" /><ul>{rows(metrics.warnings).map((warning, index) => <li key={index}>{original(warning)}</li>)}</ul><p>过程能力：{original(metrics.process_capability)} · 工厂资格：{original(metrics.factory_qualification)}</p><p>投影收到时间：{projection.received_at === null ? "原值为空，不作为收到时点" : original(projection.received_at)}</p></details></>}
    <details className={styles.details}><summary>本观察固定统计范围、成员与分母</summary><YieldScope value={scope} /><FixedStatistics value={value.fixed_scope} /></details>
    <details className={styles.details}><summary>异常、保存缺项、前驱与回执</summary>{raw.exceptions.length ? raw.exceptions.map((exception, index) => <section className={styles.exception} key={index}><h5>{original(exception.key)}</h5><p className={styles.prose}>{original(exception.description)}</p><p>固定关联问题：<FixedReference value={exception.issue} /></p><Source value={exception.source} label="异常固定依据" /><Source value={exception.disposition} label="处置固定依据" /></section>) : <p>本记录未列异常，不代表整个项目无异常。</p>}<Gaps values={value.gaps} /><dl className={styles.identities}><div><dt>本观察标识</dt><dd>{value.id} · v{value.revision}</dd></div><div><dt>固定前驱观察</dt><dd>{raw.previous_observation_id ?? "原值为空"}</dd></div><div><dt>本观察回执</dt><dd>{value.receipt_id}</dd></div></dl><Source value={raw.source} label="本观察固定原文" /><Source value={observed.source} label="观察时间固定依据" /></details>
  </article>;
}

function Counts({ value, label }: { value: unknown; label: string }) {
  if (value === null) return <p className={styles.context}>{label}为空，保留逐件原记录，不补零。</p>;
  const counts = record(value);
  return <div className={styles.scroll} role="region" aria-label={label} tabIndex={0}><table className={styles.table}><caption>{label} · 各项原值（不将返工次数加入投入）</caption><thead><tr>{nativeCountFields.map(key => <th key={key}>{nativeCountNames[key]}</th>)}</tr></thead><tbody><tr>{nativeCountFields.map(key => <td key={key}>{original(counts[key])}</td>)}</tr></tbody></table></div>;
}

function Rates({ value }: { value: Row }) {
  const rateNames = { known: "已知（known）", partial: "部分（partial）", unknown: "未知（unknown）", undefined_zero_denominator: "分母为零，未定义（undefined_zero_denominator）" };
  return <div className={styles.scroll} role="region" aria-label="服务器比例原值" tabIndex={0}><table className={styles.table}><thead><tr><th>统计项</th><th>原分子</th><th>固定分母</th><th>原 value</th><th>原 recorded_fraction</th><th>互斥分区完整</th><th>原状态</th></tr></thead><tbody>{([ ["first_pass_yield", "首遍良率"], ["final_good_yield", "最终合格率"] ] as const).map(([key, label]) => { const rate = record(value[key]); return <tr key={key}><td>{label}</td><td>{original(rate.numerator)}</td><td>{original(rate.denominator)}</td><td className={styles.mono}>{original(rate.value)}</td><td className={styles.mono}>{original(rate.recorded_fraction)}</td><td>{typeof rate.partition_complete === "boolean" ? rate.partition_complete ? "是（true）" : "否（false）" : "未提供"}</td><td>{rateNames[rate.state as keyof typeof rateNames] ?? original(rate.state)}</td></tr>; })}</tbody></table><p className={styles.context}>服务器原小数与记录分数分别保留，未换算百分比；部分分区不作为完整良率。</p></div>;
}

function YieldScope({ value }: { value: unknown }) {
  const scope = record(value);
  return <><Basis value={scope.basis} /><dl className={styles.facts}><div><dt>本观察固定制造基线</dt><dd><FixedReference value={scope.manufacturing_baseline} /></dd></div><div><dt>本观察固定产线</dt><dd><FixedReference value={scope.line} /></dd></div><div><dt>本观察固定判据</dt><dd><FixedReference value={scope.criterion} /></dd></div><div><dt>本观察最小样本</dt><dd>{original(scope.minimum_sample)}</dd></div><div><dt>本观察成员范围键</dt><dd>{original(scope.cohort_key)}</dd></div></dl></>;
}

function FixedStatistics({ value }: { value: unknown }) {
  if (value === null) return <p>本观察完整固定统计范围为空；保留原始值，不借用其他观察范围。</p>;
  const fixed = record(value), cohort = record(fixed.cohort);
  return <><dl className={styles.facts}><div><dt>固定统计用途</dt><dd>{original(fixed.purpose)}</dd></div><div><dt>固定统计地点 / 原时区</dt><dd>{original(fixed.site)} · {original(fixed.original_timezone)}</dd></div><div><dt>固定成员范围</dt><dd>{cohortName(cohort.mode)}</dd></div><div><dt>母批数量</dt><dd>{original(cohort.population_count)}</dd></div><div><dt>固定投入分母</dt><dd>{original(cohort.fixed_input_count)}</dd></div><div><dt>分母政策原值</dt><dd>{original(cohort.denominator_policy)}</dd></div><div><dt>固定统计口径键</dt><dd>{original(cohort.statistics_basis_key)}</dd></div><div><dt>固定 Pilot 版本</dt><dd>{original(fixed.pilot_id)} · v{original(fixed.pilot_revision)}</dd></div></dl><ReferenceSet value={cohort.unit_refs} label="固定投入成员" /><Source value={cohort.source} label="固定成员分母依据" /></>;
}

function UnitOutcomes({ value }: { value: Row[] }) {
  return <div className={styles.scroll} role="region" aria-label="逐件原始观察" tabIndex={0}><table className={styles.table}><thead><tr><th>固定样件</th><th>首遍原结果</th><th>最终原状态</th><th>返工次数（非新增投入）</th><th>固定依据</th></tr></thead><tbody>{value.map((unit, index) => <tr key={index}><td><FixedReference value={unit.sample} /></td><td>{outcomes[original(unit.first_result)] ?? original(unit.first_result)}</td><td>{outcomes[original(unit.final_state)] ?? original(unit.final_state)}</td><td>{original(unit.rework_cycles)}</td><td><Source value={unit.source} label="本单件固定依据" /></td></tr>)}</tbody></table></div>;
}

function FixedReference({ value }: { value: unknown }) { const ref = record(value); return value === null ? <>未知（原引用为空）</> : typeof ref.id === "string" && typeof ref.revision === "number" ? <>{ref.id} · v{ref.revision}</> : <>固定引用未提供</>; }
function ReferenceSet({ value, label }: { value: unknown; label: string }) { return <details className={styles.details}><summary>{label}</summary>{value === null ? <p>原值为空，未提供成员枚举；不等于零成员。</p> : !Array.isArray(value) ? <p>本字段未提供成员列表。</p> : value.length ? <ul>{value.map((ref, index) => <li key={index}><FixedReference value={ref} /></li>)}</ul> : <p>原列表为空，不代表全部成员。</p>}</details>; }
function Source({ value, label }: { value: unknown; label: string }) { const source = record(value); return <details className={styles.details}><summary>{label}</summary>{value === null || value === undefined ? <p>本字段未提供固定依据。</p> : <><p><FixedReference value={source} /></p><p>原定位：{original(source.position)}</p></>}</details>; }
function Gaps({ values }: { values: NativeGap[] }) { return <details className={styles.details}><summary>保存时缺项与诊断（{values.length} 条）</summary>{values.length ? <ul>{values.map((gap, index) => <li key={index}><p className={styles.prose}>{gap.detail}</p><small>{gap.code}{gap.state ? ` · ${gap.state}` : ""}</small></li>)}</ul> : <p>本次保存未列缺项，不代表当前成熟或已满足资格。</p>}</details>; }
