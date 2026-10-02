"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { OpportunityForm, type OpportunityDraft, type Solution } from "./opportunities";
import { PlanFields, type Plan } from "./experiments";
import { type Evidence, type Workspace } from "./product-work-api";

export type DiscoveryTarget = { id: string; kind: "segment" | "opportunity"; title: string; version: number; segment_id: string; state: "exploring" | "evaluating" | "selected" | "deferred" | "closed"; solutions: Solution[] };
type Content = Record<string, unknown>;

export function DiscoveryForm({ capability, value, targets, evidence, workspace, base, onSave, onCancel }: { capability: "opportunity_mapping" | "experiment_design"; value: Content; targets: DiscoveryTarget[]; evidence: Evidence[]; workspace: Workspace; base: string; onSave: (content: Content) => void; onCancel: () => void }) {
  if (capability === "opportunity_mapping") return <OpportunityCandidate value={value} targets={targets} evidence={evidence} base={base} onSave={onSave} onCancel={onCancel}/>;
  return <ExperimentCandidate value={value} targets={targets} evidence={evidence} workspace={workspace} onSave={onSave} onCancel={onCancel}/>;
}

function OpportunityCandidate({ value, targets, evidence, base, onSave, onCancel }: { value: Content; targets: DiscoveryTarget[]; evidence: Evidence[]; base: string; onSave: (content: Content) => void; onCancel: () => void }) {
  const [candidate] = useState<OpportunityDraft>(() => ({ ...(value as Omit<OpportunityDraft, "solutions">), supersedes_id: null, requirement_links: [], state: "exploring", selected_solution_id: null, solutions: (value.solutions as Omit<Solution, "id">[]).map((solution, i) => ({ ...solution, id: `candidate-${i}` })) } as OpportunityDraft));
  return <OpportunityForm initial={null} candidate={candidate} segments={targets.filter(t => t.kind === "segment").map(t => ({ ...t, is_latest: true }))} items={targets.filter(t => t.kind === "opportunity").map(t => ({ ...t, is_latest: true }))} evidence={evidence} base={base} onSaved={() => {}} onCancel={onCancel} onReview={draft => {
    onSave({ segment_id: draft.segment_id, parent_opportunity_id: draft.parent_opportunity_id, title: draft.title, importance: draft.importance, satisfaction: draft.satisfaction, importance_basis: draft.importance_basis, satisfaction_basis: draft.satisfaction_basis, revision_reason: draft.revision_reason, solutions: draft.solutions.map(solution => ({ title: solution.title, approach: solution.approach, rationale: solution.rationale, constraints: solution.constraints, unknowns: solution.unknowns })) });
  }}/>;
}

function ExperimentCandidate({ value, targets, evidence, workspace, onSave, onCancel }: { value: Content; targets: DiscoveryTarget[]; evidence: Evidence[]; workspace: Workspace; onSave: (content: Content) => void; onCancel: () => void }) {
  const [opportunityId, setOpportunityId] = useState(String(value.opportunity_id));
  const [solutionId, setSolutionId] = useState(String(value.solution_id));
  const [plan, setPlan] = useState<Plan>(() => ({ ...value, owner_user_id: workspace.current_user_id } as Plan));
  const selected = targets.find(t => t.kind === "opportunity" && t.id === opportunityId);
  const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
  return <form className="space-y-3 rounded-md border p-3" onSubmit={event => { event.preventDefault(); onSave({ opportunity_id: opportunityId, solution_id: solutionId, dimension: plan.dimension, hypothesis: plan.hypothesis, method: plan.method, sample_basis: plan.sample_basis, success_criterion: plan.success_criterion, falsification_criterion: plan.falsification_criterion, due_at: plan.due_at, sources: plan.sources }); }}>
    <h5 className="font-medium">核对实验计划</h5><div className="grid gap-3 sm:grid-cols-2"><label>机会版本<select required className={field} value={opportunityId} onChange={event => { setOpportunityId(event.target.value); setSolutionId(""); }}><option value="">选择本次原机会</option>{targets.filter(t => t.kind === "opportunity" && t.state !== "closed").map(t => <option key={t.id} value={t.id}>{t.title} · v{t.version}</option>)}</select></label><label>要验证的方案<select required className={field} value={solutionId} onChange={event => setSolutionId(event.target.value)}><option value="">选择原方案</option>{selected?.solutions.map(s => <option key={s.id} value={s.id}>{s.title}</option>)}</select></label></div>
    <PlanFields plan={plan} evidence={evidence} members={workspace.members.filter(m => m.id === workspace.current_user_id)} ownerLocked onChange={setPlan}/>
    <p className="text-sm text-muted-foreground">应用后为原发起人负责的实验草稿。批准、开始和实际结果仍须另行办理；这里的来源只作为计划依据。</p>
    <div className="flex gap-2"><Button disabled={!selected || !selected.solutions.some(s => s.id === solutionId)}>保存此条核对内容</Button><Button type="button" variant="outline" onClick={onCancel}>取消</Button></div>
  </form>;
}
