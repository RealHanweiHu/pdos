"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { readProjectExternalHandoff, readProjectExternalHandoffReceipts, readProjectExternalHandoffs } from "@/lib/project-external-handoffs";
import type { ProjectExternalHandoffApi, ProjectExternalHandoffList, ProjectExternalHandoffReceipts, ProjectExternalHandoffScope } from "@/lib/project-external-handoffs";
import type { HandoffDetail, HandoffHeader, HandoffHistory, HandoffReading } from "@/lib/external-handoffs";
import styles from "./project-external-handoffs.module.css";

type Props = ProjectExternalHandoffScope & { api: ProjectExternalHandoffApi; readVersion: number };
type Page = { cursor?: string };
type ReceiptRequest = { api: ProjectExternalHandoffApi; page: Page; detail: HandoffDetail; before?: number; previous: HandoffHistory[] };
type Row = Record<string, unknown>;
const record = (value: unknown): Row => value !== null && typeof value === "object" && !Array.isArray(value) ? value as Row : {};
const rows = (value: unknown): unknown[] => Array.isArray(value) ? value : [];
const original = (value: unknown) => value === null ? "未知（原值为空）" : typeof value === "string" || typeof value === "number" ? String(value) : "未提供";
const originalBoolean = (value: unknown) => value === true ? "是（true）" : value === false ? "否（false）" : original(value);
const stageNames = { sent: "发送", accepted: "接收", effective: "实际生效" };
const stateNames = { not_recorded: "未记录", succeeded: "本范围记录成功", partial: "部分范围", unknown: "结果未知", rejected: "已拒绝", failed: "已失败", conflict: "事实冲突" };
const statusNames = { authorized: "已登记授权", sent: "已记录发送", acknowledged: "已记录接收", reconciled: "已对账实际生效" };
const mismatches: Record<string, string> = { DESTINATION_MISMATCH: "回执收件方与授权不一致", EXTERNAL_ID_MISMATCH: "回执外部编号与授权不一致", MANIFEST_MISMATCH: "回执文件指纹与授权不一致", RECEIVED_SCOPE_MISMATCH: "回执范围与授权不一致" };
const kindNames: Record<string, string> = { definition: "产品定义", engineering_configuration: "工程配置", process_revision: "制造配置", part: "零件", bom_revision: "BOM", artifact: "原件", work_instruction: "作业指导书", control_plan: "控制计划" };

export function ProjectExternalHandoffs(props: Props) {
  return <ScopedHandoffs key={JSON.stringify([props.principalId, props.categoryId, props.productId, props.projectId, props.readVersion])} {...props} />;
}

