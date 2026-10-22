"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { readProjectManufacturingPreparation, readProjectManufacturingPreparationDocument } from "@/lib/project-manufacturing-preparation";
import type { ProjectManufacturingPreparation as PreparationReading, ProjectManufacturingPreparationApi, ProjectManufacturingPreparationDocumentBinding, ProjectManufacturingPreparationVersion } from "@/lib/project-manufacturing-preparation";
import { mpNames } from "../manufacturing-preparation/manufacturing-preparation-contract";
import type { MpParameter, MpRef, MpSource } from "../manufacturing-preparation/manufacturing-preparation-contract";
import styles from "./project-manufacturing-preparation.module.css";

type Props = { api: ProjectManufacturingPreparationApi; categoryId: string; productId: string; projectId: string; principalId: string; readVersion: number };
type Version = ProjectManufacturingPreparationVersion;
type Binding = ProjectManufacturingPreparationDocumentBinding;
type Page = { historyCursor?: string };
type DocumentRequest = { api: ProjectManufacturingPreparationApi; page: Page; baseline: Version; binding: Binding };
type DocumentReading = { request: DocumentRequest; data: Awaited<ReturnType<typeof readProjectManufacturingPreparationDocument>> | null; error: string };
type Documents = { request: DocumentRequest | null; reading: DocumentReading | null; read: (baseline: Version, binding: Binding) => void; close: () => void };
const unknown = (value: string | null) => value === null ? "未知" : value;
const operationName = (value: Version, key: string) => value.body.process_snapshot.operations.find(operation => operation.key === key)?.name ?? "工序名称未提供";

export function ProjectManufacturingPreparation(props: Props) {
  return <ScopedPreparation key={JSON.stringify([props.principalId, props.categoryId, props.productId, props.projectId, props.readVersion])} {...props} />;
}

