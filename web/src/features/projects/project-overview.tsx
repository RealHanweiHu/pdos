"use client";

import { useEffect, useState, type ReactNode } from "react";
import { ArrowRight, CalendarBlank, ClipboardText, Flag, Package, Robot, Users, Warning } from "@phosphor-icons/react";
import { actionTarget, available, dateText, healthTone, readProjectOverview, slipText, type CockpitApi, type OverviewAction, type ProjectOverview } from "@/lib/project-cockpit";
import styles from "./project-views.module.css";
import own from "./project-overview.module.css";

type Scope = { categoryId: string; productId: string; projectId: string };
type Props = {
  api: CockpitApi; scope: Scope; principalId: string; readVersion?: number;
  onOpen: (view: string, panel?: string | null) => void;
  onWriteUpdate: () => void;
  children?: ReactNode;
};

const kindIcon: Record<OverviewAction["kind"], ReactNode> = {
  blocked: <Warning size={15} aria-hidden="true"/>, receive: <ClipboardText size={15} aria-hidden="true"/>, decide: <Flag size={15} aria-hidden="true"/>,
};

function Section({ title, icon, tail, children }: { title: string; icon?: ReactNode; tail?: ReactNode; children: ReactNode }) {
  return <section className={styles.section} aria-label={title}><h2>{icon}{title}{tail !== undefined && <span>{tail}</span>}</h2>{children}</section>;
}
function who(person: { name: string | null } | null | undefined, principalId: string, id?: string) {
  if (!person) return "负责人未记录";
  return id === principalId ? `${person.name ?? "本人"}（本人）` : person.name ?? "姓名暂不可读";
}
function Missing({ reason }: { reason: string }) { return <p role="status" className={styles.panelEmpty}>{reason}</p>; }