function ScopedHandoffs({ api, categoryId, productId, projectId, principalId }: Props) {
  const [page, setPage] = useState<Page>({});
  const [reading, setReading] = useState<{ api: ProjectExternalHandoffApi; page: Page; data: ProjectExternalHandoffList | null; error: string } | null>(null);
  const [selection, setSelection] = useState<{ api: ProjectExternalHandoffApi; page: Page; id: string; revision: number } | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [detail, setDetail] = useState<{ api: ProjectExternalHandoffApi; page: Page; selected: HandoffHeader; attempt: number; data: HandoffDetail | null; error: string } | null>(null);
  const [receiptRequest, setReceiptRequest] = useState<ReceiptRequest | null>(null);
  const [receipts, setReceipts] = useState<{ request: ReceiptRequest; data: ProjectExternalHandoffReceipts | null; error: string } | null>(null);
  const current = reading?.api === api && reading.page === page ? reading : null;
  const data = current?.data ?? null, error = current?.error ?? "";
  const selected = selection?.api === api && selection.page === page ? data?.items.find(item => item.id === selection.id && item.revision === selection.revision) : undefined;
  const currentDetail = detail?.api === api && detail.page === page && detail.selected === selected && detail.attempt === attempt ? detail : null;
  const fixed = currentDetail?.data ?? null, detailError = currentDetail?.error ?? "";
  const request = receiptRequest?.api === api && receiptRequest.page === page && receiptRequest.detail === fixed ? receiptRequest : null;
  const currentReceipts = receipts?.request === request ? receipts : null;
  const history = currentReceipts?.data ?? null, historyError = currentReceipts?.error ?? "";
  const live = useRef<{ api: ProjectExternalHandoffApi; page: Page; selected: HandoffHeader | undefined; attempt: number; fixed: HandoffDetail | null; request: ReceiptRequest | null } | null>(null);
  useLayoutEffect(() => {
    const input = { api, page, selected, attempt, fixed, request };
    live.current = input;
    return () => { if (live.current === input) live.current = null; };
  }, [api, page, selected, attempt, fixed, request]);
  useEffect(() => {
    let active = true;
    const isCurrent = () => active && live.current?.api === api && live.current.page === page;
    void readProjectExternalHandoffs(api, { categoryId, productId, projectId, principalId }, page.cursor).then(value => {
      if (isCurrent()) setReading({ api, page, data: value, error: "" });
    }).catch(failure => {
      if (isCurrent()) setReading({ api, page, data: null, error: failure instanceof Error ? failure.message : "本页外部交接未完整取得。" });
    });
    return () => { active = false; };
  }, [api, categoryId, productId, projectId, principalId, page]);
  useEffect(() => {
    if (!selected) return;
    let active = true;
    const isCurrent = () => active && live.current?.api === api && live.current.page === page && live.current.selected === selected && live.current.attempt === attempt;
    void readProjectExternalHandoff(api, { categoryId, productId, projectId, principalId }, { id: selected.id, revision: selected.revision }).then(value => {
      if (isCurrent()) setDetail({ api, page, selected, attempt, data: value, error: "" });
    }).catch(failure => {
      if (!isCurrent()) return;
      const message = failure instanceof Error ? failure.message : "所选外部交接未完整取得。";
      setDetail({ api, page, selected, attempt, data: null, error: message });
      if ((failure as Error & { status?: number })?.status !== 503) setReading({ api, page, data: null, error: `所选移交的权限或固定版本无法核对，已隐藏旧资料：${message}` });
    });
    return () => { active = false; };
  }, [api, categoryId, productId, projectId, principalId, page, selected, attempt]);
  useEffect(() => {
    if (!request || !fixed) return;
    let active = true;
    const isCurrent = () => active && live.current?.api === api && live.current.page === page && live.current.fixed === fixed && live.current.request === request;
    void readProjectExternalHandoffReceipts(api, { categoryId, productId, projectId, principalId }, fixed, request.before).then(value => {
      if (!isCurrent()) return;
      const all = [...request.previous, ...value.items];
      if (new Set(all.map(item => item.id)).size !== all.length || new Set(all.map(item => item.sequence)).size !== all.length) throw new Error("原回执分页出现重复身份或序号，请重新读取所选移交，不能拼接不完整历史。");
      setReceipts({ request, data: { ...value, items: all }, error: "" });
    }).catch(failure => {
      if (!isCurrent()) return;
      const message = failure instanceof Error ? failure.message : "同水位原回执未完整取得。";
      setReceipts({ request, data: null, error: message });
      if ((failure as Error & { status?: number })?.status !== 503) setReading({ api, page, data: null, error: `原回执权限、版本或水位变化，已隐藏旧资料，请重新选择并读取：${message}` });
    });
    return () => { active = false; };
  }, [api, categoryId, productId, projectId, principalId, page, fixed, request]);
  const refresh = () => setPage({ cursor: page.cursor });
  const startHistory = () => { if (fixed) setReceiptRequest({ api, page, detail: fixed, previous: [] }); };
  return <section className={styles.panel} aria-label="本项目外部交接与原回执">
    <header className={styles.heading}><h2>外部交接与原回执</h2><Button type="button" size="xs" variant="outline" onClick={refresh}>刷新本页外部交接</Button></header>
    {error ? <div className={styles.notice} role="alert"><p>外部交接暂不可读：{error}</p><div className={styles.actions}><Button type="button" size="xs" variant="outline" onClick={refresh}>重新读取本页外部交接</Button>{page.cursor !== undefined && <Button type="button" size="xs" variant="outline" onClick={() => setPage({})}>回首页</Button>}</div></div> : !data ? <p className={styles.notice} role="status">正在读取本项目外部交接…</p> : <>
      <p className={styles.note}>本页 {data.items.length} 条可读交接，非项目总数。明确选择后读取固定授权和原发送意图。</p>
      {data.items.length ? <div className={styles.scroll} role="region" aria-label="本页可选外部交接" tabIndex={0}><table className={styles.table}><thead><tr><th>用途 / 固定包</th><th>服务器状态</th><th>原回执水位</th><th>查看</th></tr></thead><tbody>{data.items.map(item => <tr key={item.id} data-selected={item === selected}><td><strong>{item.purpose}</strong><small>固定包 <FixedReference value={item.package} /></small></td><td>{statusNames[item.reading.status]}</td><td>{item.as_of.receipt_count} 条 · epoch {item.as_of.epoch}</td><td><Button type="button" size="xs" variant={selected === item ? "secondary" : "outline"} aria-label={`读取外部交接 ${item.id}`} aria-pressed={selected === item} onClick={() => setSelection({ api, page, id: item.id, revision: item.revision })}>读取固定交接</Button></td></tr>)}</tbody></table></div> : <p className={styles.notice}>本页没有可展示的外部交接，不据此判断整个项目没有交接或回执。</p>}
      <div className={styles.pagination}><Button type="button" size="xs" variant="outline" disabled={page.cursor === undefined} onClick={() => setPage({})}>回首页</Button><Button type="button" size="xs" variant="outline" disabled={data.nextCursor === null} onClick={() => { if (data.nextCursor) setPage({ cursor: data.nextCursor }); }}>下一页外部交接</Button><span>{data.nextCursor ? "仍有下一页，未汇总为全部记录。" : "本页未提供下一页位置。"}</span></div>
      {!selected && data.items.length > 0 && <p className={styles.notice}>请选择固定交接，分别核对发送、接收与实际生效。</p>}
      {selected && <section className={styles.selected} aria-label="已选外部交接详情"><header className={styles.heading}><h3>固定授权、原意图与阶段事实</h3><Button type="button" size="xs" variant="outline" onClick={() => setAttempt(value => value + 1)}>刷新已选外部交接</Button></header>{detailError ? <div className={styles.notice} role="alert"><p>固定交接暂不可读：{detailError}</p><Button type="button" size="xs" variant="outline" onClick={() => setAttempt(value => value + 1)}>重新读取已选外部交接</Button></div> : !fixed ? <p className={styles.notice} role="status">正在核对所选交接的固定版本与回执水位…</p> : <div className={styles.content}><ProjectExternalHandoffDetail detail={fixed} /><section className={styles.history} aria-label="原回执历史"><h4>原回执历史</h4><p className={styles.context}>本水位服务器已登记 {fixed.as_of.receipt_count} 条；原回执按各自发生、收到、范围及对账关系保留。</p>{!request ? <Button type="button" size="xs" variant="outline" onClick={startHistory}>展开原回执历史</Button> : <><div className={styles.actions}><Button type="button" size="xs" variant="outline" onClick={() => setReceiptRequest(null)}>收起原回执历史</Button><Button type="button" size="xs" variant="outline" onClick={startHistory}>从最新原回执重新读取</Button></div>{historyError ? <div className={styles.notice} role="alert"><p>同水位原回执暂不可读：{historyError}</p><Button type="button" size="xs" variant="outline" onClick={() => setReceiptRequest({ ...request })}>重新读取本次原回执页</Button></div> : !history ? <p className={styles.context} role="status">正在读取与所选交接水位一致的原回执…</p> : <><p className={styles.context}>已读取 {history.items.length} 条原回执，水位 epoch {history.asOf.epoch}；仅展示已返回的历史。</p>{history.items.length ? history.items.map(item => <ProjectExternalHandoffReceipt key={item.id} value={item} />) : <p className={styles.context}>本回执页未返回记录，不据此重判三个阶段状态。</p>}{history.beforeSequence !== null ? <Button type="button" size="xs" variant="outline" onClick={() => setReceiptRequest({ api, page, detail: fixed, before: history.beforeSequence!, previous: history.items })}>读取更早原回执</Button> : <p className={styles.context}>本页未提供更早原回执位置。</p>}</>}</>}</section></div>}</section>}
      <p className={styles.foot}>授权和原意图不表示已发送、已接收或已生效。三个阶段按服务器原投影分别展示；此面板仅供读取，不进行网络发送或资格判定。</p>
    </>}
  </section>;
}

