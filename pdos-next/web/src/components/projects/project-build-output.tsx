"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import type { ProjectBuildApi, ProjectBuildRecord, ProjectBuildScope } from "@/lib/project-build-summary";
import { readProjectBuildOutput } from "@/lib/project-build-output";
import styles from "./project-build-output.module.css";

type Props = { api: ProjectBuildApi; scope: ProjectBuildScope; build: ProjectBuildRecord; onAccessRejected?: (message: string) => void };
type OutputReading = Awaited<ReturnType<typeof readProjectBuildOutput>>;
type ActualConfiguration = OutputReading["actualConfigurations"][number];
type Lot = OutputReading["lots"][number];
type Sample = OutputReading["samples"][number];
const registered = (value: string | null) => value === null || !value.trim() ? "未登记" : value;
const sourceState = (value: "current" | "needs_recheck") => value === "current" ? "来源当前可读" : "来源需重核";
const nature = (value: "real" | "synthetic") => value === "synthetic" ? "合成观测记录" : "实物观测登记";

export function ProjectBuildOutput(props: Props) {
  const { categoryId, productId, projectId } = props.scope;
  return <ScopedBuildOutput key={JSON.stringify([categoryId, productId, projectId, props.build.id, props.build.revision])} {...props} />;
}

function ScopedBuildOutput({ api, scope, build, onAccessRejected }: Props) {
  const { categoryId, productId, projectId } = scope;
  const [attempt, setAttempt] = useState(0);
  const [reading, setReading] = useState<{ api: ProjectBuildApi; build: ProjectBuildRecord; attempt: number; data: OutputReading | null; error: string } | null>(null);
  const live = useRef<{ api: ProjectBuildApi; build: ProjectBuildRecord; attempt: number; onAccessRejected: Props["onAccessRejected"] } | null>(null);
  useLayoutEffect(() => {
    const input = { api, build, attempt, onAccessRejected };
    live.current = input;
    return () => { if (live.current === input) live.current = null; };
  }, [api, build, attempt, onAccessRejected]);
  const current = reading?.api === api && reading.build === build && reading.attempt === attempt ? reading : null;
  const data = current?.data ?? null, error = current?.error ?? "";
  useEffect(() => {
    let active = true;
    const isCurrent = () => active && live.current?.api === api && live.current.build === build && live.current.attempt === attempt && live.current.onAccessRejected === onAccessRejected;
    void readProjectBuildOutput(api, { categoryId, productId, projectId }, build).then(value => {
      if (isCurrent()) setReading({ api, build, attempt, data: value, error: "" });
    }).catch(failure => {
      if (!isCurrent()) return;
      const failed = failure as Error & { status?: number };
      const message = failed instanceof Error ? failed.message : "产出批次与样件资料未完整取得。";
      setReading({ api, build, attempt, data: null, error: message });
      if (failed?.status !== 503) onAccessRejected?.(`当前轮次的权限、来源或固定版本无法核对，已隐藏旧轮次资料：${message}`);
    });
    return () => { active = false; };
  }, [api, categoryId, productId, projectId, build, attempt, onAccessRejected]);
  const partial = !!data && (data.productUnavailableCount > 0 || data.productHasMore);
  return <section className={styles.panel} aria-label="本轮产出批次与样件登记">
    <header className={styles.heading}><h3>产出批次与样件登记</h3><Button type="button" size="xs" variant="outline" onClick={() => setAttempt(value => value + 1)}>刷新产出与样件</Button></header>
    {error ? <div className={styles.notice} role="alert"><p>产出与样件摘要暂不可读：{error}</p><Button type="button" size="xs" variant="outline" onClick={() => setAttempt(value => value + 1)}>重新读取产出与样件</Button></div> : !data ? <p className={styles.notice} role="status">正在核对本轮实际配置、批次与样件登记…</p> : <>
      <p className={styles.note}>以下为 {data.build.name} · v{data.build.revision} 的已读取登记记录。{partial ? "型号读集尚未完整，不代表本轮全部产出或样件。" : "数量仅指已读取的登记记录。"}</p>
      {data.productUnavailableCount > 0 && <p className={styles.notice}>型号范围内 {data.productUnavailableCount} 条记录暂不可读；该数不是本轮缺失记录数。</p>}
      {data.productHasMore && <p className={styles.notice}>型号范围内仍有未读取记录，以下仅展示已核对的本轮记录。</p>}
      <div className={styles.section}><h4>实际双配置</h4>
        {data.actualConfigurations.length ? <div className={styles.configs}>{data.actualConfigurations.map(value => <Configuration key={value.id} value={value} />)}</div> : <p className={styles.empty}>{partial ? "本次尚无可展示的本轮实际配置，读取范围尚未完整。" : "当前可读范围内尚无本轮实际配置登记。"}</p>}
      </div>
      <div className={styles.section}><h4>产出批次</h4>
        {data.lots.length ? <div className={styles.lots}>{data.lots.map(value => <LotRecord key={value.id} value={value} data={data} />)}</div> : <p className={styles.empty}>{partial ? "本次尚无可展示的本轮批次，读取范围尚未完整。" : "当前可读范围内尚无本轮产出批次登记。"}</p>}
      </div>
      <div className={styles.section}><h4>样件保管与去向登记</h4>
        {data.samples.length ? <div className={styles.scroll}><table className={styles.table}><thead><tr><th>样件 / 模穴</th><th>保管人 / 位置</th><th>登记去向</th><th>登记状态与身份</th></tr></thead><tbody>{data.samples.map(value => <SampleRecord key={value.id} value={value} data={data} />)}</tbody></table></div> : <p className={styles.empty}>{partial ? "本次尚无可展示的本轮样件，读取范围尚未完整。" : "当前可读范围内尚无本轮样件单件标识登记。"}</p>}
      </div>
      <p className={styles.foot}>保管、位置、去向与可用性均为登记时字段，不代表实时到达、预约、消耗或当前可用；此摘要不提供试模合格结论。</p>
    </>}
  </section>;
}

