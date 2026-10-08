import {
  issueTarget, qualityCapability, qualityRecord, qualityRevision, qualitySame, qualityText,
  type QualityIssue,
} from "./build-quality-loop-view";

type FixedAction = Record<string, unknown> & {
  id: string; kind: "corrective" | "preventive"; text: string;
  executor_id: string; completion: unknown;
};
export type CapaTextSnapshot = Record<string, unknown> & {
  id: string; hypotheses: Record<string, unknown>[]; actions: FixedAction[];
  requirement: Record<string, unknown> & {
    method: string; acceptance: string; observation_until: string; required_failure_ids: string[];
  };
};
export type CapaTextDraft = {
  issueVersionId: string; issueId: string; revision: number;
  fixedCapa: CapaTextSnapshot; actions: { id: string; text: string }[];
};

export function capaTextSnapshot(row: QualityIssue): CapaTextSnapshot | null {
  const capa = row.issue.capa;
  if (!qualityRecord(capa) || typeof capa.id !== "string" || !capa.id ||
      !Array.isArray(capa.actions) || !capa.actions.length ||
      !capa.actions.every(action => qualityRecord(action) && typeof action.id === "string" && !!action.id &&
        ["corrective", "preventive"].includes(String(action.kind)) && typeof action.text === "string" &&
        typeof action.executor_id === "string" && !!action.executor_id && "completion" in action) ||
      new Set(capa.actions.map(action => (action as Record<string, unknown>).id)).size !== capa.actions.length ||
      !Array.isArray(capa.hypotheses) || !capa.hypotheses.length ||
      !capa.hypotheses.every(hypothesis => qualityRecord(hypothesis) && typeof hypothesis.text === "string" &&
        Array.isArray(hypothesis.sources) && hypothesis.sources.length > 0) ||
      !qualityRecord(capa.requirement) || typeof capa.requirement.method !== "string" ||
      typeof capa.requirement.acceptance !== "string" || typeof capa.requirement.observation_until !== "string" ||
      !Array.isArray(capa.requirement.required_failure_ids) || !capa.requirement.required_failure_ids.length ||
      !capa.requirement.required_failure_ids.every(identity => typeof identity === "string" && !!identity)) return null;
  return structuredClone(capa) as CapaTextSnapshot;
}

export function capaTextEditable(row: QualityIssue): boolean {
  const capa = capaTextSnapshot(row);
  return !!capa && row.is_current === true && row.source_status === "current" &&
    qualityRevision(row.revision) && qualityCapability(row.capabilities, "quality.capa.draft") &&
    ["triaged", "actioning"].includes(row.issue.status) && row.issue.root_cause === null &&
    row.issue.closure === null && row.issue.needs_recheck === false && row.issue.merged_into === null &&
    capa.actions.every(action => action.completion === null) && capa.effectiveness === null &&
    Array.isArray(capa.effectiveness_history) && capa.effectiveness_history.length === 0;
}

export function capaTextDraft(row: QualityIssue): CapaTextDraft | null {
  const fixedCapa = capaTextSnapshot(row);
  return fixedCapa ? {
    issueVersionId: row.id, issueId: row.issue_id, revision: row.revision, fixedCapa,
    actions: fixedCapa.actions.map(action => ({ id: action.id, text: action.text })),
  } : null;
}

export function capaDraftTextPayload(row: QualityIssue, draft: CapaTextDraft): Record<string, unknown> {
  const capa = capaTextSnapshot(row);
  if (!capaTextEditable(row) || !capa || draft.issueVersionId !== row.id || draft.issueId !== row.issue_id ||
      draft.revision !== row.revision || !qualitySame(draft.fixedCapa, capa) ||
      draft.actions.length !== capa.actions.length ||
      draft.actions.some((action, index) => action.id !== capa.actions[index].id)) {
    throw new Error("仅当前服务器允许的未决 CAPA 可作文本续版；原身份、版本和固定要求必须保持。");
  }
  const actions = capa.actions.map((action, index) => ({ ...structuredClone(action), text: qualityText(draft.actions[index].text) }));
  if (actions.every((action, index) => action.text === capa.actions[index].text)) {
    throw new Error("措施文本尚未改变，本次没有提交。");
  }
  // Copy the server's exact fixed material, including source positions, nulls and original time spelling.
  return {
    ...issueTarget(row), capa_id: capa.id, hypotheses: structuredClone(capa.hypotheses), actions,
    requirement: structuredClone(capa.requirement),
  };
}