export function ProjectExternalHandoffDetail({ detail }: { detail: HandoffDetail }) {
  const authorization = detail.authorization, declaration = record(authorization.declaration), packet = detail.intent.packet;
  return <><p className={styles.title}>{detail.purpose} · {statusNames[detail.reading.status]}</p><p className={styles.context}>{detail.applicability === "current" ? "当前直接适用依据可核" : "适用依据需重核，历史授权与回执保留"}</p><Packet value={declaration} />
    <details className={styles.details}><summary>授权、原意图与固定指纹</summary><dl className={styles.identities}><div><dt>交接授权</dt><dd><FixedReference value={detail} /></dd></div><div><dt>原发送意图</dt><dd><FixedReference value={detail.intent} /></dd></div><div><dt>授权具名人标识</dt><dd><ul>{rows(authorization.signers).map((signer, index) => <li key={index}>{original(signer)}</li>)}</ul></dd></div><div><dt>授权材料准备原时点</dt><dd>{original(authorization.prepared_at)}</dd></div><div><dt>授权记录保存原时点</dt><dd>{original(detail.created_at)}</dd></div><div><dt>授权登记回执</dt><dd>{detail.receipt_id}</dd></div><div><dt>固定包指纹</dt><dd>{original(authorization.package_sha256)}</dd></div><div><dt>原意图文件指纹</dt><dd>{original(packet.manifest_sha256)}</dd></div><div><dt>原意图映射指纹</dt><dd>{original(packet.mappings_sha256)}</dd></div><div><dt>原意图内容指纹</dt><dd>{original(packet.content_sha256)}</dd></div><div><dt>当前投影水位</dt><dd>{detail.as_of.id} · epoch {detail.as_of.epoch}</dd></div><div><dt>当前投影指纹</dt><dd>{detail.as_of.projection_sha256}</dd></div></dl><p>材料准备时点不是外部发送、接收或生效时点。</p><SavedAuthority value={detail.authority} authorization={authorization} /><Limits value={authorization.limits} /><Sources value={authorization.sources} label="授权固定来源" /></details>
    <div className={styles.stages}>{(["sent", "accepted", "effective"] as const).map(stage => <Stage key={stage} value={detail.reading[stage]} />)}</div>
    <Flags reading={detail.reading} />
  </>;
}

