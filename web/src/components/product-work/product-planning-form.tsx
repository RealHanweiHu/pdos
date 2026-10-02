"use client";

import { useState } from "react";
import { StrategyForm, type StrategyContent } from "./strategies";
import { DefinitionForm, type DefinitionContent } from "./definitions";
import { type DiscoveryTarget } from "./product-discovery-form";
import { type Evidence, type ProductCatalog, type Workspace } from "./product-work-api";

export type PlanningTarget =
  | { kind: "product"; id: string; code: string; name: string; lifecycle: string }
  | { kind: "work"; id: string; title: string; action_type: string; state: string }
  | { kind: "strategy"; id: string; title: string; revision_number: number; state: string }
  | { kind: "definition"; id: string; title: string; content: DefinitionContent; state: string };
type Content = Record<string, unknown>;
type Props = { value: Content; targets: (DiscoveryTarget | PlanningTarget)[]; line: string | null; evidence: Evidence[]; workspace: Workspace; catalog: ProductCatalog; base: string; onSave: (value: Content) => void; onCancel: () => void };

export function PlanningForm({ capability, ...props }: Props & { capability: "product_strategy" | "product_definition" }) {
  return <div className="space-y-3"><p className="text-sm text-muted-foreground">此处核对草稿内容。应用后再办理路线选择、专业处置、规格确认及具名协审；正式发布仍是独立操作。</p>{props.value.supersedes_id ? <p className="text-sm">原发布版：{props.targets.filter(t => t.kind === "strategy" || t.kind === "definition").find(t => t.id === props.value.supersedes_id)?.title ?? String(props.value.supersedes_id)} · 创建新修订并保留原版</p> : null}{capability === "product_strategy" ? <StrategyCandidate {...props}/> : <DefinitionCandidate {...props}/>}</div>;
}

function StrategyCandidate({ value, targets, line, evidence, workspace, catalog, base, onSave, onCancel }: Props) {
  const [candidate] = useState(() => ({ opportunity_id: String(value.opportunity_id), content: { ...(value as Omit<StrategyContent, "professional_constraints">), owner_user_id: workspace.current_user_id, selected_solution_id: null, professional_constraints: (value.professional_constraints as Omit<StrategyContent["professional_constraints"][number], "id" | "disposition">[]).map((c, i) => ({ ...c, id: `constraint-${i}`, disposition: null })) } as StrategyContent }));
  const work = targets.filter(t => t.kind === "work").filter(t => t.state !== "cancelled" && ["discipline_review", "constraint_review"].includes(t.action_type));
  return <StrategyForm initial={null} revise={false} candidate={candidate} candidateWork={work} opportunities={targets.filter((t): t is DiscoveryTarget => t.kind === "opportunity").map(t => ({ ...t, product_line_id: line, is_latest: true }))} workspace={workspace} catalog={catalog} evidence={evidence} base={base} onSaved={() => {}} onCancel={onCancel} onReview={({ opportunity_id, content }) => onSave({ opportunity_id, supersedes_id: value.supersedes_id ?? null, title: content.title, canvas: content.canvas, route_comparisons: content.route_comparisons, professional_constraints: content.professional_constraints.map(c => ({ discipline: c.discipline, statement: c.statement, work_item_id: c.work_item_id })), unknowns: content.unknowns, decision_reason: content.decision_reason })}/>;
}

function DefinitionCandidate({ value, targets, line, evidence, workspace, catalog, base, onSave, onCancel }: Props) {
  const [candidate] = useState(() => ({ product_id: String(value.product_id), strategy_id: String(value.strategy_id), content: { ...(value as Omit<DefinitionContent, "items">), owner_user_id: workspace.current_user_id, reviewers: {}, items: (value.items as Omit<DefinitionContent["items"][number], "owner_user_id" | "state" | "disposition_reason">[]).map(item => ({ ...item, owner_user_id: null, state: "needs_confirmation" as const, disposition_reason: null })) } as DefinitionContent }));
  const previous = targets.find(t => t.kind === "definition" && t.id === value.supersedes_id);
  const stableKeys = previous?.kind === "definition" ? previous.content.items.map(i => i.item_key) : [];
  return <DefinitionForm initial={null} revise={false} candidate={candidate} candidateStableKeys={stableKeys} candidateProducts={targets.filter(t => t.kind === "product").map(t => ({ ...t, product_line_id: line ?? "" }))} strategies={targets.filter(t => t.kind === "strategy").map(t => ({ ...t, product_line_id: line }))} workspace={workspace} catalog={catalog} evidence={evidence} base={base} onSaved={() => {}} onCancel={onCancel} onReview={({ product_id, strategy_id, content }) => onSave({ product_id, strategy_id, supersedes_id: value.supersedes_id ?? null, title: content.title, target_users: content.target_users, scenarios: content.scenarios, included_features: content.included_features, excluded_features: content.excluded_features, region_constraints: content.region_constraints, target_cost: content.target_cost, price_position: content.price_position, launch_window: content.launch_window, service_requirements: content.service_requirements, success_criteria: content.success_criteria, change_reason: content.change_reason, items: content.items.map(i => ({ item_key: i.item_key, title: i.title, target_text: i.target_text, target_value: i.target_value, unit: i.unit, tolerance: i.tolerance, conditions: i.conditions, priority: i.priority, required_for_release: i.required_for_release, rationale: i.rationale, verification_method: i.verification_method, acceptance_criterion: i.acceptance_criterion, verification_stage: i.verification_stage })) })}/>;
}