export function ProjectOverviewView({ api, scope, principalId, readVersion = 0, onOpen, onWriteUpdate, children }: Props) {
  const { categoryId, productId, projectId } = scope;
  const [attempt, setAttempt] = useState(0);
  const key = JSON.stringify([categoryId, productId, projectId, principalId, readVersion, attempt]);
  const [reading, setReading] = useState<{ key: string; api: CockpitApi; data: ProjectOverview | null; error: string } | null>(null);
  useEffect(() => {
    let active = true;
    void readProjectOverview(api, { categoryId, productId, projectId }).then(data => { if (active) setReading({ key, api, data, error: "" }); })
      .catch(failure => { if (active) setReading({ key, api, data: null, error: (failure as Error).message }); });
    return () => { active = false; };
  }, [api, categoryId, productId, projectId, key]);
  const current = reading?.key === key && reading.api === api ? reading : null;
  if (!current) return <p role="status" className={styles.unknown}>正在读取项目概览…</p>;
  if (!current.data) return <div role="alert" className="workspace-read-error"><p>{current.error}</p><button type="button" className={styles.outlineLink} onClick={() => setAttempt(value => value + 1)}>重新读取</button></div>;
  const data = current.data;
  const health = available(data.health) ? data.health : null;
  const node = available(data.next_node) ? data.next_node : null;
  const latest = data.status_update.latest;
  const headline = latest?.fact_summary ?? (health ? health.reason : data.health.reason);

  return <div className={own.overview}>
    <div className={own.intro}>
      <div className={own.introMain}>
        <span className={own.status} data-tone={health ? healthTone(health.state) : "neutral"}><i aria-hidden="true"/>{health?.label ?? "健康度暂不可读"}</span>
        <h2>{headline}</h2>
        {latest && <p className={own.byline}>{who(latest.actor, principalId, latest.actor?.id)} · {dateText(latest.created_at)} 具名状态更新</p>}
      </div>
      <button type="button" className={own.textLink} onClick={() => onOpen("gates")}>查看阶段出口<ArrowRight size={13} aria-hidden="true"/></button>
    </div>
    <div className={own.stageLine}>
      {data.stage.available ? <ol className={own.stages} aria-label="阶段位置">{data.stage.stages.map(stage => <li key={stage.key ?? stage.name} data-state={stage.status} aria-current={stage.status === "current" ? "step" : undefined}><i aria-hidden="true"/>{stage.name}</li>)}</ol> : <p className={styles.unknown}>阶段位置：{data.stage.reason ?? "暂不可读"}</p>}
      {health && <details className={own.rule}><summary>健康度依据</summary>
        <p>{health.reason}</p>
        <p>规则 {health.rule?.id} · v{health.rule?.version}；门禁聚合 {health.basis.gate_state}{health.basis.review_pending ? "；评审待具名决定" : ""}{health.basis.overdue_commitments.length ? `；逾期承诺 ${health.basis.overdue_commitments.length} 项` : ""}</p>
        {!!health.basis.conditions.length && <ul>{health.basis.conditions.map(c => <li key={c.key}>{c.label}：{c.state}</li>)}</ul>}
      </details>}
    </div>

    <div className={own.columns}>
      <div className={own.main}>
        <Section title="需要办理" icon={<ClipboardText size={15}/>} tail={`${data.actions.items.length} 项`}>
          {!!data.actions.partial_reasons.length && <p role="status" className={styles.noteInline}>部分来源暂不可读：{data.actions.partial_reasons.join("；")}</p>}
          {data.actions.items.length === 0 ? <p className={styles.panelEmpty}>当前没有阻塞、待接收或待决定的事项。</p> : data.actions.items.map((item, index) => {
            const target = actionTarget(item);
            return <div className={styles.action} key={`${item.type}:${item.source.id ?? index}`} data-kind={item.kind}>
              {kindIcon[item.kind]}
              <div className={styles.actionBody}><p>{item.title}</p><small><b className={own.kind} data-kind={item.kind}>{item.kind_label}</b> · 负责：{who(item.responsible, principalId, item.responsible?.id)} · {item.reason}</small></div>
              {item.due_at && <span className={styles.tag}>{dateText(item.due_at)}</span>}
              <button type="button" className={own.handle} onClick={() => onOpen(target.view, target.panel)}>{item.responsible?.id === principalId ? "去办理" : "查看"}<ArrowRight size={12} aria-hidden="true"/></button>
            </div>;
          })}
          <p className={styles.panelFoot}>办理在原记录中进行，概览不直接执行命令；只列你有权看到的记录。</p>
        </Section>

        <Section title="风险与问题" icon={<Warning size={15}/>}>
          <div className={own.riskGroups}>
            <div><h3>开放风险</h3>{data.risks.risks.length ? <ul>{data.risks.risks.map(r => <li key={r.id}>{r.title}<small>{who(r.responsible, principalId, r.responsible?.id)}{r.due_date ? ` · 期限 ${dateText(r.due_date)}` : ""}{r.state === "unknown" ? " · 状态待核对" : ""}</small></li>)}</ul> : <p className={styles.unknown}>无开放风险。</p>}</div>
            <div><h3>未关闭问题</h3>{!available(data.risks.issues) ? <p className={styles.unknown}>{data.risks.issues.reason}</p> : data.risks.issues.length ? <ul>{data.risks.issues.map(i => <li key={i.id}>{i.title}<small>风险 {i.risk_label} · {who(i.owner, principalId, i.owner?.id)}</small></li>)}</ul> : <p className={styles.unknown}>无未关闭问题。</p>}<p className={own.hint}>P0/P1 分级未建，按问题记录的风险等级排序。</p></div>
            <div><h3>超期外部等待</h3>{data.risks.overdue_waits.length ? <ul>{data.risks.overdue_waits.map(w => <li key={w.id}>{w.title}{w.blocking && <b className={own.kind} data-kind="blocked">阻塞</b>}<small>{w.target} · {who(w.responsible, principalId, w.responsible?.id)}{w.reason ? ` · ${w.reason}` : ""}</small></li>)}</ul> : <p className={styles.unknown}>无超期外部等待。</p>}</div>
            <div><h3>未来 {data.risks.window_days} 天到期</h3>{data.risks.due_soon.length ? <ul>{data.risks.due_soon.map(d => <li key={`${d.kind}:${d.id}`}>{d.title}<small>{d.kind === "commitment" ? "承诺" : "G0 待办"} · {dateText(d.due_at)} · {who(d.responsible, principalId, d.responsible?.id)}</small></li>)}</ul> : <p className={styles.unknown}>没有即将到期的承诺或待办。</p>}</div>
          </div>
        </Section>

        <Section title="动态与讨论" icon={<CalendarBlank size={15}/>}>
          <div className={own.updatePrompt}><span>{latest ? "最新具名状态更新已置顶在上方。" : "尚无具名状态更新。"}</span><button type="button" className={styles.outlineLink} onClick={onWriteUpdate}>写状态更新</button></div>
          <p className={own.hint}>{data.status_update.cycle.reason}</p>
          {children}
        </Section>
      </div>

      <aside className={own.rail}>
        <Section title={node?.name ? `下一节点 · ${node.name}` : "下一节点"} icon={<Flag size={15}/>}>
          {!node ? <Missing reason={available(data.next_node) ? "" : data.next_node.reason}/> : <div className={styles.sectionBox}>
            <dl className={own.times}>
              <dt>基线</dt><dd>{dateText(node.times.baseline)}</dd>
              <dt>预测</dt><dd>{node.times.forecast ? `${dateText(node.times.forecast.earliest)} — ${dateText(node.times.forecast.latest)}` : "未知"}</dd>
              <dt>承诺</dt><dd>{node.times.commitments.length ? node.times.commitments.map(c => `${dateText(c.promised_at)}${c.fulfilled ? "（已履行）" : ""}`).join("、") : "未知"}</dd>
              <dt>实际</dt><dd>{dateText(node.times.actual)}</dd>
            </dl>
            <p className={own.slip} data-state={node.slip.state}>{slipText(node.slip)}</p>
            <h3 className={own.railHeading}>出口条件</h3>
            {node.exit_conditions.length ? <ul className={own.conditions}>{node.exit_conditions.map(c => <li key={c.key} data-state={c.state}><span>{c.label}</span><b>{c.state_label}</b></li>)}</ul> : <p className={styles.unknown}>尚未采用阶段模板，没有出口条件。</p>}
            <p className={own.placeholder}><b>出口成果：{node.exit_outcomes.label}</b>{node.exit_outcomes.reason}</p>
          </div>}
        </Section>

        <Section title="下一 Build" icon={<Package size={15}/>}>
          {!available(data.next_build) ? <Missing reason={data.next_build.reason}/> : data.next_build.build ? <div className={styles.sectionBox}>
            <h3 className={own.railHeading}>{data.next_build.build.name}</h3>
            <dl className={own.times}>
              <dt>目的</dt><dd>{data.next_build.build.purpose || "待明确"}</dd>
              <dt>配置</dt><dd>{data.next_build.build.engineering_configuration.name} v{data.next_build.build.engineering_configuration.revision} / {data.next_build.build.manufacturing_configuration.name} v{data.next_build.build.manufacturing_configuration.revision}</dd>
              <dt>数量</dt><dd>{data.next_build.build.planned_quantity} {data.next_build.build.unit}</dd>
              <dt>计划</dt><dd>{data.next_build.build.planned_start ? `${dateText(data.next_build.build.planned_start)} 开工` : "开工日期未定"}</dd>
              <dt>验证</dt><dd>{data.next_build.build.verification_objectives || "尚未登记"}</dd>
            </dl>
            {data.next_build.build.source_status !== "current" && <p className={styles.noteInline}>固定依据需重核。</p>}
            <button type="button" className={own.textLink} onClick={() => onOpen("builds", "summary")}>打开试制轮次<ArrowRight size={12} aria-hidden="true"/></button>
          </div> : <p className={styles.panelEmpty}>没有未开工的 Build。{data.next_build.unavailable_count ? `另有 ${data.next_build.unavailable_count} 个轮次暂不可读。` : ""}</p>}
        </Section>

        <Section title="关键承诺" icon={<CalendarBlank size={15}/>} tail={data.key_commitments.length ? `${data.key_commitments.length} 项` : undefined}>
          {data.key_commitments.length ? <ul className={own.compact}>{data.key_commitments.map(c => <li key={c.id}><span>{c.title}{c.for_gate && <b className={own.kind} data-kind="decide">门禁</b>}</span><small>{who(c.promisor, principalId, c.promisor?.id)} → {who(c.recipient, principalId, c.recipient?.id)} · {c.promised_at ? dateText(c.promised_at) : "未给日期"}{c.overdue ? " · 已逾期" : ""}</small></li>)}</ul> : <p className={styles.panelEmpty}>没有未履行的承诺。</p>}
          <button type="button" className={own.textLink} onClick={() => onOpen("plan", "commitments")}>承诺与外部等待<ArrowRight size={12} aria-hidden="true"/></button>
        </Section>

        <Section title="团队" icon={<Users size={15}/>}>
          {!available(data.team) ? <Missing reason={data.team.reason}/> : <>
            <ul className={own.compact}>{data.team.members.map(m => <li key={m.principal_id}><span>{m.name}{m.is_owner && <b className={own.kind} data-kind="decide">负责人</b>}</span><small>{m.roles.join("、") || "未设角色"} · 进行中 {m.open_tasks} 项</small></li>)}</ul>
            {!!data.team.vacant_roles.length && <p className={own.hint}>空缺角色：{data.team.vacant_roles.join("、")}</p>}
            <p className={own.hint}>{data.team.load_note}</p>
          </>}
          <button type="button" className={own.textLink} onClick={() => onOpen("team")}>打开团队<ArrowRight size={12} aria-hidden="true"/></button>
        </Section>

        <Section title="小Pai 值班摘要" icon={<Robot size={15}/>}>
          {!available(data.agent_duty) ? <Missing reason={data.agent_duty.reason}/> : <>
            <p className={own.duty}>{data.agent_duty.total ? `近 ${data.agent_duty.window_days} 天在本项目：${data.agent_duty.items.map(i => `${i.label} ${i.count} 次`).join("、")}。` : `近 ${data.agent_duty.window_days} 天小Pai 未在本项目写入。`}</p>
            <p className={own.hint}>只读，不计入待办。{data.agent_duty.revocable ? "" : data.agent_duty.revocation_note}</p>
          </>}
        </Section>
      </aside>
    </div>
    <details className={own.rules}><summary>概览的计算规则</summary><ul>{data.rules.map(rule => <li key={rule.id}><code>{rule.id}@{rule.version}</code> {rule.text}</li>)}</ul><p>读取于 <time dateTime={data.as_of}>{new Date(data.as_of).toLocaleString()}</time></p></details>
  </div>;
}