function Packet({ value }: { value: Row }) {
  const configuration = record(value.subject_config), destination = record(value.destination);
  return <><dl className={styles.facts}>{([ ["package", "固定发布包"], ["engineering_decision", "固定工程决定"], ["manufacturing_decision", "固定制造决定"] ] as const).map(([key, label]) => <div key={key}><dt>{label}</dt><dd><FixedReference value={value[key]} /></dd></div>)}{([ ["definition", "固定产品定义"], ["engineering_configuration", "固定工程配置"], ["manufacturing_configuration", "固定制造配置"] ] as const).map(([key, label]) => <div key={key}><dt>{label}</dt><dd><FixedReference value={configuration[key]} /></dd></div>)}<div><dt>目标外部系统</dt><dd>{original(destination.system)}</dd></div><div><dt>固定收件方标识</dt><dd>{original(destination.recipient_id)}</dd></div><div><dt>固定外部编号</dt><dd>{original(value.external_id)}</dd></div></dl><ScopeRange value={value.release_scope} />
    <details className={styles.details}><summary>固定文件清单（{rows(value.manifest).length} 项）</summary>{rows(value.manifest).length ? <div className={styles.scroll} role="region" aria-label="固定文件 manifest" tabIndex={0}><table className={styles.table}><thead><tr><th>逻辑名称 / 固定原件</th><th>外部编号 / 版本</th><th>内容指纹（SHA-256）</th><th>依据</th></tr></thead><tbody>{rows(value.manifest).map((item, index) => { const file = record(item); return <tr key={index}><td>{original(file.logical_name)}<small><FixedReference value={file.artifact} /></small></td><td>{original(file.external_number)}<small>{original(file.external_version)}</small></td><td>{original(file.content_sha256)}</td><td><Sources value={file.sources} label="文件固定依据" /></td></tr>; })}</tbody></table></div> : <p>本授权文件列表为空，不推断移交资料已齐备。</p>}</details>
    <details className={styles.details}><summary>固定编号与版本映射（{rows(value.mappings).length} 项）</summary>{rows(value.mappings).length ? <div className={styles.scroll} role="region" aria-label="固定编号版本映射" tabIndex={0}><table className={styles.table}><thead><tr><th>固定对象</th><th>外部编号</th><th>外部版本</th><th>依据</th></tr></thead><tbody>{rows(value.mappings).map((item, index) => { const mapping = record(item), ref = record(mapping.ref); return <tr key={index}><td>{kindNames[original(ref.kind)] ?? original(ref.kind)}<small><FixedReference value={ref} /></small></td><td>{original(mapping.external_number)}</td><td>{original(mapping.external_version)}</td><td><Sources value={mapping.sources} label="映射固定依据" /></td></tr>; })}</tbody></table></div> : <p>本授权映射列表为空，不代表必需映射已齐备。</p>}</details></>;
}

