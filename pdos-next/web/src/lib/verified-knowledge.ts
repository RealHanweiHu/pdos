import { sameCandidateCommand, type DomainCommand } from "./domain-candidate";
import { validMaterialPreview, validMaterialReceipt, type MaterialCommand } from "./category-materials";
import { candidateOperation, parseKnowledgePayload, runKnowledgeRequest, type KnowledgePending, type KnowledgeScope } from "./knowledge-experience";
import { workRecord, workUuid, type ProjectWorkApi } from "./project-work";

export type KnowledgeReview = { responsible_id: string; applicability_scope: string; review_due_at: string };
export type KnowledgeReviewStatus = KnowledgeReview & { state: "draft" | "verified" | "needs_review"; label: string; priority: number; verified_by: string | null; draft_origin: "ai_draft"; basis_count?: number };
export type AnswerKnowledgeSeed = { command_scope: { category_id: string; product_id: string | null; expected_revision: number }; operation: "category.knowledge.add" | "category.knowledge.promote" | typeof candidateOperation; payload: Record<string, unknown>; question: string; answer: string; basis_count: number; people: { id: string; name: string }[]; default_responsible_id: string; draft_origin: "ai_draft" };
export type AnswerKnowledgePending = { stage: "inputs" | "preview" | "execute"; command: DomainCommand };
export type VerifiedAnswer = { id: string; lineage_id: string; version: number; content: { title: string; question: string; answer: string; draft_origin: "ai_draft" }; review: KnowledgeReviewStatus; basis_count: number };
export type KnowledgeShare = { kind: "missing_material" | "shared_feedback"; run_id: string; feedback_id: string | null; question: string; answer: string | null; search_scope: Record<string, string | null>; recipient: { id: string; name: string; category_id: string; category_name: string }; preview_digest: string };
export const knowledgeAnswerRoot = (category: string) => `v1/categories/${category}/experience`;
export function parseAnswerSeed(value: unknown, category: string): AnswerKnowledgeSeed {
  if (!workRecord(value) || !workRecord(value.command_scope) || value.command_scope.category_id !== category || !(value.command_scope.product_id === null || workUuid(value.command_scope.product_id)) || !Number.isSafeInteger(value.command_scope.expected_revision) || Number(value.command_scope.expected_revision) < 1 || !["category.knowledge.add", "category.knowledge.promote", candidateOperation].includes(String(value.operation)) || !workRecord(value.payload) || typeof value.question !== "string" || typeof value.answer !== "string" || !value.answer.trim() || !Number.isSafeInteger(value.basis_count) || Number(value.basis_count) < 0 || !Array.isArray(value.people) || !value.people.every(person => workRecord(person) && workUuid(person.id) && typeof person.name === "string") || !workUuid(value.default_responsible_id) || value.draft_origin !== "ai_draft") throw new Error("知识材料尚未完整读取。");
  return value as AnswerKnowledgeSeed;
}
export function answerKnowledgeCommand(seed: AnswerKnowledgeSeed, value: { title: string; answer: string; review: KnowledgeReview; deidentified: boolean }): AnswerKnowledgePending {
  if (!value.title.trim() || !value.answer.trim() || !seed.people.some(person => person.id === value.review.responsible_id) || !value.review.applicability_scope.trim() || !Number.isFinite(Date.parse(value.review.review_due_at))) throw new Error("请填写标题、内容、负责人、适用范围和复核日期。");
  const payload = structuredClone(seed.payload);
  payload.knowledge_review = structuredClone(value.review);
  if (seed.operation === candidateOperation) { payload.title = value.title.trim(); payload.lesson = value.answer.trim(); }
  else { payload.content = { ...(payload.content as Record<string, unknown>), title: value.title.trim(), answer: value.answer.trim() }; if (seed.operation === "category.knowledge.promote") payload.deidentified_confirmed = value.deidentified; }
  if (seed.operation === "category.knowledge.promote" && !value.deidentified) throw new Error("请完成去标识整理后勾选确认。");
  const reads = seed.operation === candidateOperation ? [...new Map((payload.sources as { id: string; revision: number }[]).map(source => [source.id, { artifact_id: source.id, expected_revision: source.revision }])).values()] : [];
  return { stage: seed.operation === candidateOperation ? "inputs" : seed.operation === "category.knowledge.promote" ? "preview" : "execute", command: { ...structuredClone(seed.command_scope), command_id: crypto.randomUUID(), idempotency_key: crypto.randomUUID(), operation: seed.operation, source_read_set: reads, payload } };
}
export function restoreAnswerKnowledge(value: unknown, category: string): AnswerKnowledgePending | null {
  if (!workRecord(value) || !["inputs", "preview", "execute"].includes(String(value.stage)) || !workRecord(value.command)) return null;
  const command = value.command;
  if (command.category_id !== category || !workUuid(command.command_id) || !workUuid(command.idempotency_key) || !(command.product_id === null || workUuid(command.product_id)) || !Number.isSafeInteger(command.expected_revision) || Number(command.expected_revision) < 1 || !Array.isArray(command.source_read_set) || !workRecord(command.payload) || ![candidateOperation, "category.knowledge.add", "category.knowledge.promote"].includes(String(command.operation))) return null;
  const review = command.payload.knowledge_review;
  if (!workRecord(review) || !workUuid(review.responsible_id) || typeof review.applicability_scope !== "string" || !review.applicability_scope.trim() || typeof review.review_due_at !== "string" || !Number.isFinite(Date.parse(review.review_due_at))) return null;
  if (command.operation !== candidateOperation && command.product_id !== null || command.operation === candidateOperation && value.stage === "preview") return null;
  return structuredClone(value) as AnswerKnowledgePending;
}
/** The native command boundary owns authorization, T1/T2 policy and idempotency. */
export async function runAnswerKnowledge(api: ProjectWorkApi, pending: AnswerKnowledgePending, principal: string, onStage: (value: AnswerKnowledgePending) => void) {
  const command = pending.command, root = `v1/categories/${command.category_id}/commands`;
  if (command.operation === candidateOperation) {
    const scope: KnowledgeScope = { categoryId: command.category_id, productId: command.product_id, principalId: principal, projectId: String(command.payload.project_id ?? "") };
    parseKnowledgePayload(command.payload, candidateOperation, scope);
    return runKnowledgeRequest(api, pending as KnowledgePending, scope, value => onStage(value), () => true);
  }
  if (pending.stage === "preview") {
    const value = await api<unknown>(`${root}/preview`, command);
    if (!validMaterialPreview(value, command as MaterialCommand) || !sameCandidateCommand(command, value.command as DomainCommand)) throw new Error("原去标识请求尚未核对，请保留原请求。");
    return { stage: "preview" as const, prepared: value };
  }
  const receipt = await api<unknown>(root, command);
  if (!validMaterialReceipt(receipt, command as MaterialCommand)) throw new Error("知识保存回执待读回，请重试原请求。");
  return { stage: "saved" as const, receipt, command };
}
export function parseKnowledgeShare(value: unknown, category: string, run: string): KnowledgeShare {
  if (!workRecord(value) || !["missing_material", "shared_feedback"].includes(String(value.kind)) || value.run_id !== run || typeof value.question !== "string" || !(value.answer === null || typeof value.answer === "string") || !workRecord(value.recipient) || value.recipient.category_id !== category || !workUuid(value.recipient.id) || typeof value.recipient.name !== "string" || typeof value.recipient.category_name !== "string" || !workRecord(value.search_scope) || value.search_scope.category_id !== category || typeof value.preview_digest !== "string" || !/^[a-f0-9]{64}$/.test(value.preview_digest)) throw new Error("分享范围和接收人尚未完整读取。");
  return value as KnowledgeShare;
}
export function knowledgeShareRequest(value: KnowledgeShare, requestKey: string) { return { run_id: value.run_id, kind: value.kind, feedback_id: value.feedback_id, request_key: requestKey, preview_digest: value.preview_digest }; }
