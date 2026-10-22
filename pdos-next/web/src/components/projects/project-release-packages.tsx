"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { readProjectReleasePackage, readProjectReleasePackages } from "@/lib/project-release-packages";
import type { ProjectReleaseApi, ProjectReleaseHeader, ProjectReleaseList, ProjectReleasePackage, ProjectReleaseScope } from "@/lib/project-release-packages";
import type { ReleaseAssessment } from "@/lib/releases";
import styles from "./project-release-packages.module.css";

type Props = ProjectReleaseScope & { api: ProjectReleaseApi; readVersion: number };
type Page = { cursor?: string };
type Row = Record<string, unknown>;
const record = (value: unknown): Row => value !== null && typeof value === "object" && !Array.isArray(value) ? value as Row : {};
const rows = (value: unknown): unknown[] => Array.isArray(value) ? value : [];
const original = (value: unknown) => typeof value === "string" || typeof value === "number" ? String(value) : "未提供";
const names = { engineering: "工程", manufacturing: "制造" };
const states = { BLOCKED: "阻塞", UNKNOWN: "未知", READY_WITH_CONDITIONS: "附条件满足本范围检查", READY: "满足本范围检查" };
const applicability = (value: unknown) => value === "current" ? "当前适用依据可核" : value === "needs_recheck" ? "适用依据需重核，历史保留" : "适用性未核对";
const objectNames: Record<string, string> = { definition: "产品定义", engineering_configuration: "工程配置", manufacturing_configuration: "制造配置", process_revision: "制造配置", manufacturing_publication: "制造基线发布", test_run: "测试运行", pilot_run: "试产运行", issue: "问题", change: "变更", exception: "例外决定", artifact: "原件资料", work_instruction: "作业指导书", control_plan: "控制计划", build_lot: "制造批次", line: "产线" };

export function ProjectReleasePackages(props: Props) {
  return <ScopedReleasePackages key={JSON.stringify([props.principalId, props.categoryId, props.productId, props.projectId, props.readVersion])} {...props} />;
}