function Stage({ value }: { value: HandoffReading["sent"] }) { return <section className={styles.stage} aria-label={`${stageNames[value.stage]}服务器阶段`}><h4>{stageNames[value.stage]}</h4><p className={styles.state} data-state={value.state}>{stateNames[value.state]}</p><h5>服务器已覆盖范围</h5>{value.covered_scopes.length ? value.covered_scopes.map((scope, index) => <ScopeRange key={index} value={scope} />) : <p className={styles.context}>本阶段未返回覆盖范围。</p>}<details className={styles.details}><summary>本阶段当前原回执引用</summary><ul>{value.active.map(ref => <li key={ref.id}><FixedReference value={ref} /></li>)}</ul></details><Diagnostics values={value.mismatches} /></section>; }
function Flags({ reading }: { reading: HandoffReading }) { return <div className={styles.flags}>{reading.delivery_unknown && <p>服务器记录发送结果未知，须核对原意图与原回执。</p>}{reading.rejected && <p>服务器记录存在未对账拒绝。</p>}{reading.failed && <p>服务器记录存在未对账失败。</p>}{reading.conflict && <p>服务器记录阶段事实冲突，不能据此认定完整交付。</p>}</div>; }

export function ProjectExternalHandoffReceipt({ value }: { value: HandoffHistory }) {
  const { original: receipt, issuer } = value, destination = record(receipt.destination);
  return <article className={styles.receipt} aria-label={`原回执 ${value.id}`}><h5>序号 {value.sequence} · {stageNames[receipt.stage as keyof typeof stageNames] ?? original(receipt.stage)} · {stateNames[receipt.outcome as keyof typeof stateNames] ?? original(receipt.outcome)}</h5><dl className={styles.facts}><div><dt>外部回执编号</dt><dd>{original(receipt.external_receipt_id)}</dd></div><div><dt>实际发生原时点</dt><dd>{original(receipt.occurred_at)}</dd></div><div><dt>系统收到原时点</dt><dd>{value.received_at}</dd></div><div><dt>原回执收件方</dt><dd>{original(destination.system)} / {original(destination.recipient_id)}</dd></div><div><dt>原回执外部编号</dt><dd>{original(receipt.external_id)}</dd></div><div><dt>显式对账原事实</dt><dd>{receipt.reconciles === null ? "原值为空，未引用对账前驱" : <FixedReference value={receipt.reconciles} />}</dd></div></dl><ScopeRange value={receipt.release_scope} /><Diagnostics values={value.mismatches} /><details className={styles.details}><summary>原回执、发行者、来源与指纹</summary><dl className={styles.identities}><div><dt>原事实标识</dt><dd>{value.id} · v{value.revision}</dd></div><div><dt>固定授权引用</dt><dd><FixedReference value={receipt.handoff} /></dd></div><div><dt>固定原意图引用</dt><dd><FixedReference value={receipt.intent} /></dd></div><div><dt>登记回执</dt><dd>{value.receipt_id}</dd></div><div><dt>原文件清单指纹</dt><dd>{original(receipt.manifest_sha256)}</dd></div><div><dt>发行者登记键 / 版本</dt><dd>{original(issuer.key)} / {original(issuer.version)}</dd></div><div><dt>发行者水位</dt><dd>{original(issuer.epoch)}</dd></div><div><dt>发行系统 / 主体标识</dt><dd>{original(issuer.system)} / {original(issuer.subject_id)}</dd></div><div><dt>原发行证明指纹</dt><dd>{original(issuer.proof_sha256)}</dd></div></dl><Sources value={[value.source]} label="本原回执固定来源" /></details></article>;
}

