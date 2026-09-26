"use client";

import { Button } from "@/components/ui/button";
import { field, obj, rows, text, type Row } from "@/components/quality/fmea-sources";
import { QuietAnchorValue } from "./change-quiet-sources";

const ids = (v: unknown): string[] => Array.isArray(v) ? v.map(String) : [];
const date = (v: unknown) => typeof v === "string" ? new Date(v).toLocaleString("zh-CN") : "未记录";

export function QuietCreationHistory({ data }: { data: Row }) {
  const origin = obj(data.origin), names = Object.fromEntries(rows(data.people).map(p => [text(p.id), text(p.name)]));
  return <div className="space-y-2 text-xs">
    {data.origin ? <div><p>创建时已核对冻结政策 · {date(origin.checked_at)}</p>
      {rows(origin.requirements).length ? rows(origin.requirements).map(r => <p key={`${r.policy_id}:${obj(r.window).key}`}>创建时命中：政策 v{String(r.policy_version)} · {text(obj(r.window).key).toUpperCase()}；原要求持续保留，窗口结束不会自动免除审批。</p>) : <p>创建时没有生效的冻结窗口；后续提交分析和批准仍会核对届时政策。</p>}
    </div> : <p>历史变更未保存创建时核对记录，不能据此判断当时是否处于冻结期。</p>}
    {rows(data.adoptions).map(a => <details key={text(a.id)} className="rounded-md border p-2"><summary className="cursor-pointer">{text(a.window_key).toUpperCase()} 承接政策 v{String(a.new_policy_version)} · {date(a.created_at)}</summary>
      <p>确认人：{names[text(a.created_by_user_id)] ?? "原具名确认人"}；{text(obj(a.body).reason)}</p>
      <p>原窗口：{date(obj(a.old_window).starts_at)} 至 {date(obj(a.old_window).ends_at)} · {text(obj(a.old_window).planning_basis)}</p>
      <p>承接窗口：{date(obj(a.new_window).starts_at)} 至 {date(obj(a.new_window).ends_at)} · {text(obj(a.new_window).planning_basis)}</p>
      <p>保留原分析和审批历史。承接后须重新提交分析，并按新要求办理例外审批。</p>
    </details>)}
  </div>;
}

export function QuietPolicyAdoption({ data, requirement, busy, write }: { data: Row; requirement: Row; busy: boolean; write: (body: Row) => void }) {
  const ecr = obj(data.ecr), policy = obj(data.latest_policy), oldWindow = obj(requirement.window);
  const window = rows(obj(policy.body).windows).find(w => w.key === oldWindow.key);
  if (ecr.status !== "impact_analysis" || data.can_decide !== true || !window || obj(policy.body).enabled !== true || Number(policy.version) <= Number(requirement.policy_version)) return null;
  const chain = ids(window.approver_ids), oldChain = ids(oldWindow.approver_ids);
  const independent = ![ecr.requested_by_user_id, ecr.analyzed_by_user_id, ...chain].includes(data.actor_id);
  const source = obj(data.latest_policy_sources)[text(window.key)], sourceCurrent = obj(source).current === true;
  const names = Object.fromEntries(rows(data.people).map(p => [text(p.id), text(p.name)]));
  return <details className="space-y-2 rounded-md border p-3 text-xs"><summary className="cursor-pointer font-medium">重新分析：承接最新政策 v{String(policy.version)}</summary>
    <p>当前要求 v{String(requirement.policy_version)} → 最新政策 v{String(policy.version)}；{date(window.starts_at)} 至 {date(window.ends_at)}</p>
    <p>{text(window.planning_basis)}</p><QuietAnchorValue source={source}/>
    <p>审批环节：{oldChain.length} → {chain.length}；新审批顺序：{chain.map(id => names[id] ?? "人员当前不可用").join(" → ")}</p>
    <p>确认将保留原始依据，并以新版同类窗口继续履行冻结义务。窗口结束不会免除审批；需要重新提交影响分析，原审批不能直接沿用。</p>
    {!independent && <p>须由独立于变更申请及新审批链的授权人员确认。</p>}
    {chain.length < oldChain.length && <p>新版审批环节少于原要求，不能承接。</p>}
    <form className="space-y-2" onSubmit={e => { e.preventDefault(); const form = new FormData(e.currentTarget); write({ old_policy_id: requirement.policy_id, new_policy_id: policy.id, window_key: window.key, reason: form.get("reason") }); }}><fieldset disabled={busy || !independent || !sourceCurrent || chain.length < oldChain.length} className="space-y-2">
      <label className="block">承接理由及原影响分析需要更新的内容<textarea name="reason" required maxLength={4000} className={field}/></label>
      <Button size="sm" type="submit">确认承接并继续重新分析</Button>
    </fieldset></form>
  </details>;
}
