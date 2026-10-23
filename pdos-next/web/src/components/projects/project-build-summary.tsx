"use client";

import { useCallback, useEffect, useState } from "react";
import { ArrowRight } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { readBuildTestSummary, readProjectBuilds, type ProjectBuildApi, type ProjectBuildRecord, type ProjectBuildScope } from "@/lib/project-build-summary";
import { ProjectBuildOutput } from "./project-build-output";
import { ProjectBuildReadiness } from "./project-build-readiness";
import styles from "./project-build-summary.module.css";

type Props = ProjectBuildScope & { api: ProjectBuildApi; principalId: string; readVersion: number };
type BuildReading = Awaited<ReturnType<typeof readProjectBuilds>>;
type TestReading = Awaited<ReturnType<typeof readBuildTestSummary>>;
const typeNames: Record<string, string> = { prototype: "原型验证", tool_trial: "试模 / 工装试验", pilot: "试产验证" };
const runStates: Record<string, string> = { planned: "已固定测试计划", running: "已登记开测", results_pending: "待结果复核", reviewed: "已具名复核", disposed: "已具名处置" };
const resultNames: Record<string, string> = { pending: "尚未形成判定", pass: "固定范围数值判定通过", fail: "固定范围数值判定未通过", indeterminate: "缺项，不能确定", invalid: "已明确记录为无效" };
const print = (value: unknown) => value === null || value === undefined || value === "" ? "未登记" : typeof value === "object" ? JSON.stringify(value) : String(value);
const sourceState = (value: unknown) => value === "current" ? "来源当前可读" : value === "needs_recheck" ? "来源需重核" : "来源状态未提供";
function workHref(scope: ProjectBuildScope, buildId: string, view: string, task: string) {
  return `/?${new URLSearchParams({ area: "category", category: scope.categoryId, bench: "projects", product: scope.productId, project: scope.projectId, build: buildId, view, task })}`;
}
export function ProjectBuildSummary(props: Props) {
  return <ScopedBuildSummary key={JSON.stringify([props.principalId, props.categoryId, props.productId, props.projectId, props.readVersion])} {...props}/>;
}
function ScopedBuildSummary({ api, categoryId, productId, projectId }: Props) {
  const [attempt, setAttempt] = useState(0);
  const [reading, setReading] = useState<{ api: ProjectBuildApi; attempt: number; data: BuildReading | null; error: string } | null>(null);
  const [selection, setSelection] = useState<{ api: ProjectBuildApi; attempt: number; id: string } | null>(null);
  const current = reading?.api === api && reading.attempt === attempt ? reading : null;
  const data = current?.data ?? null, error = current?.error ?? "";
  const selected = selection?.api === api && selection.attempt === attempt ? data?.items.find(item => item.id === selection.id) : undefined;
  const rejectAccess = useCallback((message: string) => setReading({ api, attempt, data: null, error: message }), [api, attempt]);
  const scope = { categoryId, productId, projectId };
  useEffect(() => {
    let active = true;
    void readProjectBuilds(api, { categoryId, productId, projectId }).then(value => { if (active) setReading({ api, attempt, data: value, error: "" }); })
      .catch(failure => { if (active) setReading({ api, attempt, data: null, error: (failure as Error).message }); });
    return () => { active = false; };
  }, [api, categoryId, productId, projectId, attempt]);
  return <div className={`${styles.content} project-canvas`}>
    <section className={styles.panel} aria-label="本项目 Builds">
      <header className={styles.heading}><h2>本项目 Builds</h2><Button type="button" variant="outline" size="xs" onClick={() => setAttempt(value => value + 1)}>刷新本项目轮次</Button></header>
      {error ? <div className={styles.notice} role="alert"><p>项目轮次暂不可读：{error}</p><Button type="button" variant="outline" size="xs" onClick={() => setAttempt(value => value + 1)}>重新读取项目轮次</Button></div> : !data ? <p className={styles.notice} role="status">正在读取本项目轮次…</p> : <>
        <p className={styles.note}>已读取 {data.items.length} 条可读轮次。{data.unavailableCount > 0 && ` ${data.unavailableCount} 条记录暂不可读。`}{data.hasMore && " 读集尚未完整。"}请选择需要核对的轮次。</p>
        {data.items.length > 0 ? <div className={styles.scroll}><table className={styles.table}><thead><tr><th>Build / 目的</th><th>固定工程配置</th><th>固定制造配置</th><th>计划数量</th><th>计划窗口</th><th>记录状态</th><th>办理</th></tr></thead><tbody>{data.items.map(item => <tr key={item.id} data-selected={selected?.id === item.id}>
          <td><button type="button" className={styles.name} aria-label={`查看 ${item.name} 轮次摘要`} aria-pressed={selected?.id === item.id} onClick={() => setSelection({ api, attempt, id: item.id })}>{item.name}</button><small>{typeNames[item.type] ?? item.type} · v{item.revision}</small><small>{item.purpose}</small></td>
          <td>{item.engineering_configuration.name}<small>固定 v{item.engineering_configuration.revision}</small></td><td>{item.manufacturing_configuration.name}<small>固定 v{item.manufacturing_configuration.revision}</small></td>
          <td className={styles.mono}>{item.planned_quantity} {item.unit}</td><td><span>{print(item.planned_start)}</span><small>至 {print(item.planned_end)}</small></td><td>{item.status === "planned" ? "计划已登记" : item.status}<small>{item.source_status === "current" ? "来源当前可读" : "来源需重核"}</small></td>
          <td><a className={styles.link} href={workHref(scope, item.id, "builds", "prepare")}>进入办理<ArrowRight size={12} aria-hidden="true"/></a></td>
        </tr>)}</tbody></table></div> : <p className={styles.notice}>{data.unavailableCount > 0 || data.hasMore ? "当前没有可展示的轮次，读取范围尚不完整。" : "当前可读范围内尚无本项目 Build 记录。"}</p>}
        <p className={styles.note}>计划与实际执行分别记录；计划窗口不是承诺。选中轮次后可读取实际产出与样件登记；执行优先级尚未汇入。</p>
      </>}
    </section>
    {selected && <SelectedBuild key={`${selected.id}:${selected.revision}`} api={api} scope={scope} build={selected} builds={data!.items} onAccessRejected={rejectAccess}/>}
  </div>;
}
function SelectedBuild({ api, scope, build, builds, onAccessRejected }: { api: ProjectBuildApi; scope: ProjectBuildScope; build: ProjectBuildRecord; builds: ProjectBuildRecord[]; onAccessRejected: (message: string) => void }) {
  const [attempt, setAttempt] = useState(0);
  const [reading, setReading] = useState<{ api: ProjectBuildApi; attempt: number; data: TestReading | null; error: string } | null>(null);
  const current = reading?.api === api && reading.attempt === attempt ? reading : null;
  const data = current?.data ?? null, error = current?.error ?? "";
  const { categoryId, productId, projectId } = scope;
  useEffect(() => {
    let active = true;
    void readBuildTestSummary(api, { categoryId, productId, projectId }, build).then(value => { if (active) setReading({ api, attempt, data: value, error: "" }); })
      .catch(failure => { if (active) {
        const failed = failure as Error & { status?: number };
        setReading({ api, attempt, data: null, error: failed.message });
        if (failed.status !== 503) onAccessRejected(`当前轮次的权限、来源或固定版本无法核对，已隐藏旧轮次资料：${failed.message}`);
      } });
    return () => { active = false; };
  }, [api, categoryId, productId, projectId, build, attempt, onAccessRejected]);
  const fixed = data?.build, previous = fixed?.previous_build_id ? builds.find(item => item.id === fixed.previous_build_id) : undefined;
  return <section className={styles.panel} aria-label="已选轮次事实摘要">
    <header className={styles.heading}><h3>已选轮次事实摘要</h3><Button type="button" size="xs" variant="outline" onClick={() => setAttempt(value => value + 1)}>刷新已选轮次摘要</Button></header>
    {error ? <div className={styles.notice} role="alert"><p>已选轮次与测试摘要暂不可读：{error}</p><Button type="button" size="xs" variant="outline" onClick={() => setAttempt(value => value + 1)}>重新读取已选轮次摘要</Button></div> : !data || !fixed ? <p className={styles.notice} role="status">正在核对已选轮次与当前测试记录…</p> : <>
      <dl className={styles.facts}><div><dt>Build</dt><dd>{fixed.name} · 固定 v{fixed.revision}</dd></div><div><dt>目的</dt><dd>{fixed.purpose}</dd></div><div><dt>计划数量</dt><dd className={styles.mono}>{fixed.planned_quantity} {fixed.unit}</dd></div><div><dt>前轮</dt><dd>{fixed.previous_build_id ? previous?.name ?? "已登记前轮，名称未取得" : "未登记前轮"}</dd></div><div><dt>固定工程配置</dt><dd>{fixed.engineering_configuration.name} · v{fixed.engineering_configuration.revision}</dd></div><div><dt>固定制造配置</dt><dd>{fixed.manufacturing_configuration.name} · v{fixed.manufacturing_configuration.revision}</dd></div><div className={styles.full}><dt>验证目标</dt><dd>{print(fixed.verification_objectives)}</dd></div><div className={styles.full}><dt>处置要求</dt><dd>{print(fixed.disposition_plan)}</dd></div></dl>
      <details className={styles.details}><summary>固定双配置、版本与来源状态</summary><p>本轮按下列固定引用核对。</p><dl className={styles.identityFacts}><div><dt>Build 标识</dt><dd>{fixed.id} · v{fixed.revision}</dd></div><div><dt>原固定项目版本</dt><dd>v{fixed.project_revision}</dd></div>{[["工程配置", fixed.engineering_configuration], ["制造配置", fixed.manufacturing_configuration]].map(([label, value]) => { const config = value as ProjectBuildRecord["engineering_configuration"]; return <div key={String(label)}><dt>{String(label)}</dt><dd>{config.name} · 固定 v{config.revision}<small>{config.id} · {sourceState(config.source_status)}</small></dd></div>; })}<div><dt>前轮标识</dt><dd>{print(fixed.previous_build_id)}</dd></div></dl></details>
      <div className={styles.actions}><a className={styles.link} href={workHref(scope, fixed.id, "builds", "prepare")}>办理本轮 Build<ArrowRight size={12}/></a><a className={styles.link} href={workHref(scope, fixed.id, "verification", "results")}>测试结果与处置<ArrowRight size={12}/></a><a className={styles.link} href={workHref(scope, fixed.id, "verification", "handoff")}>交样与接收<ArrowRight size={12}/></a></div>
      <p className={styles.note}>进入工作台后请核对并选择本轮 Build；测试 Run 仍需在原页面选择。</p>
      <ProjectBuildReadiness scope={scope} build={fixed}/>
      <ProjectBuildOutput api={api} scope={scope} build={fixed} onAccessRejected={onAccessRejected}/>
      <header className={styles.heading}><h3>本轮当前测试记录</h3><span>{data.unavailableCount > 0 || data.hasMore || data.unindexedRunCount > 0 ? "读集未完整" : `${data.runs.length} 个当前运行`}</span></header>
      {data.unavailableCount > 0 && <p className={styles.notice}>{data.unavailableCount} 条测试记录暂不可读，以下仅为已读取范围。</p>}{data.hasMore && <p className={styles.notice}>测试读集尚未完整，不汇总为全部结果。</p>}
      {data.unindexedRunCount > 0 && <p className={styles.notice}>{data.unindexedRunCount} 个历史运行尚未提供可核对的当前索引，未当作当前运行展示。</p>}
      {data.runs.length > 0 ? <div className={styles.runs}>{data.runs.map(run => <article className={styles.run} key={run.runId}>
        <h4>{run.request.title} · Run v{run.revision}</h4><small>{run.requestRevision === run.request.revision ? `固定 / 当前请求 v${run.requestRevision}` : `Run 固定请求 v${run.requestRevision} · 请求当前 v${run.request.revision}`} · {runStates[run.status] ?? run.status} · {run.sourceStatus === "current" ? "来源当前可读" : "来源需重核"}</small>
        <p>{run.currentProjection ? <>{resultNames[run.currentProjection.result] ?? run.currentProjection.result}{(run.sourceStatus !== "current" || run.currentProjection.sourceStatus !== "current") && " · 来源需重核（原固定判定，当前适用性尚未确认）"}</> : "尚无与当前固定依据一致的已保存判定。"}</p>
        <p>本运行固定覆盖：样件 {print(run.coverage.sampleCount)} · 测试项 {print(run.coverage.itemCount)} · 配对 {print(run.coverage.pairCount)}</p><small>已登记测量记录配对 {print(run.coverage.measuredPairCount)} · 尚缺测量记录配对 {print(run.coverage.missingPairCount)}</small>
        <details><summary>固定身份、原时间与测量原值</summary>
          <dl className={styles.identityFacts}><div><dt>Run 标识 / 固定版本</dt><dd>{run.runId} · v{run.revision}<small>版本标识 {run.versionId}</small></dd></div><div><dt>请求标识 / Run 固定引用</dt><dd>{run.request.id} · v{run.requestRevision}</dd></div><div><dt>请求当前版本</dt><dd>v{run.request.revision} · {sourceState(run.request.sourceStatus)}</dd></div><div><dt>运行记录原时点</dt><dd>{run.createdAt}</dd></div>{run.currentProjection && <div><dt>已有数值判定版本</dt><dd>{run.currentProjection.id} · v{run.currentProjection.revision}<small>对应 Run v{run.currentProjection.runRevision} · {sourceState(run.currentProjection.sourceStatus)}</small></dd></div>}
          {([ ["实际开测", run.runSnapshot.actual_start], ["实际结束", run.runSnapshot.actual_end], ["最终结果返回", run.runSnapshot.final_result] ] as const).map(([label, clock]) => <div key={label}><dt>{label}原时点</dt><dd>{clock ? <><time dateTime={clock.occurred_at}>{clock.occurred_at}</time> · {clock.original_timezone}<small>系统收到记录：{clock.received_at}</small></> : "尚未登记"}</dd></div>)}</dl>
          {run.runSnapshot.measurements.length > 0 ? <div className={styles.scroll}><table className={styles.measurements}><thead><tr><th>样件标识</th><th>测试项标识</th><th>原值 / 单位</th><th>观测原时点</th></tr></thead><tbody>{run.runSnapshot.measurements.map(value => <tr key={value.id}><td>{value.coverage.sample_id}</td><td>{value.coverage.item_id}</td><td>{value.raw_value ?? "原值未登记"} {value.unit ?? "单位未登记"}</td><td>{value.observed_at ?? "尚未登记"}<small>{value.observed_timezone ?? "原时区未登记"}</small></td></tr>)}</tbody></table></div> : <p>本运行尚无已登记测量原值。</p>}
          {([ ["具名专业结论", run.runSnapshot.professional_conclusion], ["具名处置意见", run.runSnapshot.disposition] ] as const).map(([label, conclusion]) => conclusion && typeof conclusion.text === "string" && typeof conclusion.actor_id === "string" ? <div className={styles.statement} key={label}><p>{label}：{conclusion.text}</p><small>具名人员标识：{conclusion.actor_id}</small></div> : null)}
          <a className={styles.link} href={workHref(scope, fixed.id, "verification", "results")}>查看原测试工作台的完整记录<ArrowRight size={12}/></a>
        </details>
      </article>)}</div> : <p className={styles.notice}>{data.unavailableCount > 0 || data.hasMore || data.unindexedRunCount > 0 ? "当前没有可展示的测试运行，读取范围尚不完整。" : "当前可读范围内尚无本轮测试 Run。"}</p>}
      <p className={styles.note}>已有判定只适用于对应固定测试范围，不代表整轮完成、阶段通过或制造放行。</p>
    </>}
  </section>;
}