function Configuration({ value }: { value: ActualConfiguration }) {
  return <article className={styles.config} aria-label={`实际配置登记 ${value.id}`}>
    <p className={styles.recordTitle}>实际配置登记 · v{value.revision}<span>{sourceState(value.sourceStatus)}</span></p>
    <dl className={styles.facts}><div><dt>实际工程配置</dt><dd>{value.actualEngineering.name} · 固定 v{value.actualEngineering.revision}</dd></div><div><dt>实际制造配置</dt><dd>{value.actualManufacturing.name} · 固定 v{value.actualManufacturing.revision}</dd></div></dl>
    <p className={styles.meta}>观测原时点：<time dateTime={value.observedAt}>{value.observedAt}</time></p>
    <details className={styles.details}><summary>计划配置对照与登记标识</summary><dl className={styles.facts}>
      {([["计划工程配置", value.plannedEngineering], ["计划制造配置", value.plannedManufacturing], ["实际工程配置", value.actualEngineering], ["实际制造配置", value.actualManufacturing]] as const).map(([label, ref]) => <div key={label}><dt>{label}</dt><dd>{ref.name} · 固定 v{ref.revision}<small>{ref.id}</small></dd></div>)}
      <div><dt>实际配置记录</dt><dd>{value.id} · v{value.revision}</dd></div><div><dt>记录创建原时点</dt><dd>{value.createdAt}</dd></div>
    </dl></details>
  </article>;
}