function ScopedPreparation({ api, categoryId, productId, projectId }: Props) {
  const [page, setPage] = useState<Page>({});
  const [reading, setReading] = useState<{ api: ProjectManufacturingPreparationApi; page: Page; data: PreparationReading | null; error: string } | null>(null);
  const [selection, setSelection] = useState<DocumentRequest | null>(null);
  const [documentReading, setDocumentReading] = useState<DocumentReading | null>(null);
  const current = reading?.api === api && reading.page === page ? reading : null;
  const data = current?.data ?? null, error = current?.error ?? "";
  const selected = selection?.api === api && selection.page === page && data && [...data.currentVersions, ...data.returnedHistory].includes(selection.baseline) ? selection : null;
  const fixed = documentReading?.request === selected ? documentReading : null;
  const live = useRef<{ api: ProjectManufacturingPreparationApi; page: Page; selected: DocumentRequest | null } | null>(null);
  useLayoutEffect(() => {
    const input = { api, page, selected };
    live.current = input;
    return () => { if (live.current === input) live.current = null; };
  }, [api, page, selected]);
  useEffect(() => {
    let active = true;
    const isCurrent = () => active && live.current?.api === api && live.current.page === page;
    void readProjectManufacturingPreparation(api, { categoryId, productId, projectId }, page).then(value => {
      if (isCurrent()) setReading({ api, page, data: value, error: "" });
    }).catch(failure => {
      if (isCurrent()) setReading({ api, page, data: null, error: failure instanceof Error ? failure.message : "本项目制造准备资料未完整取得。" });
    });
    return () => { active = false; };
  }, [api, categoryId, productId, projectId, page]);
  useEffect(() => {
    if (!selected) return;
    let active = true;
    const isCurrent = () => active && live.current?.api === api && live.current.page === page && live.current.selected === selected;
    void readProjectManufacturingPreparationDocument(api, { categoryId, productId, projectId }, selected.baseline, selected.binding).then(value => {
      if (isCurrent()) setDocumentReading({ request: selected, data: value, error: "" });
    }).catch(failure => {
      if (!isCurrent()) return;
      const message = failure instanceof Error ? failure.message : "基线固定子文档未完整取得。";
      setDocumentReading({ request: selected, data: null, error: message });
      if ((failure as Error & { status?: number })?.status !== 503) setReading({ api, page, data: null, error: `固定子文档的权限或版本无法核对，已隐藏本页旧资料：${message}` });
    });
    return () => { active = false; };
  }, [api, categoryId, productId, projectId, page, selected]);
  const refresh = () => setPage({ ...page });
  const documents: Documents = { request: selected, reading: fixed, read: (baseline, binding) => setSelection({ api, page, baseline, binding }), close: () => setSelection(null) };
  return <section className={styles.panel} aria-label="本项目制造准备资料">
    <header className={styles.heading}><h2>制造准备资料</h2><Button type="button" size="xs" variant="outline" onClick={refresh}>刷新制造资料</Button></header>
    {error ? <div className={styles.notice} role="alert"><p>制造准备资料暂不可读：{error}</p><div className={styles.actions}><Button type="button" size="xs" variant="outline" onClick={refresh}>重新读取制造资料</Button>{page.historyCursor !== undefined && <Button type="button" size="xs" variant="outline" onClick={() => setPage({})}>回历史首页</Button>}</div></div> : !data ? <p className={styles.notice} role="status">正在读取本项目制造准备草稿…{page.historyCursor !== undefined && "正在读取所选历史页；旧页和固定子文档已隐藏。"}</p> : <>
      <p className={styles.note}>{page.historyCursor === undefined ? "历史首页" : "历史分页"}：本页重新取得当前版本及单页历史，不累加前页内容或不可读条数。</p>
      <p className={styles.note}>本次可读的当前版本 {data.currentVersions.length} 条，按各资料系列分别保留；当前仅指该系列版本头。以下均为草稿资料，不能据此判断正式发布或当前就绪。</p>
      {data.unavailableCount > 0 && <p className={styles.notice}>本次读集有 {data.unavailableCount} 条资料暂不可读；无法据此区分当前或历史版本，也不代表本项目缺项总数。</p>}
      {data.hasMore && <p className={styles.notice}>尚有历史未读取；下一页只替换本页历史，当前版本每次由服务器重新返回。</p>}
      {data.currentVersions.length ? <div>{data.currentVersions.map(value => <PreparationVersion key={value.id} value={value} documents={documents} />)}</div> : <p className={styles.notice}>本次没有可展示的当前版本资料。{data.hasMore ? "仍有历史未读取。" : "这不构成全部制造准备资料的否定结论。"}</p>}
      <details className={styles.history}><summary>本次返回的历史版本（{data.returnedHistory.length} 条）</summary><p className={styles.context}>以下仅为本页历史，按各版保存时的固定配置、正文与引用展示，不以当前版本补齐历史。{!data.returnedHistory.length && "本页没有可展示的历史行，不推断从未保存历史。"}</p>{data.returnedHistory.map(value => <PreparationVersion key={value.id} value={value} documents={documents} />)}</details>
      <div className={styles.pagination}><Button type="button" size="xs" variant="outline" disabled={page.historyCursor === undefined} onClick={() => setPage({})}>回历史首页</Button><Button type="button" size="xs" variant="outline" disabled={data.nextCursor === null} onClick={() => { if (data.nextCursor !== null) setPage({ historyCursor: data.nextCursor }); }}>下一页历史</Button><span>{data.hasMore ? "尚有历史未读取。" : "本页未提供下一页历史位置。"}</span></div>
      <p className={styles.foot}>保存时缺项不会在此自动重算。正式发布、人员、工装、物料与库存资格不在本次读集内；未读取不等于未登记或未满足。</p>
    </>}
  </section>;
}

