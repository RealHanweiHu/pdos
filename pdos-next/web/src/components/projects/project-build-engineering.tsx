"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { readProjectBuilds } from "@/lib/project-build-summary";
import type { ProjectBuildApi, ProjectBuildList, ProjectBuildRecord, ProjectBuildScope } from "@/lib/project-build-summary";
import { readProjectBuildEngineering } from "@/lib/project-build-engineering";
import type { ProjectBuildEngineering, ProjectBuildEngineeringExternalReference, ProjectBuildEngineeringSource } from "@/lib/project-build-engineering";
import styles from "./project-build-engineering.module.css";

type Props = ProjectBuildScope & { api: ProjectBuildApi; principalId: string; readVersion: number };
const unknown = (value: string | null) => value === null ? "未知" : value;
const sourceState = (value: "current" | "needs_recheck") => value === "current" ? "来源状态：当前" : "来源状态：需重核";

export function ProjectBuildEngineering(props: Props) {
  return <ScopedEngineering key={JSON.stringify([props.principalId, props.categoryId, props.productId, props.projectId, props.readVersion])} {...props} />;
}

function ScopedEngineering({ api, categoryId, productId, projectId }: Props) {
  const [attempt, setAttempt] = useState(0);
  const [reading, setReading] = useState<{ api: ProjectBuildApi; attempt: number; data: ProjectBuildList | null; error: string } | null>(null);
  const [selection, setSelection] = useState<{ api: ProjectBuildApi; attempt: number; id: string } | null>(null);
  const [detailAttempt, setDetailAttempt] = useState(0);
  const [detail, setDetail] = useState<{ api: ProjectBuildApi; attempt: number; build: ProjectBuildRecord; detailAttempt: number; data: ProjectBuildEngineering | null; error: string } | null>(null);
  const current = reading?.api === api && reading.attempt === attempt ? reading : null;
  const data = current?.data ?? null, error = current?.error ?? "";
  const selected = selection?.api === api && selection.attempt === attempt ? data?.items.find(item => item.id === selection.id) : undefined;
  const live = useRef<{ api: ProjectBuildApi; attempt: number; selected: ProjectBuildRecord | undefined; detailAttempt: number } | null>(null);
  useLayoutEffect(() => {
    const input = { api, attempt, selected, detailAttempt };
    live.current = input;
    return () => { if (live.current === input) live.current = null; };
  }, [api, attempt, selected, detailAttempt]);
  useEffect(() => {
    let active = true;
    const isCurrent = () => active && live.current?.api === api && live.current.attempt === attempt;
    void readProjectBuilds(api, { categoryId, productId, projectId }).then(value => {
      if (isCurrent()) setReading({ api, attempt, data: value, error: "" });
    }).catch(failure => {
      if (isCurrent()) setReading({ api, attempt, data: null, error: failure instanceof Error ? failure.message : "本项目 Build 列表未完整取得。" });
    });
    return () => { active = false; };
  }, [api, categoryId, productId, projectId, attempt]);
  useEffect(() => {
    if (!selected) return;
    let active = true;
    const isCurrent = () => active && live.current?.api === api && live.current.attempt === attempt && live.current.selected === selected && live.current.detailAttempt === detailAttempt;
    void readProjectBuildEngineering(api, { categoryId, productId, projectId }, selected).then(value => {
      if (isCurrent()) setDetail({ api, attempt, build: selected, detailAttempt, data: value, error: "" });
    }).catch(failure => {
      if (!isCurrent()) return;
      const message = failure instanceof Error ? failure.message : "已选 Build 的固定工程资料未完整取得。";
      setDetail({ api, attempt, build: selected, detailAttempt, data: null, error: message });
      if ((failure as Error & { status?: number })?.status !== 503) setReading({ api, attempt, data: null, error: `已选 Build 的权限或固定版本无法核对，已隐藏旧资料：${message}` });
    });
    return () => { active = false; };
  }, [api, categoryId, productId, projectId, attempt, selected, detailAttempt]);
  const currentDetail = detail?.api === api && detail.attempt === attempt && detail.build === selected && detail.detailAttempt === detailAttempt ? detail : null;
  const engineering = currentDetail?.data ?? null, detailError = currentDetail?.error ?? "";
  return <section className={styles.panel} aria-label="本项目 Build 固定工程配置">
    <header className={styles.heading}><h2>工程配置 · Build 固定引用</h2><Button type="button" variant="outline" size="xs" onClick={() => setAttempt(value => value + 1)}>刷新工程 Build 列表</Button></header>
    {error ? <div className={styles.notice} role="alert"><p>工程 Build 列表暂不可读：{error}</p><Button type="button" variant="outline" size="xs" onClick={() => setAttempt(value => value + 1)}>重新读取工程 Build 列表</Button></div> : !data ? <p className={styles.notice} role="status">正在读取本项目可读 Build…</p> : <>
      <p className={styles.note}>已读取 {data.items.length} 条可读 Build。请选择需要核对的轮次；工程配置按该轮计划固定引用读取，不代表规格冻结或工程批准。</p>
      {data.unavailableCount > 0 && <p className={styles.notice}>本次列表有 {data.unavailableCount} 条记录暂不可读，不能据此判断完整项目范围。</p>}{data.hasMore && <p className={styles.notice}>本次 Build 列表尚未完整，仅展示已读取轮次。</p>}
      {data.items.length ? <div className={styles.scroll} role="region" aria-label="可选 Build 固定工程配置" tabIndex={0}><table className={styles.table}><thead><tr><th>Build / 目的</th><th>计划固定工程配置</th><th>记录原时点 / 来源</th><th>核对</th></tr></thead><tbody>{data.items.map(build => <tr key={build.id} data-selected={selected === build}><td><strong>{build.name}</strong><small>v{build.revision} · {build.purpose}</small></td><td>{build.engineering_configuration.name}<small>固定 v{build.engineering_configuration.revision}</small></td><td><time dateTime={build.created_at}>{build.created_at}</time><small>{sourceState(build.source_status)}</small></td><td><Button type="button" size="xs" variant={selected === build ? "secondary" : "outline"} aria-label={`核对 ${build.name} 工程配置`} aria-pressed={selected === build} onClick={() => setSelection({ api, attempt, id: build.id })}>核对工程配置</Button></td></tr>)}</tbody></table></div> : <p className={styles.notice}>{data.unavailableCount > 0 || data.hasMore ? "本次没有可展示的 Build，读取范围尚未完整。" : "当前可读范围内尚无本项目 Build 记录。"}</p>}
      {!selected && data.items.length > 0 && <p className={styles.notice}>尚未选择 Build，未读取任何轮次的工程明细。</p>}
      {selected && <section className={styles.selected} aria-label="已选 Build 固定工程资料"><header className={styles.heading}><h3>已选 Build 固定工程资料</h3><Button type="button" size="xs" variant="outline" onClick={() => setDetailAttempt(value => value + 1)}>刷新已选工程配置</Button></header>{detailError ? <div className={styles.notice} role="alert"><p>固定工程资料暂不可读：{detailError}</p><Button type="button" size="xs" variant="outline" onClick={() => setDetailAttempt(value => value + 1)}>重新读取已选工程配置</Button></div> : !engineering ? <p className={styles.notice} role="status">正在重新核对已选 Build 的固定工程引用…</p> : <EngineeringReading value={engineering} />}</section>}
      <p className={styles.foot}>此处不读取最新配置，不判定引用漂移、固件已刷入、物料齐套或库存，也不提供设计责任人与接口确认事实。</p>
    </>}
  </section>;
}