function ScopedReleasePackages({ api, categoryId, productId, projectId, principalId }: Props) {
  const [page, setPage] = useState<Page>({});
  const [reading, setReading] = useState<{ api: ProjectReleaseApi; page: Page; data: ProjectReleaseList | null; error: string } | null>(null);
  const [selection, setSelection] = useState<{ api: ProjectReleaseApi; page: Page; id: string; revision: number } | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [detail, setDetail] = useState<{ api: ProjectReleaseApi; page: Page; selected: ProjectReleaseHeader; attempt: number; data: ProjectReleasePackage | null; error: string } | null>(null);
  const current = reading?.api === api && reading.page === page ? reading : null;
  const data = current?.data ?? null, error = current?.error ?? "";
  const selected = selection?.api === api && selection.page === page ? data?.items.find(item => item.id === selection.id && item.revision === selection.revision) : undefined;
  const live = useRef<{ api: ProjectReleaseApi; page: Page; selected: ProjectReleaseHeader | undefined; attempt: number } | null>(null);
  useLayoutEffect(() => {
    const input = { api, page, selected, attempt };
    live.current = input;
    return () => { if (live.current === input) live.current = null; };
  }, [api, page, selected, attempt]);
  useEffect(() => {
    let active = true;
    const isCurrent = () => active && live.current?.api === api && live.current.page === page;
    void readProjectReleasePackages(api, { categoryId, productId, projectId, principalId }, page.cursor).then(value => {
      if (isCurrent()) setReading({ api, page, data: value, error: "" });
    }).catch(failure => {
      if (isCurrent()) setReading({ api, page, data: null, error: failure instanceof Error ? failure.message : "本页固定发布包未完整取得。" });
    });
    return () => { active = false; };
  }, [api, categoryId, productId, projectId, principalId, page]);
  useEffect(() => {
    if (!selected) return;
    let active = true;
    const isCurrent = () => active && live.current?.api === api && live.current.page === page && live.current.selected === selected && live.current.attempt === attempt;
    void readProjectReleasePackage(api, { categoryId, productId, projectId, principalId }, { id: selected.id, revision: selected.revision }).then(value => {
      if (isCurrent()) setDetail({ api, page, selected, attempt, data: value, error: "" });
    }).catch(failure => {
      if (!isCurrent()) return;
      const message = failure instanceof Error ? failure.message : "所选发布包与专业决定未完整取得。";
      setDetail({ api, page, selected, attempt, data: null, error: message });
      if ((failure as Error & { status?: number })?.status !== 503) setReading({ api, page, data: null, error: `所选固定包的权限、来源或版本无法核对，已隐藏旧资料：${message}` });
    });
    return () => { active = false; };
  }, [api, categoryId, productId, projectId, principalId, page, selected, attempt]);
  const currentDetail = detail?.api === api && detail.page === page && detail.selected === selected && detail.attempt === attempt ? detail : null;
  const fixed = currentDetail?.data ?? null, detailError = currentDetail?.error ?? "";
  const refresh = () => setPage({ cursor: page.cursor });
  return <section className={styles.panel} aria-label="本项目固定发布包与专业决定">
    <header className={styles.heading}><h2>固定发布包与专业决定</h2><Button type="button" size="xs" variant="outline" onClick={refresh}>刷新本页发布包</Button></header>
    {error ? <div className={styles.notice} role="alert"><p>固定发布包暂不可读：{error}</p><div className={styles.recovery}><Button type="button" size="xs" variant="outline" onClick={refresh}>重新读取本页发布包</Button>{page.cursor !== undefined && <Button type="button" size="xs" variant="outline" onClick={() => setPage({})}>回首页</Button>}</div></div> : !data ? <p className={styles.notice} role="status">正在读取本项目固定发布包…</p> : <>
      <p className={styles.note}>本页返回 {data.items.length} 条可读包版本，非项目总数。请选择固定版本后读取内容；系列当前头与专业决定分别核对。</p>
      {data.items.length ? <div className={styles.scroll} role="region" aria-label="可选固定发布包版本" tabIndex={0}><table className={styles.table}><thead><tr><th>用途 / 固定版本</th><th>系列位置</th><th>包记录 / 适用性</th><th>读取</th></tr></thead><tbody>{data.items.map(item => <tr key={item.id} data-selected={selected === item}><td><strong>{item.purpose}</strong><small>v{item.revision}</small><small>{item.id}</small></td><td>{item.isSeriesCurrent ? "本系列当前头" : "历史固定版本"}</td><td>已保存固定包<small>{applicability(item.applicability)}</small></td><td><Button type="button" size="xs" variant={selected === item ? "secondary" : "outline"} aria-label={`读取发布包 ${item.id} v${item.revision}`} aria-pressed={selected === item} onClick={() => setSelection({ api, page, id: item.id, revision: item.revision })}>读取固定包</Button></td></tr>)}</tbody></table></div> : <p className={styles.notice}>本页没有可展示的固定包版本，不据此推断整个项目或系列没有发布包。</p>}
      <div className={styles.pagination}><Button type="button" size="xs" variant="outline" disabled={page.cursor === undefined} onClick={() => setPage({})}>回首页</Button><Button type="button" size="xs" variant="outline" disabled={data.nextCursor === null} onClick={() => { if (data.nextCursor) setPage({ cursor: data.nextCursor }); }}>下一页发布包</Button><span>{data.nextCursor ? "仍有下一页，未合并为全部记录。" : "本页未提供下一页位置。"}</span></div>
      {!selected && data.items.length > 0 && <p className={styles.notice}>尚未选择固定包，未读取包内容与专业决定。</p>}
      {selected && <section className={styles.selected} aria-label="已选固定发布包详情"><header className={styles.heading}><h3>已选固定包与专业决定</h3><Button type="button" size="xs" variant="outline" onClick={() => setAttempt(value => value + 1)}>刷新已选固定包</Button></header>{detailError ? <div className={styles.notice} role="alert"><p>所选固定包暂不可读：{detailError}</p><Button type="button" size="xs" variant="outline" onClick={() => setAttempt(value => value + 1)}>重新读取已选固定包</Button></div> : !fixed ? <p className={styles.notice} role="status">正在核对所选固定版本、工程与制造决定…</p> : <PackageReading value={fixed} />}</section>}
      <p className={styles.foot}>系列当前头不代表放行或批准；适用依据需重核不等于撤回。客户承认、外部接收与实际生效分别记录；此处不提供 DVT 或 G2 正式评审结论。</p>
    </>}
  </section>;
}