export function PreparationVersion({ value, documents }: { value: Version; documents?: Documents }) {
  const { input, process_snapshot: process, gaps } = value.body;
  return <article className={styles.record} aria-label={`制造准备资料 ${value.id}`}>
    <div className={styles.title}><h3>{value.title}</h3><span>{mpNames[value.kind]} · v{value.revision}</span></div>
    <p className={styles.meta}>{value.is_current ? "本系列当前版本" : "固定历史版本"} · {value.source_status === "current" ? "来源状态：当前" : "来源状态：需重核"}</p>
    <dl className={styles.facts}><div><dt>固定制造配置</dt><dd>{process.name} · v{value.process.revision}<small>{value.process.id}</small></dd></div><div><dt>固定工序</dt><dd>{value.operation_key === null ? "本版基线内各工序（见下方）" : <>{operationName(value, value.operation_key)}<small>{value.operation_key}</small></>}</dd></div></dl>
    <p className={styles.meta}>保存原时点：<time dateTime={value.created_at}>{value.created_at}</time></p>
    <details className={styles.material}><summary>{"steps" in input ? `作业步骤与参数（${input.steps.length} 步）` : "checks" in input ? `控制检查与判据（${input.checks.length} 项）` : `基线固定文档引用（${input.operations.length} 道工序）`}</summary>
      <p className={styles.context}>以下为本版保存的内容与未知项。</p>
      {"steps" in input && <><p>适用条件：{unknown(input.conditions)}</p>{input.steps.map((step, index) => <section key={step.key} className={styles.item} aria-label={`作业步骤 ${step.key}`}><h4>步骤 {index + 1} · {step.key}</h4><p className={styles.prose}>{step.text}</p><p>安全说明：{unknown(step.safety_notes)}</p><Parameters values={step.parameters} /><Sources values={step.sources} label="本步骤固定依据" /></section>)}</>}
      {"checks" in input && input.checks.map(check => <section key={check.key} className={styles.item} aria-label={`控制检查 ${check.key}`}><h4>{check.feature} · {check.key}</h4><dl className={styles.facts}><div><dt>检验方法</dt><dd>{unknown(check.method)}</dd></div><div><dt>频次</dt><dd>{unknown(check.frequency)}</dd></div><div><dt>采样方法</dt><dd>{unknown(check.sampling_method)}</dd></div><div><dt>异常反应</dt><dd>{unknown(check.reaction_plan)}</dd></div><div><dt>责任描述</dt><dd>{unknown(check.responsible_role)}</dd></div></dl>{check.criterion ? <Parameters values={[check.criterion]} /> : <p className={styles.context}>判据未知</p>}<Sources values={check.sources} label="本控制项固定依据" /></section>)}
      {"operations" in input && <><p>过程风险依据：{unknown(input.risk_notes)}</p><p>包装与标识依据：{unknown(input.packaging_label_basis)}</p><div className={styles.scroll} role="region" aria-label="基线固定文档引用" tabIndex={0}><table className={styles.table}><thead><tr><th>固定工序</th><th>作业指导书引用</th><th>控制计划引用</th></tr></thead><tbody>{input.operations.map(operation => <tr key={operation.operation_key}><td>{operationName(value, operation.operation_key)}<small>{operation.operation_key}</small></td><td><DocumentReference value={operation.work_instruction} operationKey={operation.operation_key} version={value} documents={documents} /></td><td><DocumentReference value={operation.control_plan} operationKey={operation.operation_key} version={value} documents={documents} /></td></tr>)}</tbody></table></div><p className={styles.context}>文档身份与内容指纹来自本版保存绑定；明确选择后才读取固定正文，不从当前文档补齐。固定内容指纹未由正文读取接口重新验证。</p>{documents?.request?.baseline === value && <FixedDocument documents={documents} />}</>}
      <Sources values={input.sources} label="本版总体固定依据" />
    </details>
    <details className={styles.details}><summary>保存时缺项（{gaps.length} 项，原记录）</summary>{gaps.length ? <ul>{gaps.map((gap, index) => <li key={`${gap.code}:${index}`}><span className={styles.prose}>{gap.detail}</span><small>{gap.code}{typeof gap.operation_key === "string" ? ` · 工序 ${gap.operation_key}` : ""}{typeof gap.key === "string" ? ` · 条目 ${gap.key}` : ""}{gap.fields?.length ? ` · 字段 ${gap.fields.join("、")}` : ""}</small></li>)}</ul> : <p>此版保存时未列出缺项，不代表当前无缺项或已就绪。</p>}</details>
    <details className={styles.details}><summary>固定身份、保存原因与回执</summary><dl className={styles.identities}><div><dt>资料版本</dt><dd>{value.id} · v{value.revision}</dd></div><div><dt>资料系列</dt><dd>{value.series_id}</dd></div><div><dt>前一固定版本</dt><dd>{value.previous_id === null ? "未登记前版" : `${value.previous_id} · v${value.previous_revision}`}</dd></div><div><dt>用途</dt><dd>{value.purpose}</dd></div><div><dt>保存原因</dt><dd className={styles.prose}>{input.reason}</dd></div><div><dt>记录属主</dt><dd>{value.owner_id}</dd></div><div><dt>可读范围原值</dt><dd>{value.visibility}</dd></div><div><dt>保存回执</dt><dd>{value.receipt_id}</dd></div><div><dt>本版固定来源读集</dt><dd><ul>{value.required_source_read_set.map(ref => <li key={ref.artifact_id}>{ref.artifact_id} · v{ref.expected_revision}</li>)}</ul></dd></div></dl></details>
  </article>;
}