function EngineeringReading({ value }: { value: ProjectBuildEngineering }) {
  const { build, configuration: config } = value, { bom, definition } = config;
  return <div className={styles.reading}>
    <p className={styles.note}>{build.name} · 固定 v{build.revision} · {sourceState(build.source_status)}</p>
    {value.unavailableCount > 0 && <p className={styles.note}>重新读取的 Build 列表有 {value.unavailableCount} 条记录暂不可读；这不是本轮工程配置缺项数。</p>}{value.hasMore && <p className={styles.note}>重新读取的 Build 列表尚未完整；以下仅对应本次已核对的选定轮次。</p>}
    <dl className={styles.facts}><div><dt>固定工程配置</dt><dd>{config.name} · v{config.revision}<small>草稿 · {sourceState(config.source_status)}</small></dd></div><div><dt>固定产品定义</dt><dd>{definition.title} · v{definition.revision}<small>定义状态原值：{definition.status === "published" ? "已发布" : "草稿"} · {sourceState(definition.source_status)}</small></dd></div><div><dt>固定研发 BOM</dt><dd>{bom.name} · v{bom.revision}<small>草稿 · {sourceState(bom.source_status)}</small></dd></div><div><dt>工程配置保存原时点</dt><dd><time dateTime={config.created_at}>{config.created_at}</time></dd></div></dl>
    <h4 className={styles.subheading}>固定 BOM 行 · 每份 BOM 原值</h4><p className={styles.context}>用量与损耗率均保留原值，不乘 Build 计划数量，不代表采购需求、实到或齐套。</p>
    <div className={styles.scroll} role="region" aria-label="固定 BOM 每份原值" tabIndex={0}><table className={styles.table}><thead><tr><th>条目 / 固定零件</th><th>每份用量</th><th>单位</th><th>损耗率原值</th><th>关键项 / 备注</th><th>固定零件登记</th></tr></thead><tbody>{bom.lines.map(line => <tr key={line.key}><td><strong>{line.key}</strong><small>{line.part.name} · 固定 v{line.expected_part_revision}</small><small>{line.part_id}</small><small>{sourceState(line.part.source_status)}</small></td><td className={styles.mono}>{unknown(line.quantity)}</td><td>{unknown(line.unit)}</td><td className={styles.mono}>{unknown(line.loss_rate)}</td><td>{line.critical ? "是（登记值）" : "否（登记值）"}<small className={styles.prose}>{unknown(line.notes)}</small></td><td><details className={styles.details}><summary>编号、映射与设计引用</summary><dl className={styles.identities}><div><dt>内部编号</dt><dd>{unknown(line.part.internal_number)}</dd></div><div><dt>ERP 编号声明</dt><dd>{unknown(line.part.erp_number)}</dd></div><div><dt>客户编号</dt><dd>{unknown(line.part.customer_number)}</dd></div><div><dt>映射版本</dt><dd>{unknown(line.part.mapping_version)}</dd></div><div><dt>映射状态原值</dt><dd>{line.part.mapping_status}</dd></div><div><dt>外部核实</dt><dd>未核实（not_checked）</dd></div><div><dt>零件记录属主</dt><dd>{line.part.owner_id}</dd></div><div><dt>零件保存原时点</dt><dd>{line.part.created_at}</dd></div></dl>{line.part.external_design_refs.length ? line.part.external_design_refs.map((ref, index) => <ExternalReference key={index} value={ref} label={`零件外部引用 ${index + 1}`} />) : <p>本零件版本未提供外部设计引用。</p>}<Sources values={line.part.sources} label="固定零件来源" /></details></td></tr>)}</tbody></table></div>
    <h4 className={styles.subheading}>机械 / 电子 / 固件固定引用</h4><div className={styles.designs}>{([ ["mechanical", "机械设计"], ["electronic", "电子设计"], ["firmware", "固件制品"] ] as const).map(([key, label]) => <ExternalReference key={key} value={config.design_versions[key]} label={label} />)}</div>
    <details className={styles.details}><summary>固定身份、记录属主与保存依据</summary><dl className={styles.identities}><div><dt>Build 固定身份</dt><dd>{build.id} · v{build.revision}</dd></div><div><dt>工程配置固定身份</dt><dd>{config.id} · v{config.revision}</dd></div><div><dt>定义固定身份</dt><dd>{config.definition_id} · v{config.definition_revision}</dd></div><div><dt>BOM 固定身份</dt><dd>{config.bom_id} · v{config.bom_revision}</dd></div><div><dt>BOM 保存原时点</dt><dd>{bom.created_at}</dd></div><div><dt>工程配置记录属主</dt><dd>{config.owner_id}</dd></div><div><dt>BOM 记录属主</dt><dd>{bom.owner_id}</dd></div><div><dt>工程配置系列</dt><dd>{config.series_id}</dd></div><div><dt>工程配置固定前版</dt><dd>{config.previous_id === null ? "未提供前版" : `${config.previous_id} · v${config.expected_previous_revision}`}</dd></div><div><dt>工程配置保存原因</dt><dd className={styles.prose}>{config.reason}</dd></div><div><dt>BOM 保存原因</dt><dd className={styles.prose}>{bom.reason}</dd></div><div><dt>外部核实</dt><dd>未核实（not_checked）</dd></div></dl><Sources values={config.sources} label="固定工程配置来源" /><Sources values={bom.sources} label="固定 BOM 来源" /><ul>{config.required_source_read_set.map(ref => <li key={ref.artifact_id}>{ref.artifact_id} · v{ref.expected_revision}</li>)}</ul></details>
  </div>;
}