function PackageReading({ value }: { value: ProjectReleasePackage }) {
  const { detail, assessments } = value, body = detail.package, declaration = record(body.declaration);
  return <div className={styles.reading}>
    <p className={styles.title}>{detail.purpose} · 固定包 v{detail.revision}</p><p className={styles.context}>{value.isSeriesCurrent ? "本系列当前头" : "历史固定版本"} · {applicability(detail.applicability)}</p>
    <ContentScope value={declaration} />
    <Limits value={declaration.limits} label="包内保存的限制" />
    <ExceptionBases value={body.exceptions} />
    <details className={styles.details}><summary>包内固定对象与证据</summary><ObjectReferences value={body.objects} /><Sources value={body.sources} label="包内固定证据引用" /><dl className={styles.identities}><div><dt>证据内容指纹</dt><dd>{original(body.evidence_digest)}</dd></div><div><dt>包正文内容指纹</dt><dd>{original(body.body_sha256)}</dd></div><div><dt>固定政策版本</dt><dd>{body.policy === null ? "未提供" : original(record(body.policy).version)}</dd></div></dl></details>
    <div className={styles.assessments}>{assessments.map(assessment => <Assessment key={assessment.discipline} value={assessment} label={`${names[assessment.discipline]}包范围检查`} />)}</div>
    <h4 className={styles.subheading}>已登记专业决定 · 各自固定范围</h4>
    {(["engineering", "manufacturing"] as const).map(discipline => <section key={discipline} className={styles.discipline} aria-label={`${names[discipline]}已登记决定`}><h4>{names[discipline]}决定</h4>{detail.decisions.some(row => row.discipline === discipline) ? detail.decisions.filter(row => row.discipline === discipline).map(row => <Decision key={String(row.id)} value={row} />) : <p className={styles.context}>本次可读固定包未返回{names[discipline]}决定记录。</p>}</section>)}
    <details className={styles.details}><summary>包记录、系列指针与保存回执</summary><dl className={styles.identities}><div><dt>固定包身份</dt><dd>{detail.id} · v{detail.revision}</dd></div><div><dt>包记录状态原值</dt><dd>{original(detail.status)}</dd></div><div><dt>系列指针</dt><dd>{detail.current.id}</dd></div><div><dt>系列当前固定版本</dt><dd><FixedReference value={detail.current.version} /></dd></div><div><dt>保存回执</dt><dd>{detail.receipt_id}</dd></div><div><dt>包记录属主</dt><dd>{original(body.owner_id)}</dd></div><div><dt>原固定型号版本</dt><dd>v{original(body.product_revision)}</dd></div><div><dt>保存说明</dt><dd className={styles.prose}>{original(declaration.reason)}</dd></div></dl></details>
  </div>;
}

function ContentScope({ value }: { value: Row }) {
  const configuration = record(value.subject_config), range = record(value.release_scope);
  return <><p className={styles.purpose}>用途：{original(value.purpose)}</p><dl className={styles.facts}>{([ ["definition", "固定产品定义"], ["engineering_configuration", "固定工程配置"], ["manufacturing_configuration", "固定制造配置"] ] as const).map(([key, label]) => <div key={key}><dt>{label}</dt><dd><FixedReference value={configuration[key]} /></dd></div>)}{([ ["quantity", "数量原值"], ["unit", "单位"], ["site", "场地"], ["lots", "批次"], ["lines", "产线"], ["regions", "地区"] ] as const).map(([key, label]) => <div key={key}><dt>{label}</dt><dd><RangeValue value={range[key]} /></dd></div>)}</dl></>;
}