function LotRecord({ value, data }: { value: Lot; data: OutputReading }) {
  const configuration = data.actualConfigurations.find(item => item.id === value.actualConfiguration.id && item.revision === value.actualConfiguration.revision);
  const allocations = data.allocations.filter(item => item.lotId === value.id);
  return <article className={styles.lot} aria-label={`产出批次 ${value.id}`}>
    <p className={styles.recordTitle}>{value.lotLabel}<span>{nature(value.observation.nature)} · {sourceState(value.sourceStatus)}</span></p>
    <dl className={styles.facts}><div><dt>产出登记件数</dt><dd>{value.observedUnitCount} {value.unit}</dd></div><div><dt>已登记单件标识数</dt><dd>{value.identifiedCount}</dd></div><div><dt>尚未登记单件标识数</dt><dd>{value.remainingUnitCount}</dd></div><div><dt>固定实际配置</dt><dd>{configuration ? <>{configuration.actualEngineering.name} · v{configuration.actualEngineering.revision}<small>{configuration.actualManufacturing.name} · v{configuration.actualManufacturing.revision}</small></> : "实际配置未完整取得"}</dd></div></dl>
    <p className={styles.meta}>观测原时点：<time dateTime={value.observation.occurredAt}>{value.observation.occurredAt}</time><span>系统收到记录：<time dateTime={value.observation.receivedAt}>{value.observation.receivedAt}</time></span></p>
    <details className={styles.details}><summary>批次、观测与分配登记</summary><dl className={styles.facts}>
      <div><dt>批次记录</dt><dd>{value.id} · v{value.revision}</dd></div><div><dt>固定实际配置记录</dt><dd>{value.actualConfiguration.id} · v{value.actualConfiguration.revision}</dd></div><div><dt>外部观测系统</dt><dd>{value.observation.system}</dd></div><div><dt>外部观测标识</dt><dd>{value.observation.externalId}</dd></div><div><dt>服务端本轮同单位产出登记数</dt><dd>{value.buildObservedUnitCount} {value.unit}<small>登记汇总，不代表实到、合格或可用数量。</small></dd></div><div><dt>记录创建原时点</dt><dd>{value.createdAt}</dd></div>
    </dl>
      {allocations.length ? <div className={styles.allocations}>{allocations.map(allocation => <div key={allocation.id}><p>单件标识分配登记 {allocation.unitCount} 件 · v{allocation.revision} · {sourceState(allocation.sourceStatus)}</p><small>创建原时点：{allocation.createdAt}</small><p>分配记录 {allocation.id}</p><ul>{allocation.sampleIds.map(id => <li key={id}>{data.samples.find(sample => sample.id === id)?.label ?? "样件名称暂不可读"}<small>{id}</small></li>)}</ul></div>)}</div> : <p className={styles.context}>{data.productHasMore || data.productUnavailableCount > 0 ? "本次未取得本批次的单件标识分配记录，读取范围尚未完整。" : "当前可读范围内尚无本批次单件标识分配登记。"}</p>}
    </details>
  </article>;
}

function SampleRecord({ value, data }: { value: Sample; data: OutputReading }) {
  const lot = data.lots.find(item => item.id === value.lotId);
  const custodian = value.custodianLabel?.trim() ? value.custodianLabel : value.custodianId ? "姓名未登记" : "未登记";
  return <tr aria-label={`样件登记 ${value.id}`}><td><strong>{value.label}</strong><small>批次：{lot?.lotLabel ?? "批次名称暂不可读"}</small><small>模穴：{registered(value.cavity)}</small><small>工序：{registered(value.operationKey)}</small></td><td>保管人：{custodian}<small>位置：{registered(value.location)}</small></td><td>{registered(value.destination)}</td><td><span>{nature(value.observationNature)}</span><small>{sourceState(value.sourceStatus)} · v{value.revision}</small><small>登记可用性：{value.recordedAvailability === "hold" ? "暂缓使用" : "未知"}</small>
    <details className={styles.details}><summary>样件固定身份与原记录</summary><dl className={styles.identities}><div><dt>样件标识</dt><dd>{value.id} · v{value.revision}</dd></div><div><dt>来源批次</dt><dd>{value.lotId}</dd></div><div><dt>分配记录</dt><dd>{value.allocationId}</dd></div><div><dt>固定实际配置记录</dt><dd>{value.actualConfiguration.id} · v{value.actualConfiguration.revision}</dd></div><div><dt>保管人标识</dt><dd>{registered(value.custodianId)}</dd></div><div><dt>记录创建原时点</dt><dd>{value.createdAt}</dd></div></dl></details>
  </td></tr>;
}