function ExternalReference({ value, label }: { value: ProjectBuildEngineeringExternalReference | null; label: string }) {
  return <section className={styles.external} aria-label={label}><h5>{label}</h5>{value === null ? <p>本配置未提供固定引用。</p> : <><p>{value.system} · {value.external_id}</p><dl className={styles.facts}><div><dt>外部版本原值</dt><dd>{unknown(value.revision)}</dd></div><div><dt>资料截至时点</dt><dd>{value.as_of === null ? "未知" : <time dateTime={value.as_of}>{value.as_of}</time>}</dd></div></dl><details className={styles.details}><summary>内容指纹与固定依据</summary><p>SHA-256：{unknown(value.content_sha256)}</p>{value.basis ? <Sources values={[value.basis]} label="外部引用固定依据" /> : <p>本引用未提供原文依据。</p>}</details></>}</section>;
}

function Sources({ values, label }: { values: ProjectBuildEngineeringSource[]; label: string }) {
  return <details className={styles.details}><summary>{label}（{values.length} 条）</summary><ul>{values.map((source, index) => <li key={`${source.artifact_id}:${source.expected_revision}:${source.line}:${index}`}><p className={styles.prose}>{source.quote}</p><small>{source.artifact_id} · v{source.expected_revision} · 行 {source.line}</small></li>)}</ul></details>;
}