function ExceptionBases({ value }: { value: unknown }) {
  return <details className={styles.details}><summary>包内固定例外依据（{rows(value).length} 条）</summary><p>以下为包内保存的固定依据；原状态与期限不作为本页重新判定的当前有效性。</p>{rows(value).map((item, index) => { const basis = record(item), scope = record(basis.scope), decision = record(basis.decision); return <section key={index} className={styles.exception} aria-label={`包内固定例外 ${original(decision.id)}`}><h4>固定例外决定 <FixedReference value={basis.decision} /></h4><ContentScope value={basis} /><dl className={styles.identities}><div><dt>保存时状态原值</dt><dd>{basis.state === null ? "原值为空" : original(basis.state)}</dd></div><div><dt>专业范围原值</dt><dd>{basis.discipline === "engineering" ? "工程" : basis.discipline === "manufacturing" ? "制造" : original(basis.discipline)}</dd></div><div><dt>固定政策版本</dt><dd>{basis.policy_version === null ? "原值为空" : original(basis.policy_version)}</dd></div><div><dt>固定检查键</dt><dd>{rows(basis.check_keys).length ? <ul>{rows(basis.check_keys).map((key, keyIndex) => <li key={keyIndex}>{original(key)}</li>)}</ul> : "本依据未提供检查键"}</dd></div><div><dt>原明确期限</dt><dd>{basis.expiry === null ? "未另设期限（原值为空）" : original(basis.expiry)}</dd></div><div><dt>固定型号范围</dt><dd>{original(scope.product_id)}</dd></div><div><dt>固定项目范围</dt><dd>{original(scope.project_id)}</dd></div></dl><Limits value={basis.limits} label="本例外固定限制" /><Sources value={basis.sources} label="本例外固定依据" /></section>; })}</details>;
}