function Parameters({ values }: { values: MpParameter[] }) {
  if (!values.length) return <p className={styles.context}>本步骤未声明参数，不补零或默认单位。</p>;
  return <div className={styles.scroll} role="region" aria-label="固定参数原值" tabIndex={0}><table className={styles.table}><thead><tr><th>参数</th><th>名义值</th><th>下界</th><th>上界</th><th>单位</th><th>固定依据</th></tr></thead><tbody>{values.map(parameter => <tr key={parameter.key}><td>{parameter.key}</td><td>{unknown(parameter.nominal)}</td><td>{unknown(parameter.lower)}</td><td>{unknown(parameter.upper)}</td><td>{unknown(parameter.unit)}</td><td><Sources values={parameter.sources} label="参数依据" /></td></tr>)}</tbody></table></div>;
}

function DocumentReference({ value, operationKey, version, documents }: { value: MpRef | null; operationKey: string; version: Version; documents?: Documents }) {
  if (value === null) return <>未知 / 未提供固定引用</>;
  const binding = version.body.document_bindings.find(item => item.operation_key === operationKey && item.kind === value.kind && item.id === value.id && item.revision === value.revision);
  return <>{mpNames[value.kind]} · 固定 v{value.revision}<small>{value.id}</small><details className={styles.details}><summary>保存时固定内容指纹（SHA-256）</summary><p>{binding?.body_sha256 ?? "固定内容指纹未提供"}</p></details>{documents && binding && <Button className={styles.documentButton} type="button" size="xs" variant="outline" aria-label={`读取基线 ${version.id} 工序 ${operationKey} 固定 ${value.kind} ${value.id} v${value.revision}`} aria-pressed={documents.request?.baseline === version && documents.request.binding === binding} onClick={() => documents.read(version, binding)}>展开固定正文</Button>}</>;
}

function FixedDocument({ documents }: { documents: Documents }) {
  const request = documents.request;
  if (!request) return null;
  const { baseline, binding } = request, current = documents.reading;
  return <section className={styles.fixedDocument} aria-label={`已选基线固定正文 ${baseline.id}`}><header className={styles.fixedHeading}><h4>{operationName(baseline, binding.operation_key)} · {mpNames[binding.kind]} · 固定 v{binding.revision}</h4><Button type="button" size="xs" variant="outline" onClick={documents.close}>收起固定正文</Button></header><p className={styles.context}>固定文档 {binding.id} · 基线 {baseline.id} · v{baseline.revision}；仅核对本次固定身份、项目、制造配置和工序。保存时指纹 {binding.body_sha256}，正文读取接口未返回可复验的正文指纹。</p>{current?.error ? <div className={styles.notice} role="alert"><p>固定正文暂不可读：{current.error}</p><Button type="button" size="xs" variant="outline" onClick={() => documents.read(baseline, binding)}>重新读取固定正文</Button></div> : !current?.data ? <p className={styles.context} role="status">正在读取所选固定子文档；尚未取得标题、正文与原缺项。</p> : <PreparationVersion value={current.data.document} />}</section>;
}

function Sources({ values, label }: { values: MpSource[]; label: string }) {
  return <details className={styles.details}><summary>{label}（{values.length} 条）</summary>{values.length ? <ul>{values.map((source, index) => <li key={`${source.artifact_id}:${source.expected_revision}:${source.line}:${index}`}><p className={styles.prose}>{source.quote}</p><small>{source.artifact_id} · v{source.expected_revision} · 行 {source.line}</small></li>)}</ul> : <p>本字段未提供固定依据。</p>}</details>;
}