function ScopeRange({ value }: { value: unknown }) { const scope = record(value); return <dl className={styles.facts}>{([ ["quantity", "数量原值"], ["unit", "单位"], ["site", "场地"], ["lots", "批次"], ["lines", "产线"], ["regions", "地区"] ] as const).map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{scope[key] === null || scope[key] === undefined ? "未知 / 未覆盖" : Array.isArray(scope[key]) ? scope[key].length ? <ul>{scope[key].map((item, index) => <li key={index}>{typeof item === "string" ? item : <FixedReference value={item} />}</li>)}</ul> : "明确为空，不代表全部" : original(scope[key])}</dd></div>)}</dl>; }
function FixedReference({ value }: { value: unknown }) { const ref = record(value); return typeof ref.id === "string" && typeof ref.revision === "number" ? <>{ref.id} · v{ref.revision}</> : <>固定引用未提供</>; }
function Diagnostics({ values }: { values: string[] }) { return values.length ? <ul className={styles.diagnostics}>{values.map((code, index) => <li key={index}>{mismatches[code] ?? code}{mismatches[code] && <small>{code}</small>}</li>)}</ul> : null; }
function OriginalList({ value }: { value: unknown }) { return Array.isArray(value) ? value.length ? <ul>{value.map((item, index) => <li key={index}>{original(item)}</li>)}</ul> : <>原列表为空</> : <>{original(value)}</>; }
function SavedAuthority({ value, authorization }: { value: Row; authorization: Row }) {
  const scope = record(value.scope);
  return <details className={styles.details}><summary>保存时授权依据与材料状态</summary><p>以下是原授权依据快照与保存时材料状态，不代表当前资格或当前成熟度；未重新判定有效期。</p><dl className={styles.identities}><div><dt>保存时材料状态原值</dt><dd>{original(authorization.state)}</dd></div><div><dt>保存时未知项原值</dt><dd><OriginalList value={authorization.unknown} /></dd></div><div><dt>保存时阻断项原值</dt><dd><OriginalList value={authorization.blocked} /></dd></div><div><dt>原依据人员标识</dt><dd>{original(value.subject_id)}</dd></div><div><dt>原依据操作</dt><dd>{original(value.operation)}</dd></div><div><dt>原依据精确用途</dt><dd>{original(value.purpose)}</dd></div>{([ ["tenant_id", "原依据租户标识"], ["product_id", "原依据型号标识"], ["project_id", "原依据项目标识"] ] as const).map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{original(scope[key])}</dd></div>)}<div><dt>原授权判定 authorized</dt><dd>{originalBoolean(value.authorized)}</dd></div><div><dt>原资格判定 qualified</dt><dd>{originalBoolean(value.qualified)}</dd></div><div><dt>原职责角色</dt><dd><OriginalList value={value.roles} /></dd></div><div><dt>原依据原因码</dt><dd><OriginalList value={value.reason_codes} /></dd></div><div><dt>原依据有效期截至</dt><dd>{original(value.valid_until)}</dd></div><div><dt>原依据是否合成</dt><dd>{originalBoolean(value.synthetic)}</dd></div><div><dt>原依据事实指纹</dt><dd>{original(value.facts_revision)}</dd></div></dl><details className={styles.details}><summary>保存时专业事实引用（{rows(value.fact_refs).length} 条）</summary>{rows(value.fact_refs).map((item, index) => { const fact = record(item); return <dl key={index} className={styles.identities}><div><dt>固定事实引用</dt><dd><FixedReference value={fact} /></dd></div><div><dt>事实种类 / 角色 / 性质</dt><dd>{original(fact.kind)} / {original(fact.role)} / {original(fact.nature)}</dd></div><div><dt>保存状态原值</dt><dd>{original(fact.state)}</dd></div><div><dt>原发行者键 / 版本</dt><dd>{original(fact.issuer_key)} / {original(fact.issuer_version)}</dd></div><div><dt>原事实 / 发行者水位</dt><dd>{original(fact.epoch)} / {original(fact.issuer_epoch)}</dd></div><div><dt>原事实有效起止</dt><dd>{original(fact.valid_from)} / {original(fact.valid_until)}</dd></div><div><dt>原覆盖操作 / 用途</dt><dd><OriginalList value={fact.operations} /><OriginalList value={fact.purposes} /></dd></div><div><dt>原事实内容指纹</dt><dd>{original(fact.fact_sha256)}</dd></div></dl>; })}</details></details>;
}
function Sources({ value, label }: { value: unknown; label: string }) { return <details className={styles.details}><summary>{label}（{rows(value).length} 条）</summary><ul>{rows(value).map((item, index) => { const source = record(item); return <li key={index}><FixedReference value={source} /><small>来源种类：{original(source.kind)}</small><small>原定位：{original(source.position)}</small></li>; })}</ul></details>; }
function Limits({ value }: { value: unknown }) { return <details className={styles.details}><summary>原授权固定限制（{rows(value).length} 条）</summary><ul>{rows(value).map((item, index) => { const limit = record(item); return <li key={index}><p className={styles.prose}>{original(limit.text)}</p><Sources value={limit.sources} label="限制固定依据" /></li>; })}</ul></details>; }