function RangeValue({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <>未知 / 未覆盖</>;
  if (!Array.isArray(value)) return <>{original(value)}</>;
  return value.length ? <ul>{value.map((item, index) => <li key={index}>{typeof item === "string" ? item : <FixedReference value={item} />}</li>)}</ul> : <>明确为空，不代表全部</>;
}

function FixedReference({ value }: { value: unknown }) {
  const ref = record(value);
  return typeof ref.id === "string" && typeof ref.revision === "number" ? <>{ref.id} · v{ref.revision}</> : <>固定引用未提供</>;
}

function ObjectReferences({ value }: { value: unknown }) {
  return <div className={styles.scroll} role="region" aria-label="包内固定对象与内容指纹" tabIndex={0}><table className={styles.table}><thead><tr><th>对象种类</th><th>固定身份</th><th>内容指纹（SHA-256）</th></tr></thead><tbody>{rows(value).map((item, index) => { const row = record(item), ref = record(row.ref); return <tr key={index}><td>{objectNames[original(ref.kind)] ?? original(ref.kind)}</td><td><FixedReference value={ref} /></td><td>{original(row.sha256)}</td></tr>; })}</tbody></table></div>;
}

function Assessment({ value, label }: { value: ReleaseAssessment; label: string }) {
  return <section className={styles.assessment} aria-label={label}><h4>{label}</h4><p className={styles.state} data-state={value.state}>{states[value.state]}</p><p className={styles.context}>仅对应本条检查的固定范围，检查状态不替代具名决定。</p><h5>原检查项（{value.checks.length}）</h5>{value.checks.length ? value.checks.map((check, index) => <div className={styles.check} key={index}><p><strong>{original(check.key)}</strong> · {check.state === "satisfied" ? "满足" : check.state === "blocked" ? "阻塞" : check.state === "unknown" ? "未知" : "状态未提供"}</p><p className={styles.prose}>{original(check.detail)}</p><small>适用：{typeof check.applicable === "boolean" ? check.applicable ? "是" : "否" : "未提供"} · 必需：{typeof check.required === "boolean" ? check.required ? "是" : "否" : "未提供"} · 不可豁免：{typeof check.non_waivable === "boolean" ? check.non_waivable ? "是" : "否" : "未提供"}</small><details className={styles.details} aria-label={`检查范围 ${original(check.key)}`}><summary>本检查原范围与固定例外</summary>{check.release_scope === null ? <p>未单列本检查范围（原值为空），不以包全局范围补齐。</p> : check.release_scope === undefined ? <p>本检查范围未提供，不以包全局范围补齐。</p> : <dl className={styles.facts}>{([ ["quantity", "数量原值"], ["unit", "单位"], ["site", "场地"], ["lots", "批次"], ["lines", "产线"], ["regions", "地区"] ] as const).map(([key, field]) => <div key={key}><dt>{field}</dt><dd><RangeValue value={record(check.release_scope)[key]} /></dd></div>)}</dl>}<p>本检查固定例外：{check.exception === null ? "未提供固定例外引用（原值为空）" : <FixedReference value={check.exception} />}</p></details><Sources value={check.sources} label="本检查固定依据" /></div>) : <p className={styles.context}>本次检查未返回具体检查项。</p>}<h5>阻塞（原列表）</h5><Messages value={value.blocked} empty="本列表未列阻塞。" /><h5>未知（原列表）</h5><Messages value={value.unknown} empty="本列表未列未知。" /><h5>固定条件决定</h5>{value.conditions.length ? <ul>{value.conditions.map(ref => <li key={ref.id}><FixedReference value={ref} /></li>)}</ul> : <p className={styles.context}>本次检查未列条件决定。</p>}</section>;
}

function Messages({ value, empty }: { value: string[]; empty: string }) { return value.length ? <ul>{value.map((message, index) => <li key={index} className={styles.prose}>{message}</li>)}</ul> : <p className={styles.context}>{empty}</p>; }

function Decision({ value }: { value: Row }) {
  const body = record(value.decision), assessment = record(body.assessment) as ReleaseAssessment;
  return <article className={styles.decision} aria-label={`专业决定 ${original(value.id)}`}><p className={styles.title}>已登记决定 · v{original(value.revision)}</p><p className={styles.context}>{applicability(value.applicability)}</p><ContentScope value={body} /><dl className={styles.facts}><div><dt>具名签署人标识</dt><dd><ul>{rows(body.signers).map((signer, index) => <li key={index}>{original(signer)}</li>)}</ul></dd></div><div><dt>明确期限</dt><dd>{body.expiry === null ? "未另设期限（原值为空）" : <time dateTime={original(body.expiry)}>{original(body.expiry)}</time>}</dd></div><div><dt>决定材料准备时点</dt><dd><time dateTime={original(body.prepared_at)}>{original(body.prepared_at)}</time></dd></div><div><dt>原回执</dt><dd>{original(value.receipt_id)}</dd></div></dl><p className={styles.context}>准备时点不作为签署时点；本读集未提供签署时间或人员姓名。</p><Limits value={body.limits} label="本决定固定限制" /><details className={styles.details}><summary>决定内保存的检查与固定身份</summary><Assessment value={assessment} label={`${names[assessment.discipline]}决定内固定检查`} /><dl className={styles.identities}><div><dt>决定身份</dt><dd>{original(value.id)} · v{original(value.revision)}</dd></div><div><dt>对应固定包</dt><dd><FixedReference value={body.package} /></dd></div><div><dt>证据内容指纹</dt><dd>{original(body.evidence_digest)}</dd></div><div><dt>固定包内容指纹</dt><dd>{original(body.package_sha256)}</dd></div><div><dt>政策版本</dt><dd>{body.policy_version === null ? "未提供" : original(body.policy_version)}</dd></div></dl></details></article>;
}

function Limits({ value, label }: { value: unknown; label: string }) {
  return <details className={styles.details}><summary>{label}（{rows(value).length} 条）</summary>{rows(value).length ? <ul>{rows(value).map((item, index) => { const limit = record(item); return <li key={index}><p className={styles.prose}>{original(limit.text)}</p><Sources value={limit.sources} label="本限制固定依据" /></li>; })}</ul> : <p>本记录未列限制文字，不表示范围无限或全部满足。</p>}</details>;
}

function Sources({ value, label }: { value: unknown; label: string }) {
  return <details className={styles.details}><summary>{label}（{rows(value).length} 条）</summary><ul>{rows(value).map((item, index) => { const source = record(item); return <li key={index}><FixedReference value={source} /><small>{objectNames[original(source.kind)] ?? original(source.kind)} · 原定位 {original(source.position)}</small></li>; })}</ul></details>;
}
